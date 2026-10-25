"""Device sign-in rules that need no I/O: the polling schedule and how long a token is good for."""

from __future__ import annotations

SLOW_DOWN_STEP_SECONDS = 5
DEFAULT_INTERVAL_SECONDS = 5
TOKEN_MARGIN_SECONDS = 60


def next_interval(interval: int, *, slow_down: bool) -> int:
    """The polling interval after an answer: ``slow_down`` adds 5 seconds and the new value is kept."""
    return interval + SLOW_DOWN_STEP_SECONDS if slow_down else interval


def token_usable(expires_at: float, now: float) -> bool:
    """True when a token is valid for at least another minute."""
    return expires_at - now >= TOKEN_MARGIN_SECONDS


def minutes_left(expires_at: float, now: float) -> int:
    return max(1, round((expires_at - now) / 60))
