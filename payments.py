import logging
from typing import Optional

import httpx
from telegram import Update, LabeledPrice
from telegram.ext import ContextTypes

from config import (
    STRIPE_PROVIDER_TOKEN, CRYPTOBOT_API_TOKEN, CRYPTOBOT_API_URL,
    get_plan_prices,
)
from subscription import (
    create_subscription, record_payment, PLAN_LABELS,
)

logger = logging.getLogger(__name__)

PLAN_LABELS_FULL = PLAN_LABELS  # re-export for bot.py convenience


# ---------------------------------------------------------------------------
# Telegram Stars
# ---------------------------------------------------------------------------

async def send_stars_invoice(update: Update, context: ContextTypes.DEFAULT_TYPE, plan: str):
    prices = get_plan_prices(plan)
    label = PLAN_LABELS.get(plan, plan)
    payload = f"sub_{plan}_stars"
    await context.bot.send_invoice(
        chat_id=update.effective_user.id,
        title=f"ClawdVC — {label}",
        description=f"Subscription: {label}",
        payload=payload,
        currency="XTR",
        prices=[LabeledPrice("Subscription", prices["stars"])],
    )


# ---------------------------------------------------------------------------
# Stripe
# ---------------------------------------------------------------------------

async def send_stripe_invoice(update: Update, context: ContextTypes.DEFAULT_TYPE, plan: str):
    if not STRIPE_PROVIDER_TOKEN:
        await update.callback_query.edit_message_text(
            "Card payments are not configured yet. Please use Stars or Crypto."
        )
        return
    prices = get_plan_prices(plan)
    label = PLAN_LABELS.get(plan, plan)
    payload = f"sub_{plan}_stripe"
    await context.bot.send_invoice(
        chat_id=update.effective_user.id,
        title=f"ClawdVC — {label}",
        description=f"Subscription: {label}",
        payload=payload,
        provider_token=STRIPE_PROVIDER_TOKEN,
        currency="USD",
        prices=[LabeledPrice("Subscription", prices["stripe_cents"])],
        need_email=True,
    )


# ---------------------------------------------------------------------------
# CryptoBot
# ---------------------------------------------------------------------------

async def create_crypto_invoice(user_id: int, plan: str) -> Optional[str]:
    """Create a CryptoBot invoice and return the payment URL, or None on error."""
    if not CRYPTOBOT_API_TOKEN:
        return None
    prices = get_plan_prices(plan)
    label = PLAN_LABELS.get(plan, plan)
    payload = f"sub_{plan}_crypto_{user_id}"
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{CRYPTOBOT_API_URL}/createInvoice",
                headers={"Crypto-Pay-API-Token": CRYPTOBOT_API_TOKEN},
                json={
                    "asset": "USDT",
                    "amount": prices["crypto_usdt"],
                    "description": f"ClawdVC {label} subscription",
                    "payload": payload,
                    "expires_in": 3600,
                },
            )
            data = resp.json()
            if data.get("ok"):
                record_payment(
                    user_id=user_id,
                    amount=prices["crypto_usdt"],
                    currency="USDT",
                    payment_method="crypto",
                    plan=plan,
                    payment_id=str(data["result"]["invoice_id"]),
                    status="pending",
                )
                return data["result"]["pay_url"]
            logger.error("CryptoBot createInvoice failed: %s", data)
    except Exception as e:
        logger.error("CryptoBot createInvoice error: %s", e)
    return None


async def check_crypto_payment(user_id: int) -> Optional[str]:
    """Check if any pending crypto payment for user_id has been paid.
    Returns the plan name if paid, or None.
    """
    if not CRYPTOBOT_API_TOKEN:
        return None
    from storage import get_conn
    conn = get_conn()
    pending = conn.execute(
        "SELECT payment_id, plan FROM payments WHERE user_id = ? AND payment_method = 'crypto' AND status = 'pending' ORDER BY id DESC LIMIT 1",
        (user_id,),
    ).fetchone()
    if not pending:
        return None
    invoice_id = pending["payment_id"]
    plan = pending["plan"]
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{CRYPTOBOT_API_URL}/getInvoices",
                headers={"Crypto-Pay-API-Token": CRYPTOBOT_API_TOKEN},
                params={"invoice_ids": invoice_id},
            )
            data = resp.json()
            if data.get("ok"):
                items = data["result"].get("items", [])
                if items and items[0].get("status") == "paid":
                    # Mark payment as completed and create subscription
                    conn.execute(
                        "UPDATE payments SET status = 'completed' WHERE payment_id = ? AND user_id = ?",
                        (invoice_id, user_id),
                    )
                    conn.commit()
                    create_subscription(user_id, plan, "crypto")
                    return plan
    except Exception as e:
        logger.error("CryptoBot check error: %s", e)
    return None


# ---------------------------------------------------------------------------
# Shared Telegram payment callbacks
# ---------------------------------------------------------------------------

async def precheckout_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.pre_checkout_query
    payload = query.invoice_payload
    # Validate payload format: sub_{plan}_{method}
    parts = payload.split("_", 2)
    if len(parts) >= 3 and parts[0] == "sub":
        await query.answer(ok=True)
    else:
        await query.answer(ok=False, error_message="Invalid payment payload.")


async def successful_payment_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    payment = update.message.successful_payment
    payload = payment.invoice_payload
    parts = payload.split("_", 2)
    if len(parts) < 3 or parts[0] != "sub":
        return

    plan = parts[1]
    method = parts[2]
    user_id = update.effective_user.id
    currency = payment.currency
    amount = payment.total_amount

    payment_id = payment.telegram_payment_charge_id or ""

    record_payment(
        user_id=user_id,
        amount=str(amount),
        currency=currency,
        payment_method=method,
        plan=plan,
        payment_id=payment_id,
        status="completed",
    )
    sub = create_subscription(user_id, plan, method)

    label = PLAN_LABELS.get(plan, plan)
    if sub["expires_at"]:
        expires_str = sub["expires_at"][:10]
        msg = f"Payment successful! Your {label} subscription is active until {expires_str}."
    else:
        msg = f"Payment successful! Your {label} (Lifetime) subscription is now active."

    await update.message.reply_text(msg + "\n\nUse /status to check your plan.")
