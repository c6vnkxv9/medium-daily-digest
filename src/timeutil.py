"""Asia/Taipei calendar helpers and recent-window checks."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from zoneinfo import ZoneInfo

TAIPEI = ZoneInfo("Asia/Taipei")
DEFAULT_LOOKBACK_HOURS = 24


def taipei_today(now: datetime | None = None) -> date:
    """Return today's calendar date in Asia/Taipei."""
    if now is None:
        now = datetime.now(tz=TAIPEI)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc).astimezone(TAIPEI)
    else:
        now = now.astimezone(TAIPEI)
    return now.date()


def parse_pub_date(value: str) -> datetime | None:
    """Parse RSS pubDate (RFC 2822) or ISO-8601 into an aware datetime."""
    if not value or not value.strip():
        return None
    raw = value.strip()
    try:
        dt = parsedate_to_datetime(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (TypeError, ValueError, IndexError):
        pass
    try:
        # Support trailing Z
        iso = raw.replace("Z", "+00:00")
        dt = datetime.fromisoformat(iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


def to_taipei_iso(dt: datetime) -> str:
    """Format datetime as ISO8601 in Asia/Taipei."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(TAIPEI).isoformat()


def is_taipei_today(dt: datetime, today: date | None = None) -> bool:
    """True if dt falls on the given (or current) Taipei calendar date."""
    if today is None:
        today = taipei_today()
    return dt.astimezone(TAIPEI).date() == today


def is_within_last_hours(
    dt: datetime,
    *,
    hours: float = DEFAULT_LOOKBACK_HOURS,
    now: datetime | None = None,
) -> bool:
    """True if dt is at or after (now - hours)."""
    if now is None:
        now = datetime.now(tz=timezone.utc)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    cutoff = now - timedelta(hours=hours)
    return dt.astimezone(timezone.utc) >= cutoff.astimezone(timezone.utc)
