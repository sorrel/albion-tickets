"""A ticket article → the matches it describes."""
import re
from dataclasses import dataclass
from datetime import date

from .dates import at_london, parse_day_date, parse_time
from .model import Match, match_key, url_slug
from .parse_stages import parse_stages, parse_status
from .payload import article_var, field_after, object_at, rich_text

_MONTH_START = re.compile(r"^(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\b", re.I)
_DAY_NUM_END = re.compile(r"\b(mon|tue|wed|thu|fri|sat|sun)[a-z]*\s+\d{1,2}(st|nd|rd|th)?$", re.I)
_KICKOFF_LINE = re.compile(r"kick[- ]?off", re.I)
_POINTS = re.compile(r"points allocated for this fixture\s*:?\s*(\d+)", re.I)
_UNCONFIRMED = re.compile(r"not yet confirmed|\bTBC\b|to be confirmed", re.I)
_SUFFIX = re.compile(
    r"\s*(?:[-–—|]\s*(?:sold out|updated?|tbc|postponed|rearranged|new (?:date|time))\b.*"
    r"|\((?:sold out|updated?|tbc)\))\s*$",
    re.IGNORECASE,
)
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


# Wording → competition, first match wins; anything else is the league.
_COMPETITIONS = [("conference league", "UEFA Conference League"), ("europa league", "UEFA Europa League"),
                 ("champions league", "UEFA Champions League"), ("fa cup", "FA Cup"),
                 ("carabao cup", "League Cup"), ("league cup", "League Cup")]


def competition(text: str) -> str:
    low = text.lower()
    return next((name for words, name in _COMPETITIONS if words in low), "Premier League")


def heading(line: str, segment: str) -> tuple[str, bool] | None:
    """(opponent, home) from a match heading line, or None."""
    line = _SUFFIX.sub("", line)
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


def _home_league_news(text: str) -> bool:
    return bool(re.search(r"\bat the Amex\b", text, re.I)
                and re.search(r"premier league", text, re.I)
                and not re.search(r"\baway\b|visiting supporters", text, re.I))


def _members_only_home_sale(text: str) -> bool:
    """The 'Match: X / Date: …' layout the club uses for home league games.

    Season-ticket holders already have their seat, so the only sales are to
    members and to STHs' guests. Any stage for STHs themselves (a cup tie, or
    an away sale) means it matters, so it is not ignored.
    """
    if not re.search(r"^\s*Match:\s*\S", text, re.M | re.I):
        return False
    if re.search(r"\baway\b|visiting supporters", text, re.I):
        return False
    sth_lines = [l for l in text.splitlines() if re.search(r"\bSTHs?\b|1901|season ticket", l, re.I)]
    return all(re.search(r"guest", l, re.I) for l in sth_lines)


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
        head = heading(lines[start], segment)
        if head is None:
            continue
        opponent, home = head
        when = lines[start + 1]
        d = parse_day_date(when, None, published)
        kickoff = at_london(d, parse_time(when.split("kick", 1)[-1])[0]) if d else None
        comp = competition(segment if home else segment + "\n" + title)
        stages, unreadable = parse_stages(segment, d, published)
        pts = _POINTS.search(segment)
        matches.append(Match(
            key=match_key(d or published or date.today(), opponent, home, comp),
            opponent=opponent,
            home=home,
            competition=comp,
            kickoff=kickoff,
            kickoff_confirmed=not _UNCONFIRMED.search(segment),
            stages=stages,
            status=parse_status(segment, d, published),
            fixture_points=int(pts.group(1)) if pts else None,
            url=url,
            unreadable=unreadable,
        ))
    ignorable = not matches and (_home_league_news(text) or _members_only_home_sale(text))
    return Article(url, title, published, matches, ignorable, text)


def parse_article(html: str, url: str, today: date) -> Article | None:
    slug = url_slug(url)
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
