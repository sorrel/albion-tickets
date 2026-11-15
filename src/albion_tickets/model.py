"""The shapes passed between parsing, rules and the calendar, and how matches are named."""
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Literal
from urllib.parse import urlsplit

type Audience = Literal["sth", "myalbion", "guests", "general", "other"]


@dataclass(frozen=True)
class Stage:
    label: str
    audience: Audience
    min_points: int | None
    brackets_pending: bool
    opens: datetime
    time_assumed: bool


@dataclass(frozen=True)
class Status:
    sold_out_to: str | None = None
    sold_out_min_points: int | None = None
    sold_out_label_seen: bool = False
    wheelchair_only: bool = False
    exchange_closes: datetime | None = None

    @property
    def sold(self) -> bool:
        """The page says it has sold out, in any of the club's ways of saying so."""
        return self.sold_out_label_seen or self.wheelchair_only or self.sold_out_to is not None


@dataclass(frozen=True)
class Match:
    key: str
    opponent: str
    home: bool
    competition: str
    kickoff: datetime | None
    kickoff_confirmed: bool
    stages: list[Stage]
    status: Status
    fixture_points: int | None
    url: str
    unreadable: list[str] = field(default_factory=list)
    on_sale_now: bool = False  # a saved ticket page says so, with no dated stages
    venue: str | None = None  # the ground a saved ticket page names
    postponed: bool = False  # Fixture News said so, with no new date yet
    date_confirmed: bool = True  # False for a cup draw's provisional weekend


def slug(text: str) -> str:
    """'Nottingham Forest' → 'nottingham-forest'."""
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def url_slug(url: str) -> str:
    """An article's URL → its last path part, which names it in keys and messages."""
    return urlsplit(url).path.rstrip("/").rsplit("/", 1)[-1]


def season_of(day: date) -> str:
    """A season runs August to July: 15 Jan 2027 → '2026-27'."""
    start = day.year if day.month >= 8 else day.year - 1
    return f"{start}-{(start + 1) % 100:02d}"


def match_key(day: date, opponent: str, home: bool, competition: str) -> str:
    """One match's key in every source: '2026-27-hull-city-a-premier-league'."""
    return f"{season_of(day)}-{slug(opponent)}-{'h' if home else 'a'}-{slug(competition)}"


def short_name(opponent: str, home: bool) -> str:
    """'Hull City (A)', as the tables show a match."""
    return f"{opponent} ({'H' if home else 'A'})"
