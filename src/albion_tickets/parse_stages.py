"""Sale-stage lines and sell-out wording, as the club writes them."""
import re
from datetime import date

from .dates import at_london, parse_day_date, parse_time
from .model import Audience, Stage, Status

_AUDIENCE_WORDS = re.compile(
    r"STH|Season Ticket|1901|MyAlbion|General Sale|Purchase History|Members?\b|Guests?",
    re.IGNORECASE,
)
_DAY_WORD = re.compile(r"\b(mon|tue|wed|thu|fri|sat|sun)[a-z]*\b", re.IGNORECASE)
_POINTS = re.compile(r"(\d+)\s*\+\s*(?:pts|points)?", re.IGNORECASE)


# Stage label wording → who the stage is for, first match wins ("STHs' guests" are guests).
_AUDIENCES: list[tuple[re.Pattern, Audience]] = [
    (re.compile(r"guest", re.I), "guests"), (re.compile(r"\bsths?\b|season ticket|1901", re.I), "sth"),
    (re.compile(r"myalbion", re.I), "myalbion"), (re.compile(r"general sale", re.I), "general")]


def _audience(label: str) -> Audience:
    return next((who for words, who in _AUDIENCES if words.search(label)), "other")


def _split(line: str) -> tuple[str, str] | None:
    """Split a candidate stage line into (who, when), or None if it isn't one."""
    day = _DAY_WORD.search(line)
    if not day:
        return None
    if ":" in line[: day.start()]:
        who, when = line.split(":", 1)
    else:  # "Purchase History Thu 05 Nov 9am"
        who, when = line[: day.start()], line[day.start():]
    who = who.strip()
    if not who or not _AUDIENCE_WORDS.search(who) or len(who) > 80:
        return None
    return who, when


def parse_stages(text: str, match_day: date | None, published: date | None) -> tuple[list[Stage], list[str]]:
    stages: list[Stage] = []
    unreadable: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        parts = _split(line)
        if parts is None:
            continue
        who, when = parts
        d = parse_day_date(when, before=match_day, after=published)
        if d is None:
            unreadable.append(line)
            continue
        t, assumed = parse_time(when)
        pts = _POINTS.search(who)
        stages.append(Stage(
            label=who.rstrip(" *").strip(),
            audience=_audience(who),
            min_points=int(pts.group(1)) if pts else None,
            brackets_pending=who.rstrip().endswith("*"),
            opens=at_london(d, t),
            time_assumed=assumed,
        ))
    return stages, unreadable


_SOLD_STRONG = re.compile(
    r"sold out to|\bnow sold out|\b(has|have) (now )?(been )?sold out|^sold out\b|\bsold out\s*[-–—!.]?\s*$",
    re.IGNORECASE,
)
_CONDITIONAL = re.compile(r"\b(if|when|should|may|might|once|whether)\b", re.IGNORECASE)


def _sold_out_seen(text: str) -> bool:
    """A line that *states* a sell-out — not boilerplate that merely mentions one."""
    for raw in text.splitlines():
        line = raw.strip()
        if "sold out" not in line.lower():
            continue
        if _SOLD_STRONG.search(line):
            return True
        if len(line) <= 80 and not _CONDITIONAL.search(line):
            return True
    return False


_SOLD_OUT_TO = re.compile(r"sold out to\s+(.+?)\s*(?::|\.|$)", re.IGNORECASE | re.MULTILINE)
_EXCHANGE = re.compile(r"resale[^\n]*?close[sd]?\s+on\s+([^\n]+)", re.IGNORECASE)


def parse_status(text: str, match_day: date | None, published: date | None) -> Status:
    sold_to = _SOLD_OUT_TO.search(text)
    label = sold_to.group(1).strip() if sold_to else None
    pts = _POINTS.search(label) if label else None
    closes = None
    ex = _EXCHANGE.search(text)
    if ex:
        d = parse_day_date(ex.group(1), before=match_day, after=published)
        if d is not None:
            closes = at_london(d, parse_time(ex.group(1))[0])
    return Status(
        sold_out_to=label,
        sold_out_min_points=int(pts.group(1)) if pts else None,
        sold_out_label_seen=_sold_out_seen(text),
        wheelchair_only=bool(re.search(r"wheelchair\s+only", text, re.IGNORECASE)),
        exchange_closes=closes,
    )
