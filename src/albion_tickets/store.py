"""Local state: points, what's been seen over time, and which calendar events exist.

Everything lives under data/ (gitignored). A corrupt state file stops the run
rather than being silently reset, which would duplicate every event.
"""
import hashlib
import json
import os
import re
import shutil
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Literal

from .model import Match


class StateError(Exception):
    pass


@dataclass
class MatchRecord:
    kickoffs: list[tuple[str, str]] = field(default_factory=list)  # (kick-off, first seen)
    stage_opens: dict[str, str] = field(default_factory=dict)  # {"value": iso, "seen": iso}
    first_sold_out_seen: str | None = None
    presale_sold_label: bool = False
    first_problem: str | None = None
    last_seen: str = ""
    summary: dict = field(default_factory=dict)  # opponent, home, competition, url, outcome …
    # The sell-out level a saved ticket page gave ({"label", "seen"}). Kept apart
    # from summary, which every check rebuilds, because it is the record that
    # matters year on year and the club's news often never states it.
    page_sold_out: dict[str, str] = field(default_factory=dict)
    venue: str | None = None  # the ground a saved ticket page gave for this match
    # The latest Fixture News about this match: {published, url, and kickoff +
    # confirmed, or postponed}. It wins over any source published before it.
    news: dict[str, str] = field(default_factory=dict)

    def sold_out_at(self) -> str | None:
        return self.summary.get("sold_out_stage") or self.page_sold_out.get("label")

    @property
    def kickoff_iso(self) -> str:
        """The latest kick-off seen ("" if none): also a sort key."""
        return self.kickoffs[-1][0] if self.kickoffs else ""

    @property
    def kickoff(self) -> datetime | None:
        return datetime.fromisoformat(self.kickoff_iso) if self.kickoffs else None

    @property
    def opponent(self) -> str:
        return self.summary.get("opponent", "?")

    @property
    def home(self) -> bool:
        return self.summary.get("home", False)


@dataclass
class State:
    points: int | None = None
    matches: dict[str, MatchRecord] = field(default_factory=dict)
    events: dict[str, dict] = field(default_factory=dict)  # notice key → {uid, match, one_shot, …}
    dismissed: set[str] = field(default_factory=set)
    articles: dict[str, dict] = field(default_factory=dict)  # url → {title, published, matches}
    failing_runs: int = 0
    export_dir: str | None = None  # where `albion export` copies the history after each check
    last_check: str | None = None  # when a (non-dry) check last read the club's news
    have_tickets: set[str] = field(default_factory=set)  # match keys: no sale reminders for these
    venues: dict[str, str] = field(default_factory=dict)  # opponent → ground, learnt from saved pages


@dataclass(frozen=True)
class Change:
    kind: Literal["kickoff_moved", "sale_moved"]
    match_key: str
    old: str
    new: str


def load(path: Path) -> State:
    if not path.exists():
        return State()
    try:
        raw = json.loads(path.read_text())
        return State(
            points=raw.get("points"),
            matches={k: MatchRecord(
                kickoffs=[tuple(x) for x in v.get("kickoffs", [])],
                stage_opens=v.get("stage_opens", {}),
                first_sold_out_seen=v.get("first_sold_out_seen"),
                presale_sold_label=v.get("presale_sold_label", False),
                first_problem=v.get("first_problem"),
                last_seen=v.get("last_seen", ""),
                summary=v.get("summary", {}),
                page_sold_out=v.get("page_sold_out", {}),
                venue=v.get("venue"),
                news=v.get("news", {}),
            ) for k, v in raw.get("matches", {}).items()},
            events=raw.get("events", {}),
            dismissed=set(raw.get("dismissed", [])),
            articles=raw.get("articles", {}),
            failing_runs=raw.get("failing_runs", 0),
            export_dir=raw.get("export_dir"),
            last_check=raw.get("last_check"),
            have_tickets=set(raw.get("have_tickets", [])),
            venues=raw.get("venues", {}),
        )
    except (ValueError, TypeError, AttributeError) as exc:
        raise StateError(f"{path} is unreadable ({exc}); fix or move it aside — not resetting") from exc


KEEP_DAILY = 14


def backup(path: Path, today: date) -> None:
    """Before the day's first save, keep the state as it was: 14 days, plus the first of each month."""
    if not path.exists():
        return
    folder = path.parent / "backups"
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"state-{today.isoformat()}.json"
    if not target.exists():
        shutil.copy2(path, target)
    dated = sorted(folder.glob("state-????-??-??.json"))
    keep = set(dated[-KEEP_DAILY:])
    firsts: dict[str, Path] = {}
    for f in dated:
        firsts.setdefault(f.name[6:13], f)  # earliest file in each month
    keep |= set(firsts.values())
    for f in dated:
        if f not in keep:
            f.unlink()


def save(state: State, path: Path, today: date | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    backup(path, today or date.today())
    data = {
        "points": state.points,
        "matches": {k: asdict(v) for k, v in state.matches.items()},
        "events": state.events,
        "dismissed": sorted(state.dismissed),
        "articles": state.articles,
        "failing_runs": state.failing_runs,
        "export_dir": state.export_dir,
        "last_check": state.last_check,
        "have_tickets": sorted(state.have_tickets),
        "venues": state.venues,
    }
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=1, sort_keys=True))
    os.replace(tmp, path)


def snapshot(url: str, text: str, data_dir: Path, now: datetime) -> bool:
    """Keep each distinct version of an article once. True if this one is new."""
    norm = re.sub(r"\s+", " ", text).strip()
    digest = hashlib.sha256(norm.encode()).hexdigest()
    folder = data_dir / "snapshots"
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"{digest}.txt"
    if target.exists():
        return False
    target.write_text(text)
    with (folder / "index.jsonl").open("a") as f:
        f.write(json.dumps({"url": url, "sha256": digest, "seen": now.isoformat()}) + "\n")
    return True


def observe(state: State, m: Match, outcome_opens: datetime | None, now: datetime) -> list[Change]:
    rec = state.matches.setdefault(m.key, MatchRecord())
    changes: list[Change] = []
    stamp = now.isoformat()

    if m.kickoff is not None:
        ko = m.kickoff.isoformat()
        if not rec.kickoffs:
            rec.kickoffs.append((ko, stamp))
        elif rec.kickoff_iso != ko:
            changes.append(Change("kickoff_moved", m.key, rec.kickoff_iso, ko))
            rec.kickoffs.append((ko, stamp))

    if outcome_opens is not None:
        new = outcome_opens.isoformat()
        old = rec.stage_opens.get("value")
        live = (old is not None and datetime.fromisoformat(old) > now) or outcome_opens > now
        if old is not None and old != new and live:
            changes.append(Change("sale_moved", m.key, old, new))
        if old != new:
            rec.stage_opens = {"value": new, "seen": stamp}

    st = m.status
    if st.sold and m.stages:
        if now < min(s.opens for s in m.stages):
            rec.presale_sold_label = True  # a label before sales: never trusted on its own
        elif rec.first_sold_out_seen is None and (not rec.presale_sold_label or st.sold_out_to is not None):
            rec.first_sold_out_seen = stamp

    rec.last_seen = stamp
    return changes
