import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from config import (
    ADMIN_IDS, FREE_DAILY_LIMIT, FREE_TRIAL_DAYS, MESSAGE_PACK_SIZE,
    PAID_DAILY_LIMIT,
    PRICE_PERSONAL_1W_STARS, PRICE_PERSONAL_1M_STARS,
    PRICE_PERSONAL_3M_STARS, PRICE_PERSONAL_6M_STARS,
    PRICE_GROUP_1W_STARS, PRICE_GROUP_1M_STARS,
    PRICE_GROUP_3M_STARS, PRICE_GROUP_6M_STARS,
    PRICE_PACK_STARS,
    PRICE_PERSONAL_1W_USD, PRICE_PERSONAL_1M_USD,
    PRICE_PERSONAL_3M_USD, PRICE_PERSONAL_6M_USD,
    PRICE_GROUP_1W_USD, PRICE_GROUP_1M_USD,
    PRICE_GROUP_3M_USD, PRICE_GROUP_6M_USD,
    PRICE_PACK_USD,
)
from storage import get_conn

logger = logging.getLogger(__name__)

PERIOD_DAYS = {"1w": 7, "1m": 30, "3m": 90, "6m": 180}
PERIOD_LABELS = {"1w": "1 Week", "1m": "1 Month", "3m": "3 Months", "6m": "6 Months"}

# ---------------------------------------------------------------------------
# User lifecycle
# ---------------------------------------------------------------------------

