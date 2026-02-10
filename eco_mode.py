"""
ECO Mode — Adaptive resource management for background agents.

Tracks bot traffic and dynamically adjusts agent scheduling:
- Low traffic  (<5 msgs/h):  conservation mode — agents sleep long
- Medium traffic (5-20 msgs/h): balanced mode
- High traffic  (20+ msgs/h): full power — agents at max frequency

This ensures minimal Claude API spend when the bot is idle,
and full intelligence when users are active.
"""

import time
import logging
from collections import deque

logger = logging.getLogger(__name__)

# Rolling window of message timestamps (last 2 hours)
_message_times: deque = deque(maxlen=2000)


def record_message():
    """Record a user message. Call on every Claude API interaction."""
    _message_times.append(time.time())


def get_hourly_rate() -> float:
    """Messages received in the last hour."""
    cutoff = time.time() - 3600
    return sum(1 for t in _message_times if t > cutoff)


def get_traffic_level() -> str:
    """Current traffic level: 'low', 'medium', or 'high'."""
    rate = get_hourly_rate()
    if rate < 5:
        return "low"
    elif rate < 20:
        return "medium"
    return "high"


# Agent interval configs (seconds)
_INTERVALS = {
    "low": {
        "research": 43200,       # 12h (1-2x/day)
        "intelligence": 86400,   # 24h (1x/day)
        "resilience": 1800,      # 30 min
        "moltbook_base": 3600,   # 1h
    },
    "medium": {
        "research": 14400,       # 4h
        "intelligence": 28800,   # 8h
        "resilience": 900,       # 15 min
        "moltbook_base": 1800,   # 30 min
    },
    "high": {
        "research": 3600,        # 1h
        "intelligence": 7200,    # 2h
        "resilience": 300,       # 5 min
        "moltbook_base": 900,    # 15 min (original)
    },
}


def get_interval(agent_name: str) -> int:
    """Get the recommended sleep interval for an agent based on current traffic."""
    level = get_traffic_level()
    interval = _INTERVALS[level].get(agent_name, 3600)
    return interval


def get_eco_status() -> dict:
    """Return full ECO status for monitoring/logging."""
    rate = get_hourly_rate()
    level = get_traffic_level()
    intervals = _INTERVALS[level]
    return {
        "traffic_level": level,
        "messages_per_hour": rate,
        "intervals": {k: f"{v // 3600}h {(v % 3600) // 60}m" for k, v in intervals.items()},
    }
