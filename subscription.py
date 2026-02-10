import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

from config import ADMIN_IDS, FREE_DAILY_MESSAGES, PLAN_DURATIONS
from storage import get_conn

logger = logging.getLogger(__name__)

PLAN_LABELS = {
    'monthly': '1 Month',
    '3months': '3 Months',
    '6months': '6 Months',
    'yearly': '1 Year',
    'lifetime': 'Lifetime',
}


def _now() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _today() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# Active subscription (with lazy expiry)
# ---------------------------------------------------------------------------

def get_active_subscription(user_id: int) -> Optional[dict]:
    conn = get_conn()
    row = conn.execute(
        """SELECT * FROM subscriptions
           WHERE user_id = ? AND status = 'active'
           ORDER BY id DESC LIMIT 1""",
        (user_id,),
    ).fetchone()
    if not row:
        return None
    sub = dict(row)
    # Lazy-expire if past expires_at (lifetime subs have NULL expires_at)
    if sub["expires_at"] is not None:
        if datetime.fromisoformat(sub["expires_at"]) < datetime.now(tz=timezone.utc):
            conn.execute(
                "UPDATE subscriptions SET status = 'expired' WHERE id = ?",
                (sub["id"],),
            )
            conn.commit()
            return None
    return sub


def create_subscription(user_id: int, plan: str, payment_method: str) -> dict:
    conn = get_conn()
    now = _now()
    # Expire any existing active subscription
    conn.execute(
        "UPDATE subscriptions SET status = 'expired' WHERE user_id = ? AND status = 'active'",
        (user_id,),
    )
    days = PLAN_DURATIONS.get(plan)
    expires_at = None
    if days is not None:
        expires_at = (datetime.now(tz=timezone.utc) + timedelta(days=days)).isoformat()
    conn.execute(
        """INSERT INTO subscriptions
           (user_id, plan, status, payment_method, started_at, expires_at, created_at)
           VALUES (?, ?, 'active', ?, ?, ?, ?)""",
        (user_id, plan, payment_method, now, expires_at, now),
    )
    conn.commit()
    return {
        "user_id": user_id, "plan": plan, "payment_method": payment_method,
        "started_at": now, "expires_at": expires_at,
    }


def is_subscriber(user_id: int) -> bool:
    return get_active_subscription(user_id) is not None


# ---------------------------------------------------------------------------
# Payment audit trail
# ---------------------------------------------------------------------------

def record_payment(
    user_id: int, amount: str, currency: str,
    payment_method: str, plan: str,
    payment_id: str = "", status: str = "completed",
):
    conn = get_conn()
    conn.execute(
        """INSERT INTO payments
           (user_id, amount, currency, payment_method, payment_id, plan, status, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (user_id, str(amount), currency, payment_method, payment_id, plan, status, _now()),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Daily usage tracking (free tier)
# ---------------------------------------------------------------------------

def get_daily_usage(user_id: int) -> int:
    row = get_conn().execute(
        "SELECT message_count FROM daily_usage WHERE user_id = ? AND date = ?",
        (user_id, _today()),
    ).fetchone()
    return row["message_count"] if row else 0


def increment_daily_usage(user_id: int) -> int:
    conn = get_conn()
    conn.execute(
        """INSERT INTO daily_usage (user_id, date, message_count)
           VALUES (?, ?, 1)
           ON CONFLICT(user_id, date)
           DO UPDATE SET message_count = message_count + 1""",
        (user_id, _today()),
    )
    conn.commit()
    return get_daily_usage(user_id)


# ---------------------------------------------------------------------------
# Central gate
# ---------------------------------------------------------------------------

def can_use_bot(user_id: int) -> Tuple[bool, str]:
    """Returns (allowed, reason).
    reason is 'admin', 'subscriber', 'free', or 'blocked'.
    """
    if user_id in ADMIN_IDS:
        return True, "admin"
    if is_subscriber(user_id):
        return True, "subscriber"
    usage = get_daily_usage(user_id)
    if usage < FREE_DAILY_MESSAGES:
        return True, "free"
    return False, "blocked"


# ---------------------------------------------------------------------------
# Status display
# ---------------------------------------------------------------------------

def get_subscription_status_text(user_id: int) -> str:
    if user_id in ADMIN_IDS:
        return "Status: Admin (unlimited)"

    sub = get_active_subscription(user_id)
    if sub:
        plan_label = PLAN_LABELS.get(sub["plan"], sub["plan"])
        lines = [f"Plan: {plan_label}"]
        if sub["expires_at"]:
            exp = sub["expires_at"][:10]
            lines.append(f"Expires: {exp}")
        else:
            lines.append("Expires: Never (Lifetime)")
        lines.append(f"Payment: {sub['payment_method']}")
        return "\n".join(lines)

    usage = get_daily_usage(user_id)
    remaining = max(0, FREE_DAILY_MESSAGES - usage)
    return (
        "Status: Free tier\n"
        f"Messages today: {usage}/{FREE_DAILY_MESSAGES}\n"
        f"Remaining: {remaining}\n\n"
        "Use /subscribe to upgrade."
    )
