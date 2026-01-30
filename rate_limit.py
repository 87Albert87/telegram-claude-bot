import time
from config import RATE_LIMIT

# user_id -> list of timestamps
_requests: dict[int, list[float]] = {}


def is_rate_limited(user_id: int) -> bool:
    now = time.time()
    window_start = now - 60.0

    timestamps = _requests.get(user_id, [])
    # Remove old entries
    timestamps = [t for t in timestamps if t > window_start]
    _requests[user_id] = timestamps

    if len(timestamps) >= RATE_LIMIT:
        return True

    timestamps.append(now)
    return False
