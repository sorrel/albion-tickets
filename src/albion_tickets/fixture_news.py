"""Fixture News articles: moved kick-offs, postponements and cup draws.

The club writes these as prose, one sentence per match:

    Our first match back after the November international break at Hull City
    will now be played on Sunday 22 November, kick-off 2pm.

    Albion will face Manchester United away in the third round of the
    Emirates FA Cup. Cup ties are due to take place around the weekend of
    Saturday 10 January 2026. … Manchester United v Brighton & Hove Albion

This module only reads text. Which tracked match a sentence means is decided
in run.py, which knows what is tracked.
"""
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Literal

from .dates import _DATE_RE, at_london, parse_day_date, parse_time
from .parse_article import _competition, _heading
from .ticket_page import ALIASES, canonical

type Side = Literal["home", "away"]

_HOME = re.compile(r"\b(at home|home (?:game|match|tie|fixture|leg)|welcome|host(?:s|ing)?|"
                   r"(?:at|to) the Amex|American Express Stadium)\b", re.I)
_AWAY = re.compile(r"\b(away|trip to|travel(?:ling)? to|visit(?:ing)?|head(?:ing|ed)? to|"
                   r"at the home of)\b", re.I)
_POSTPONED = re.compile(r"\b(postponed|called off|to be rescheduled|new date to be confirmed)\b", re.I)
# Wording that introduces a match's new date, as opposed to naming its old one.
_NEW_DATE = re.compile(r"\b(will now|now (?:take|be) |rearranged for|moved to|put back to|brought forward to|"
                       r"new date (?:is|of)|instead)\b", re.I)
_DRAW = re.compile(r"\b(draw|drawn)\b", re.I)
_PROVISIONAL = re.compile(r"\b(around|weekend of|week commencing|w/c|provisional(?:ly)?)\b", re.I)
_LEG = re.compile(r"\b(first|second) leg\b", re.I)
_SENTENCE = re.compile(r"(?<=[.!?])\s+(?=[A-Z])")

# A short form that names two clubs is never used on its own.
_AMBIGUOUS = {"manchester", "sheffield", "bristol", "nottingham"}
_SUFFIXES = re.compile(r"\s+(City|United|Town|FC|AFC|Hotspur|Wanderers|Rovers|Athletic|Albion)$", re.I)
_EXTRA = {"Nottingham Forest": ["Forest"], "Tottenham Hotspur": ["Spurs"]}


@dataclass(frozen=True)
class Move:
    """A sentence about a known club: a new kick-off, or a postponement.

    For a move, `when` is the new kick-off. For a postponement it is the date
    the sentence names, if any: the old one, which identifies the match.
    """
    opponent: str
    side: Side | None
    when: datetime | None
    time_given: bool
    postponed: bool
    sentence: str


@dataclass(frozen=True)
class Draw:
    """A new cup tie."""
    opponent: str
    home: bool
    competition: str
    kickoff: datetime | None
    date_confirmed: bool
    time_given: bool
    sentence: str


@dataclass
class FixtureNews:
    moves: list[Move] = field(default_factory=list)
    draws: list[Draw] = field(default_factory=list)
    unclear: list[str] = field(default_factory=list)  # names a known club with a date we couldn't place


def name_forms(opponent: str) -> list[str]:
    forms = {opponent}
    forms.update(k for k, v in ALIASES.items() if v == opponent)
    forms.update(_EXTRA.get(opponent, []))
    short = _SUFFIXES.sub("", opponent)
    if short != opponent and len(short) >= 4 and short.lower() not in _AMBIGUOUS:
        forms.add(short)
    return sorted(forms, key=len, reverse=True)


def _mentions(sentence: str, opponent: str) -> re.Match | None:
    for form in name_forms(opponent):
        m = re.search(rf"(?<![\w']){re.escape(form)}(?![\w'])", sentence, re.I)
        if m:
            return m
    return None


def _side(sentence: str, name: str | None = None) -> Side | None:
    """Home or away, from the sentence's wording ("at home", "trip to", "at Hull City")."""
    at_them = name is not None and re.search(rf"\bat\s+(?:the\s+)?{re.escape(name)}\b", sentence, re.I)
    home, away = bool(_HOME.search(sentence)), bool(_AWAY.search(sentence) or at_them)
    if home == away:
        return None
    return "home" if home else "away"


def _when(sentence: str, published: date) -> tuple[datetime | None, bool]:
    """The last date in a sentence ("moved from Saturday 21 to Sunday 22 November"
    names the new one last), with the time that follows it."""
    found = list(_DATE_RE.finditer(sentence))
    for m in reversed(found):
        d = parse_day_date(m.group(0), before=None, after=published)
        if d is None:
            continue
        t, assumed = parse_time(sentence[m.end():])
        return at_london(d, t), not assumed
    return None, False


def sentences(text: str) -> list[str]:
    out: list[str] = []
    for line in text.splitlines():
        out.extend(s.strip() for s in _SENTENCE.split(line) if s.strip())
    return out


def read(text: str, title: str, published: date, known: list[str]) -> FixtureNews:
    news = FixtureNews()
    parts = sentences(text)
    if _DRAW.search(title) or _DRAW.search(text[:400]):
        news.draws = _draws(parts, title, text, published)
    drawn = {d.opponent for d in news.draws}
    for s in parts:
        for opponent in known:
            name = _mentions(s, opponent)
            if name is None or opponent in drawn:
                continue
            when, time_given = _when(s, published)
            postponed = bool(_POSTPONED.search(s)) and not _NEW_DATE.search(s)
            if when is None and not postponed:
                if _DATE_RE.search(s):  # a date we couldn't read (e.g. its weekday doesn't fit)
                    news.unclear.append(s)
                continue  # otherwise a mention, not news about the match
            news.moves.append(Move(opponent, _side(s, name.group(0)), when, time_given, postponed, s))
    return news


def _draws(parts: list[str], title: str, text: str, published: date) -> list[Draw]:
    competition = _competition(title + "\n" + text)
    if competition == "Premier League":
        return []
    tie = next((h for h in (_heading(p.rstrip("."), "") for p in parts) if h), None)
    if tie is None:
        return []
    opponent, home = canonical(tie[0]), tie[1]
    legs = [p for p in parts if _LEG.search(p) and _DATE_RE.search(p)]
    draws: list[Draw] = []
    for p in legs:
        kickoff, time_given = _when(p, published)
        side = _side(p) if kickoff else None
        if kickoff is not None and side is not None:
            draws.append(Draw(opponent, side == "home", competition, kickoff, True, time_given, p))
    if draws:
        return draws
    dated = next((p for p in parts if _DATE_RE.search(p)), None)
    kickoff, time_given = _when(dated, published) if dated else (None, False)
    if kickoff is not None and not time_given:
        kickoff = kickoff.replace(hour=15, minute=0)  # a placeholder until the ticket news says
    confirmed = dated is not None and not _PROVISIONAL.search(dated)
    return [Draw(opponent, home, competition, kickoff, confirmed, time_given, dated or "")]
