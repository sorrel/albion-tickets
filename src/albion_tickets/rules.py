"""Which stage is the user's, and what a sell-out means for them.

Status labels ("BUY", "Sold Out") are never trusted on their own: a sell-out
counts only once the match's first published stage has opened.
"""
import re
from itertools import pairwise
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import Literal

from .dates import at_london
from .model import Match, Stage

PATTERN_NOTE = "Not the usual Tuesday–Friday pattern"
type Kind = Literal["sale", "predicted_sale", "sold_out_before_you", "exchange_open", "unreadable"]


@dataclass(frozen=True)
class Outcome:
    kind: Kind
    stage: Stage | None
    opens: datetime | None
    sold_out_stage: str | None = None
    pattern_note: str | None = None
    urgent: bool = False  # for "unreadable": a stage line the user may need couldn't be read


def _users_stage(stages: list[Stage], points: int) -> Stage | None:
    for s in stages:
        if s.audience == "sth" and (s.min_points is None or points >= s.min_points):
            return s
    return None


def _pattern_note(stages: list[Stage]) -> str | None:
    sth = [s for s in stages if s.audience == "sth" and not s.brackets_pending]
    bracketed = [s for s in sth if s.min_points is not None]
    if not bracketed:
        return None
    run = bracketed + [s for s in sth if s.min_points is None][:1]
    expected = [1, 2, 3, 4]  # Tue … Fri
    days = [s.opens.date() for s in run]
    consecutive = all((b - a).days == 1 for a, b in pairwise(days))
    if [d.weekday() for d in days] != expected or not consecutive:
        return PATTERN_NOTE
    return None


def _sold_out_stage(m: Match, seen: datetime) -> Stage | None:
    """The stage the match sold out at, or None if it can't be told."""
    st = m.status
    if st.sold_out_min_points is not None:
        for s in m.stages:
            if s.min_points == st.sold_out_min_points:
                return s
        return Stage(st.sold_out_to or "", "sth", st.sold_out_min_points, False, seen, False)
    if st.sold_out_to:
        low = st.sold_out_to.lower()
        for s in m.stages:
            if s.label.lower() == low:
                return s
        if re.search(r"\ball\b", low):
            aud = "myalbion" if "myalbion" in low else "sth"
            return Stage(st.sold_out_to, aud, None, False, seen, False)
    opened = [s for s in m.stages if s.opens <= seen]
    return opened[-1] if opened else None


def sold_out_text(label: str | None) -> str:
    """'STHs/1901 Club Members w/ 239+ Points' → 'sold out at 239+ points (STHs/1901)'.

    The level is the last group the sale reached: the club lists everyone it
    was offered to, so the widest group named is where it ran out.
    """
    if not label:
        return "sold out"
    low = label.lower()
    pts = re.search(r"(\d+)\s*\+", label)
    if pts:
        return f"sold out at {pts.group(1)}+ points (STHs/1901)"
    if "general sale" in low:
        return "sold out at general sale"
    if "purchase history" in low:
        return "sold out to supporters with purchase history"
    if "myalbion" in low:
        return "sold out to all MyAlbion+ members"
    if re.search(r"\bsths?\b|1901|season ticket", low):
        return "sold out to all STHs/1901 members"
    return f"sold out to {label}"


_STH_LINE = re.compile(r"\bSTHs?\b|season ticket|1901", re.IGNORECASE)


def decide(m: Match, points: int, now: datetime, first_sold_out_seen: datetime | None) -> Outcome:
    if any(_STH_LINE.search(line) for line in m.unreadable):
        return Outcome("unreadable", None, None, urgent=True)
    if not m.stages:
        return Outcome("unreadable", None, None)
    mine = _users_stage(m.stages, points)
    if mine is None:
        return Outcome("unreadable", None, None)
    note = _pattern_note(m.stages)

    st = m.status
    seen = first_sold_out_seen or now
    first_open = min(s.opens for s in m.stages)
    if st.sold and seen >= first_open:
        at_stage = _sold_out_stage(m, seen)
        if at_stage is None:
            return Outcome("unreadable", mine, mine.opens, None, note)
        label = st.sold_out_to or at_stage.label
        reached_you = at_stage.min_points is None or points >= at_stage.min_points
        if reached_you:
            return Outcome("exchange_open", mine, None, label, note)
        return Outcome("sold_out_before_you", mine, mine.opens, label, note)

    if mine.brackets_pending:
        tuesday = mine.opens
        if tuesday.weekday() == 1:
            friday = at_london(tuesday.date() + timedelta(days=3), time(9, 0))
            return Outcome("predicted_sale", mine, friday, None, note)
        return Outcome("predicted_sale", mine, mine.opens, None, PATTERN_NOTE)
    return Outcome("sale", mine, mine.opens, None, note)
