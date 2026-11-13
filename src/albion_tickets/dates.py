"""Dates and times as the club writes them: no years, loose abbreviations."""
from __future__ import annotations

import re
from datetime import date, datetime, time

from . import config

_DAYS = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}
_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}

_DATE_RE = re.compile(
    r"\b(mon|tue|wed|thu|fri|sat|sun)[a-z]*\.?,?\s+(\d{1,2})(?:st|nd|rd|th)?\s+"
    r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\b",
    re.IGNORECASE,
)
_TIME_RE = re.compile(r"\b(\d{1,2})(?:[:.](\d{2}))?\s*(am|pm)\b", re.IGNORECASE)


def parse_day_date(text: str, before: date | None, after: date | None) -> date | None:
    """'Tue 27 Oct' → a date. The year is inferred: the latest on or before
    `before` (the match day), or else the earliest on or after `after`.
    Returns None if there is no date, or if the weekday contradicts it."""
    m = _DATE_RE.search(text)
    if not m:
        return None
    weekday = _DAYS[m.group(1)[:3].lower()]
    day, month = int(m.group(2)), _MONTHS[m.group(3)[:3].lower()]
    ref = before or after or datetime.now(config.TZ).date()
    candidates = []
    for year in (ref.year - 1, ref.year, ref.year + 1):
        try:
            candidates.append(date(year, month, day))
        except ValueError:
            continue
    if before is not None:
        pool = [d for d in candidates if d <= before]
        chosen = max(pool) if pool else None
    else:
        pool = [d for d in candidates if d >= ref]
        chosen = min(pool) if pool else None
    if chosen is None or chosen.weekday() != weekday:
        return None
    return chosen


def parse_time(text: str) -> tuple[time, bool]:
    """'9am', '7.30pm', '2:05 PM' → (time, assumed). No time → (09:00, True)."""
    m = _TIME_RE.search(text)
    if not m:
        return time(9, 0), True
    hour, minute = int(m.group(1)), int(m.group(2) or 0)
    if m.group(3).lower() == "pm" and hour != 12:
        hour += 12
    if m.group(3).lower() == "am" and hour == 12:
        hour = 0
    return time(hour, minute), False


def at_london(d: date, t: time) -> datetime:
    return datetime.combine(d, t, tzinfo=config.TZ)
