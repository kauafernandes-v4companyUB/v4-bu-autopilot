"""Execution timestamps (CLAUDE.md section 26): always the real system
clock, UTC RFC3339, plus the mandatory not-in-the-future sanity check."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

FUTURE_TOLERANCE = timedelta(minutes=5)


def utc_now_rfc3339() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def future_timestamp_problem(ts: str, *, now: Optional[datetime] = None) -> Optional[str]:
    """None when `ts` is a valid RFC3339 UTC timestamp not significantly
    in the future relative to the real clock; otherwise a message."""
    try:
        parsed = datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return f"execution timestamp {ts!r} is not UTC RFC3339 (YYYY-MM-DDTHH:MM:SSZ)"
    now = now or datetime.now(timezone.utc)
    if parsed - now > FUTURE_TOLERANCE:
        return f"execution timestamp {ts} is in the future relative to the real clock ({now.strftime('%Y-%m-%dT%H:%M:%SZ')})"
    return None