def _now() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def ensure_user(user_id: int, username: str = "", first_name: str = "") -> dict:
    conn = get_conn()
    now = _now()
    trial_expires = (datetime.now(tz=timezone.utc) + timedelta(days=FREE_TRIAL_DAYS)).isoformat()
    conn.execute(
        """INSERT INTO users (user_id, username, first_name, first_seen, trial_expires)
           VALUES (?, ?, ?, ?, ?)
           ON CONFLICT(user_id) DO NOTHING""",
        (user_id, username, first_name, now, trial_expires),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
    return {
        "user_id": row["user_id"],
        "first_seen": row["first_seen"],
        "trial_expires": row["trial_expires"],
        "is_new": row["first_seen"] == now,
    }


def get_user(user_id: int) -> Optional[dict]:
    row = get_conn().execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
    if row:
        return dict(row)
    return None


def is_trial_active(user_id: int) -> bool:
    user = get_user(user_id)
    if not user:
        return False
    expires = datetime.fromisoformat(user["trial_expires"])
    return datetime.now(tz=timezone.utc) < expires


# ---------------------------------------------------------------------------
# Subscription queries
# ---------------------------------------------------------------------------

def get_active_subscription(user_id: int, chat_id: int) -> Optional[dict]:
    now = _now()
    row = get_conn().execute(
        """SELECT * FROM subscriptions
           WHERE user_id = ? AND chat_id = ? AND status = 'active' AND expires_at > ?
           ORDER BY expires_at DESC LIMIT 1""",
        (user_id, chat_id, now),
    ).fetchone()
    return dict(row) if row else None


def get_group_subscription(chat_id: int) -> Optional[dict]:
    now = _now()
    row = get_conn().execute(
        """SELECT * FROM subscriptions
           WHERE chat_id = ? AND status = 'active' AND expires_at > ?
           ORDER BY expires_at DESC LIMIT 1""",
        (chat_id, now),
    ).fetchone()
    return dict(row) if row else None


def _get_subscription_tier(user_id: int, chat_id: int, chat_type: str) -> str:
    if user_id in ADMIN_IDS:
        return "admin"
    if chat_type == "private":
        if get_active_subscription(user_id, chat_id):
            return "paid"
        if is_trial_active(user_id):
            return "trial"
        return "expired"
    else:
        if get_group_subscription(chat_id):
            return "paid"
        return "none"


# ---------------------------------------------------------------------------
# Usage tracking
# ---------------------------------------------------------------------------

def _today() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")


def get_daily_usage(user_id: int, chat_id: int) -> int:
    row = get_conn().execute(
        "SELECT message_count FROM daily_usage WHERE user_id = ? AND chat_id = ? AND date = ?",
        (user_id, chat_id, _today()),
    ).fetchone()
    return row["message_count"] if row else 0


def increment_usage(user_id: int, chat_id: int) -> int:
    conn = get_conn()
    conn.execute(
        """INSERT INTO daily_usage (user_id, chat_id, date, message_count)
           VALUES (?, ?, ?, 1)
           ON CONFLICT(user_id, chat_id, date)
           DO UPDATE SET message_count = message_count + 1""",
        (user_id, chat_id, _today()),
    )
    conn.commit()
    return get_daily_usage(user_id, chat_id)


def _get_daily_limit(tier: str, chat_type: str) -> int:
    if tier == "admin":
        return -1
    if tier == "paid" and chat_type != "private":
        return -1  # unlimited for group subs
    if tier == "paid":
        return PAID_DAILY_LIMIT
    if tier == "trial":
        return FREE_DAILY_LIMIT
    return 0


# ---------------------------------------------------------------------------
# Message packs
# ---------------------------------------------------------------------------

def get_available_pack_messages(user_id: int) -> int:
    now = _now()
    row = get_conn().execute(
        """SELECT COALESCE(SUM(quantity - used), 0) AS remaining
           FROM message_packs
           WHERE user_id = ? AND expires_at > ? AND used < quantity""",
        (user_id, now),
    ).fetchone()
    return row["remaining"]


def consume_pack_message(user_id: int) -> bool:
    conn = get_conn()
    now = _now()
    row = conn.execute(
        """SELECT id FROM message_packs
           WHERE user_id = ? AND expires_at > ? AND used < quantity
           ORDER BY purchased_at ASC LIMIT 1""",
        (user_id, now),
    ).fetchone()
    if not row:
        return False
    conn.execute(
        "UPDATE message_packs SET used = used + 1 WHERE id = ?",
        (row["id"],),
    )
    conn.commit()
    return True


# ---------------------------------------------------------------------------
# The central gate
# ---------------------------------------------------------------------------

def check_message_allowed(user_id: int, chat_id: int, chat_type: str) -> tuple:
    ensure_user(user_id)
    tier = _get_subscription_tier(user_id, chat_id, chat_type)

    if tier == "admin":
        increment_usage(user_id, chat_id)
        return (True, "")

    if tier == "none":
        return (False, "")

    limit = _get_daily_limit(tier, chat_type)

    if limit == -1:
        increment_usage(user_id, chat_id)
        return (True, "")

    if limit == 0:
        return (False, _upgrade_message_expired())

    usage = get_daily_usage(user_id, chat_id)
    if usage < limit:
        increment_usage(user_id, chat_id)
        return (True, "")

    # Over daily limit
    if tier == "paid" and chat_type == "private":
        if consume_pack_message(user_id):
            increment_usage(user_id, chat_id)
            return (True, "")
        pack_remaining = get_available_pack_messages(user_id)
        return (False, _upgrade_message_paid_limit(usage, limit, pack_remaining))

    if tier == "trial":
        user = get_user(user_id)
        trial_days_left = 0
        if user:
            exp = datetime.fromisoformat(user["trial_expires"])
            trial_days_left = max(0, (exp - datetime.now(tz=timezone.utc)).days)
        return (False, _upgrade_message_trial(usage, limit, trial_days_left))

    return (False, _upgrade_message_expired())


def get_remaining_messages(user_id: int, chat_id: int, chat_type: str) -> int:
    tier = _get_subscription_tier(user_id, chat_id, chat_type)
    limit = _get_daily_limit(tier, chat_type)
    if limit == -1:
        return -1
    usage = get_daily_usage(user_id, chat_id)
    remaining = max(0, limit - usage)
    if tier == "paid" and chat_type == "private":
        remaining += get_available_pack_messages(user_id)
    return remaining


# ---------------------------------------------------------------------------
# Subscription management
# ---------------------------------------------------------------------------

def create_subscription(
    user_id: int, chat_id: int, chat_type: str,
    plan: str, period: str,
    payment_method: str,
    tg_charge_id: str, provider_charge_id: str,
) -> dict:
    conn = get_conn()
    now_dt = datetime.now(tz=timezone.utc)
    now = now_dt.isoformat()
    days = PERIOD_DAYS.get(period, 30)

    # Extend existing sub if active
    existing = (get_active_subscription(user_id, chat_id)
                if chat_type == "private"
                else get_group_subscription(chat_id))
    if existing:
        starts_at = existing["expires_at"]
        start_dt = datetime.fromisoformat(starts_at)
    else:
        starts_at = now
        start_dt = now_dt

    expires_at = (start_dt + timedelta(days=days)).isoformat()
    daily_limit = PAID_DAILY_LIMIT if plan == "personal" else -1

    conn.execute(
        """INSERT INTO subscriptions
           (user_id, chat_id, chat_type, plan, period, status,
            starts_at, expires_at, daily_limit, created_at,
            payment_method, telegram_payment_charge_id, provider_payment_charge_id)
           VALUES (?, ?, ?, ?, ?, 'active', ?, ?, ?, ?, ?, ?, ?)""",
        (user_id, chat_id, chat_type, plan, period,
         starts_at, expires_at, daily_limit, now,
         payment_method, tg_charge_id, provider_charge_id),
    )
    conn.commit()
    return {
        "user_id": user_id, "chat_id": chat_id, "plan": plan, "period": period,
        "starts_at": starts_at, "expires_at": expires_at,
    }


def create_message_pack(user_id: int, tg_charge_id: str, provider_charge_id: str) -> dict:
    conn = get_conn()
    now = _now()
    expires_at = (datetime.now(tz=timezone.utc) + timedelta(days=30)).isoformat()
    conn.execute(
        """INSERT INTO message_packs
           (user_id, quantity, used, purchased_at, expires_at,
            telegram_payment_charge_id, provider_payment_charge_id)
           VALUES (?, ?, 0, ?, ?, ?, ?)""",
        (user_id, MESSAGE_PACK_SIZE, now, expires_at, tg_charge_id, provider_charge_id),
    )
    conn.commit()
    return {"user_id": user_id, "quantity": MESSAGE_PACK_SIZE, "expires_at": expires_at}


def record_payment(
    user_id: int, chat_id: int, payment_type: str,
    amount: int, currency: str, payload: str,
    tg_charge_id: str, provider_charge_id: str,
):
    conn = get_conn()
    conn.execute(
        """INSERT INTO payments
           (user_id, chat_id, payment_type, amount, currency, payload,
            telegram_payment_charge_id, provider_payment_charge_id, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (user_id, chat_id, payment_type, amount, currency, payload,
         tg_charge_id, provider_charge_id, _now()),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Payload encoding / decoding
# ---------------------------------------------------------------------------

def encode_payload(action: str, plan: str = "", period: str = "",
                   chat_id: int = 0, user_id: int = 0) -> str:
    return f"{action}|{plan}|{period}|{chat_id}|{user_id}"


def decode_payload(payload: str) -> dict:
    parts = payload.split("|")
    return {
        "action": parts[0] if len(parts) > 0 else "",
        "plan": parts[1] if len(parts) > 1 else "",
        "period": parts[2] if len(parts) > 2 else "",
        "chat_id": int(parts[3]) if len(parts) > 3 and parts[3] else 0,
        "user_id": int(parts[4]) if len(parts) > 4 and parts[4] else 0,
    }


# ---------------------------------------------------------------------------
# Price helpers
# ---------------------------------------------------------------------------

_STAR_PRICES = {
    ("personal", "1w"): PRICE_PERSONAL_1W_STARS,
    ("personal", "1m"): PRICE_PERSONAL_1M_STARS,
    ("personal", "3m"): PRICE_PERSONAL_3M_STARS,
    ("personal", "6m"): PRICE_PERSONAL_6M_STARS,
    ("group", "1w"): PRICE_GROUP_1W_STARS,
    ("group", "1m"): PRICE_GROUP_1M_STARS,
    ("group", "3m"): PRICE_GROUP_3M_STARS,
    ("group", "6m"): PRICE_GROUP_6M_STARS,
}

_USD_PRICES = {
    ("personal", "1w"): PRICE_PERSONAL_1W_USD,
    ("personal", "1m"): PRICE_PERSONAL_1M_USD,
    ("personal", "3m"): PRICE_PERSONAL_3M_USD,
    ("personal", "6m"): PRICE_PERSONAL_6M_USD,
    ("group", "1w"): PRICE_GROUP_1W_USD,
    ("group", "1m"): PRICE_GROUP_1M_USD,
    ("group", "3m"): PRICE_GROUP_3M_USD,
    ("group", "6m"): PRICE_GROUP_6M_USD,
}


def get_prices(plan: str, period: str) -> dict:
    stars = _STAR_PRICES.get((plan, period), 0)
    usd = _USD_PRICES.get((plan, period), 0)
    label = f"{plan.title()} — {PERIOD_LABELS.get(period, period)}"
    return {"stars": stars, "usd_cents": usd, "label": label}


def get_pack_prices() -> dict:
    return {
        "stars": PRICE_PACK_STARS,
        "usd_cents": PRICE_PACK_USD,
        "label": f"{MESSAGE_PACK_SIZE} extra messages",
    }


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------

def _upgrade_message_trial(usage: int, limit: int, trial_days_left: int) -> str:
    return (
        f"You've used all {limit} free messages for today.\n\n"
        f"Your free trial is active for {trial_days_left} more day(s). "
        f"Upgrade to get {PAID_DAILY_LIMIT} messages/day:\n\n"
        f"/subscribe — View plans\n\n"
        f"Your messages will reset tomorrow at midnight UTC."
    )


def _upgrade_message_paid_limit(usage: int, limit: int, pack_remaining: int) -> str:
    return (
        f"You've reached your daily limit of {limit} messages.\n\n"
        f"Need more? Buy a pack of {MESSAGE_PACK_SIZE} extra messages:\n"
        f"/buy_messages\n\n"
        f"Your daily limit resets tomorrow at midnight UTC."
    )


def _upgrade_message_expired() -> str:
    return (
        "Your free trial has ended.\n\n"
        "Subscribe to keep chatting:\n"
        "/subscribe — View plans\n\n"
        f"Personal: {PAID_DAILY_LIMIT} messages/day\n"
        "Groups: Unlimited messages"
    )


def get_status_text(user_id: int, chat_id: int, chat_type: str) -> str:
    ensure_user(user_id)
    tier = _get_subscription_tier(user_id, chat_id, chat_type)
    lines = []

    if tier == "admin":
        lines.append("Status: Admin (unlimited)")
    elif tier == "paid":
        if chat_type == "private":
            sub = get_active_subscription(user_id, chat_id)
        else:
            sub = get_group_subscription(chat_id)
        if sub:
            exp = sub["expires_at"][:10]
            lines.append(f"Plan: {sub['plan'].title()} ({sub['period']})")
            lines.append(f"Expires: {exp}")
    elif tier == "trial":
        user = get_user(user_id)
        if user:
            exp = datetime.fromisoformat(user["trial_expires"])
            days_left = max(0, (exp - datetime.now(tz=timezone.utc)).days)
            lines.append(f"Status: Free trial ({days_left} day(s) left)")
    else:
        lines.append("Status: No active subscription")

    if tier != "admin":
        limit = _get_daily_limit(tier, chat_type)
        usage = get_daily_usage(user_id, chat_id)
        if limit == -1:
            lines.append("Messages: Unlimited")
        elif limit > 0:
            lines.append(f"Messages today: {usage}/{limit}")
            if tier == "paid" and chat_type == "private":
                pack_msgs = get_available_pack_messages(user_id)
                if pack_msgs > 0:
                    lines.append(f"Pack messages: {pack_msgs}")
        else:
            lines.append("Messages: 0 (subscribe to continue)")

    if tier not in ("admin", "paid"):
        lines.append("\n/subscribe — View plans")

    return "\n".join(lines)
