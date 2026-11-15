"""Bringing the calendar in line with this run's notices, and what a run reports.

Removal is deliberately timid: an event is removed only when its owner (the
article or match it came from) was read successfully in this very run, and
never while a "check this" for it is open. A failed or partial read therefore
never deletes anything. Only what succeeded is recorded: a failed change keeps
its old fingerprint and is retried next run.
"""
import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from .calendar_app import Calendar, CalendarError, Change, Event
from .display import when
from .model import url_slug
from .notices import Notice
from .store import State, load

type Progress = Callable[[str], None]


def silent(_: str) -> None:
    pass


@dataclass
class Report:
    created: list[str] = field(default_factory=list)  # "Wed 02 Dec 20:15 · title", for -v
    updated: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    changes: list[str] = field(default_factory=list)  # kick-off and sale moves, for the summary
    errors: list[str] = field(default_factory=list)
    next_sale: str | None = None
    needs_look: list[str] = field(default_factory=list)
    imported: list[str] = field(default_factory=list)  # match keys an import added or refreshed
    skipped: list[str] = field(default_factory=list)  # "<what>: <why>" for everything an import left alone


def begin(cal: Calendar, state_path: Path, report: Report, progress: Progress) -> State | None:
    """The state, once the calendar is reachable and points are set; else None, with the reason reported."""
    progress("Checking the calendar is ready (macOS may ask to allow this)…")
    if problem := cal.check_ready():
        report.errors.append(problem)
        return None
    state = load(state_path)
    if state.points is None:
        report.errors.append("Set your points first: albion points <n>")
        return None
    return state


def next_sale(state: State, notices: list[Notice], now: datetime) -> str | None:
    """The title of the soonest sale still to come, among every tracked match (not just those read this run)."""
    titles = {k: ev["title"] for k, ev in state.events.items()} | {n.key: n.title for n in notices}
    ahead = sorted((opens, f"sale:{key}") for key, rec in state.matches.items()
                   if key not in state.have_tickets and rec.summary.get("kind") in ("sale", "predicted_sale")
                   and (opens := _dt(rec.summary.get("opens"))) and opens > now)
    return next((titles[key] for _, key in ahead if key in titles), None)


def _dt(iso: str | None) -> datetime | None:
    return datetime.fromisoformat(iso) if iso else None


def fingerprint(n: Notice) -> str:
    """What the calendar event shows: a change here means the event needs rewriting."""
    parts = [n.title, n.start.isoformat(), n.end.isoformat(), [a.isoformat() for a in n.alarms], n.notes]
    if n.location:  # only when set, so events without one keep their fingerprint
        parts.append(n.location)
    if n.geo:
        parts.append(list(n.geo))
    return hashlib.sha256(json.dumps(parts).encode()).hexdigest()[:16]


def owner(key: str, state: State) -> str:
    """What an event belongs to: a "check this" its article's URL, anything else its match."""
    kind, rest = key.split(":", 1)
    match kind:
        case "check":
            return next((url for url in state.articles if url_slug(url) == rest), rest)
        case "attention":
            return "attention"
        case _:
            return rest.split(":", 1)[0]


def sync(cal: Calendar, state: State, notices: list[Notice], owners_ok: set[str],
         dry_run: bool, report: Report, progress: Progress = silent) -> None:
    """Write what changed and remove what is no longer wanted, in one batch."""
    notices = [n for n in notices if n.key not in state.dismissed]
    writes = sorted(_writes(state, notices), key=lambda w: w[0].start)  # so the report reads in date order
    removals = _removals(state, {n.key for n in notices}, owners_ok)
    line = lambda start, title: f"{when(start)} · {title}"
    if dry_run:
        for n, existing, _ in writes:
            (report.updated if existing else report.created).append(line(n.start, n.title))
        report.removed.extend(line(ev.get("start"), ev.get("title", key)) for key, ev in removals)
        return

    changes = [Change(existing["uid"] if existing else None, n) for n, existing, _ in writes]
    changes += [Change(ev["uid"]) for _, ev in removals]
    if not changes:
        return
    progress(f"Updating the calendar ({len(changes)} {'change' if len(changes) == 1 else 'changes'})…")
    results = cal.apply(changes)
    for (n, existing, fp), result in zip(writes, results[:len(writes)], strict=True):
        if isinstance(result, CalendarError):
            report.errors.append(f"calendar: {n.key}: {result}")
            continue
        (report.updated if existing else report.created).append(line(n.start, n.title))
        state.events[n.key] = {"uid": result, "owner": owner(n.key, state), "one_shot": n.one_shot, "fp": fp,
                               "start": n.start.isoformat(), "title": n.title}
    for (key, ev), result in zip(removals, results[len(writes):], strict=True):
        if isinstance(result, CalendarError):
            report.errors.append(f"calendar: remove {key}: {result}")
            continue
        report.removed.append(line(ev.get("start"), ev.get("title", key)))
        del state.events[key]


def _writes(state: State, notices: list[Notice]) -> list[tuple[Notice, dict | None, str]]:
    """(notice, its event if any, fingerprint) for each notice new or changed. Alerts are written once."""
    out = []
    for n in notices:
        existing, fp = state.events.get(n.key), fingerprint(n)
        if not existing or (existing.get("fp") != fp and not existing.get("one_shot")):
            out.append((n, existing, fp))
    return out


def _removals(state: State, wanted: set[str], owners_ok: set[str]) -> list[tuple[str, dict]]:
    """Events no notice wants, whose owner was read this run and has nothing awaiting a look."""
    return [(key, ev) for key, ev in state.events.items()
            if key not in wanted and not ev.get("one_shot") and ev.get("owner") in owners_ok
            and f"check:{ev.get('owner')}" not in wanted]


TIDY_FROM, TIDY_TO = timedelta(days=30), timedelta(days=400)  # recent past to the end of next season


def untracked(cal: Calendar, state: State, now: datetime) -> list[Event]:
    """Events in our calendar the state doesn't know: written, but their reply was lost (see `albion tidy`)."""
    known = {ev["uid"] for ev in state.events.values()}
    return [e for e in cal.listing(now - TIDY_FROM, now + TIDY_TO) if e.uid not in known and e.local not in known]
