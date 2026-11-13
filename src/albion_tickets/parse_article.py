"""A ticket article → the matches it describes."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from urllib.parse import urlsplit

from .dates import at_london, parse_day_date, parse_time
from .model import Match
from .parse_stages import parse_stages, parse_status
from .payload import article_var, field_after, object_at, rich_text

_MONTH_START = re.compile(r"^(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\b", re.I)
_DAY_NUM_END = re.compile(r"\b(mon|tue|wed|thu|fri|sat|sun)[a-z]*\s+\d{1,2}(st|nd|rd|th)?$", re.I)
_KICKOFF_LINE = re.compile(r"kick[- ]?off", re.I)
_POINTS = re.compile(r"points allocated for this fixture\s*:?\s*(\d+)", re.I)
_UNCONFIRMED = re.compile(r"not yet confirmed|\bTBC\b|to be confirmed", re.I)
_ALBION = r"(?:Brighton\s*(?:&|and)\s*Hove\s+Albion|Albion)"


@dataclass(frozen=True)
class Article:
    url: str
    title: str
    published: date | None
    matches: list[Match]
    ignorable: bool
    text: str = ""


def article_text(html: str, slug: str) -> str | None:
    found = article_var(html, slug)
    if not found:
        return None
    var, pos = found
    m = re.compile(re.escape(var) + r"\.articleBody=").search(html, pos, pos + 200_000)
    if not m:
        return None
    obj = object_at(html, m.end())
    return rich_text(obj) if obj else None


def _join_split_dates(lines: list[str]) -> list[str]:
    out: list[str] = []
    for line in lines:
        if out and _DAY_NUM_END.search(out[-1]) and _MONTH_START.match(line):
            out[-1] = f"{out[-1]} {line}"
        else:
            out.append(line)
    return out


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def _season(d: date) -> str:
    start = d.year if d.month >= 8 else d.year - 1
    return f"{start}-{(start + 1) % 100:02d}"


def _competition(text: str) -> str:
    low = text.lower()
    if "conference league" in low:
        return "UEFA Conference League"
    if "europa league" in low:
        return "UEFA Europa League"
    if "champions league" in low:
        return "UEFA Champions League"
    if "fa cup" in low or "emirates fa cup" in low:
        return "FA Cup"
    if "carabao cup" in low or "league cup" in low:
        return "League Cup"
    return "Premier League"


def _heading(line: str, segment: str) -> tuple[str, bool] | None:
    """(opponent, home) from a match heading line, or None."""
    if ":" in line or len(line) > 60:
        return None
    line = line.strip().rstrip(".")
    m = re.match(rf"^{_ALBION}\s+v\s+(.+)$", line, re.I)
    if m:
        return m.group(1).strip(), True
    m = re.match(rf"^(.+?)\s+v\s+{_ALBION}$", line, re.I)
    if m:
        return m.group(1).strip(), False
    m = re.match(r"^(.+?)\s*\((away|home)\)$", line, re.I)
    if m:
        return m.group(1).strip(), m.group(2).lower() == "home"
    if re.search(r"visiting supporters|\baway\b", segment, re.I):
        return line, False
    if re.search(r"\bat the Amex\b|American Express Stadium", segment, re.I):
        return line, True
    return None


def parse_text(text: str, url: str, title: str, published: date | None) -> Article:
    lines = _join_split_dates(text.splitlines())
    starts: list[int] = []
    for i, line in enumerate(lines):
        if i > 0 and _KICKOFF_LINE.search(line) and parse_day_date(line, None, published) is not None:
            starts.append(i - 1)
    matches: list[Match] = []
    for n, start in enumerate(starts):
        end = starts[n + 1] if n + 1 < len(starts) else len(lines)
        segment = "\n".join(lines[start:end])
        head = _heading(lines[start], segment)
        if head is None:
            continue
        opponent, home = head
        when = lines[start + 1]
        d = parse_day_date(when, None, published)
        kickoff = at_london(d, parse_time(when.split("kick", 1)[-1])[0]) if d else None
        competition = _competition(segment if home else segment + "\n" + title)
        stages, unreadable = parse_stages(segment, d, published)
        pts = _POINTS.search(segment)
        matches.append(Match(
            key=f"{_season(d or published or date.today())}-{_slug(opponent)}-{'h' if home else 'a'}-{_slug(competition)}",
            opponent=opponent,
            home=home,
            competition=competition,
            kickoff=kickoff,
            kickoff_confirmed=not _UNCONFIRMED.search(segment),
            stages=stages,
            status=parse_status(segment, d, published),
            fixture_points=int(pts.group(1)) if pts else None,
            url=url,
            unreadable=unreadable,
        ))
    ignorable = not matches and bool(
        re.search(r"\bat the Amex\b", text, re.I)
        and re.search(r"premier league", text, re.I)
        and not re.search(r"\baway\b|visiting supporters", text, re.I)
    )
    return Article(url, title, published, matches, ignorable, text)


def parse_article(html: str, url: str, today: date) -> Article | None:
    slug = urlsplit(url).path.rstrip("/").rsplit("/", 1)[-1]
    text = article_text(html, slug)
    if text is None:
        return None
    found = article_var(html, slug)
    published_raw = field_after(html, found[0], "publishDateTime", found[1]) if found else None
    published = date.fromisoformat(published_raw[:10]) if published_raw else today
    title = (field_after(html, found[0], "name", max(0, found[1] - 2000)) if found else None) or slug
    return parse_text(text, url, title, published)


def is_tracked(m: Match) -> bool:
    return (not m.home) or m.competition != "Premier League"
