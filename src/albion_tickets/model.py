"""The shapes passed between parsing, rules and the calendar."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

Audience = Literal["sth", "myalbion", "guests", "general", "other"]


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
