"""One check: fetch → discover → parse → decide → sync the calendar.

Removal is deliberately timid: an event is removed only when the article that
owns it was fetched and read successfully in this very run, and never while a
"check this" for the same match is open. A failed or partial fetch therefore
never deletes anything.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable
from urllib.parse import urlsplit

from . import config
from .calendar_app import Calendar, CalendarError
from .discover import article_count, ticket_articles
from .fetch import FetchResult
from .model import Match
from .notices import SOON, Notice, change_notices, check_this, notices_for, points_due
from .parse_article import is_tracked, parse_article
from .rules import decide
from .store import State, load, observe, save, snapshot

KEEP_TRACKING = timedelta(days=1)
FORGET_EMPTY_ARTICLE = timedelta(days=30)
ATTENTION_AFTER = 6  # failing runs in a row (about half a day) before the calendar is told


@dataclass
class Report:
    created: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    changes: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    next_sale: str | None = None
    needs_look: list[str] = field(default_factory=list)


def _fingerprint(n: Notice) -> str:
    raw = json.dumps([n.title, n.start.isoformat(), n.end.isoformat(),
                      [a.isoformat() for a in n.alarms], n.notes])
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _dt(iso: str | None) -> datetime | None:
    return datetime.fromisoformat(iso) if iso else None


def _when(start: datetime | str | None) -> str:
    if isinstance(start, str):
        start = datetime.fromisoformat(start)
    if start is None:
        return "?"
    start = start.astimezone(config.TZ)
    return f"{start:%a} {start.day} {start:%b %H:%M}"


def _slug(url: str) -> str:
    return urlsplit(url).path.rstrip("/").rsplit("/", 1)[-1]


def _active(info: dict, state: State, now: datetime) -> bool:
    if info.get("untracked"):  # read once: only home league games, which the season ticket covers
        return False
    keys = info.get("matches", [])
    if not keys:
        published = date.fromisoformat(info.get("published", now.date().isoformat()))
        return now.date() - published <= FORGET_EMPTY_ARTICLE
    for k in keys:
        rec = state.matches.get(k)
        latest = _dt(rec.kickoffs[-1][0]) if rec and rec.kickoffs else None
        if latest is None or latest + KEEP_TRACKING >= now:
            return True
    return False


def _silent(_: str) -> None:
    pass


def run_check(cal: Calendar, fetcher: Callable[[str], FetchResult], state_path: Path,
              now: datetime, dry_run: bool, progress: Callable[[str], None] = _silent) -> Report:
    report = Report()
    progress("Checking the calendar is ready (macOS may ask to allow this)…")
    problem = cal.check_ready()
    if problem:
        report.errors.append(problem)
        return report
    state = load(state_path)
    if state.points is None:
        report.errors.append("Set your points first: albion points <n>")
        return report

    progress("Reading the club's ticket news…")
    _discover(state, fetcher, report, progress)
    notices: list[Notice] = []
    owners_ok: set[str] = set()
    active = [(url, info) for url, info in list(state.articles.items()) if _active(info, state, now)]
    for i, (url, info) in enumerate(active, 1):
        progress(f"Reading article {i}/{len(active)}: {info.get('title') or _slug(url)}…")
        try:
            _read_article(state, url, info, fetcher, now, dry_run, notices, owners_ok, report)
        except Exception as exc:  # one broken article must not block the others
            report.errors.append(f"{_slug(url)}: {type(exc).__name__}: {exc}")

    notices.extend(_points_due(state, now))

    state.failing_runs = state.failing_runs + 1 if report.errors else 0
    if state.failing_runs >= ATTENTION_AFTER:
        start = now + SOON
        notices.append(Notice(f"attention:{now.date().isoformat()}",
                              f"⚠️ albion-tickets needs attention: {report.errors[0]}",
                              start, start + timedelta(minutes=15), [start],
                              "\n".join(report.errors) + "\n\nRun: albion check", one_shot=True))

    upcoming = sorted((n for n in notices if n.key.startswith("sale:") and n.alarms and n.start > now),
                      key=lambda n: n.start)
    report.next_sale = upcoming[0].title if upcoming else None
    report.needs_look = [n.title.removeprefix("Check this ticket article: ") + (f" ({n.why})" if n.why else "")
                         for n in notices if n.key.startswith("check:") and n.key not in state.dismissed]
    _sync(cal, state, notices, owners_ok, dry_run, report, progress)
    if not dry_run:
        state.last_check = now.isoformat()
        save(state, state_path)
    return report


def _points_due(state: State, now: datetime) -> list[Notice]:
    out = []
    for key, rec in state.matches.items():
        s = rec.summary
        if s.get("home", True) or not rec.kickoffs:
            continue
        n = points_due(key, s.get("opponent", key), datetime.fromisoformat(rec.kickoffs[-1][0]),
                       s.get("worth"), now)
        if n is not None:
            out.append(n)
    return out


def _discover(state: State, fetcher, report: Report, progress: Callable[[str], None] = _silent) -> None:
    for path in config.LISTING_PATHS:
        res = fetcher(config.BASE_URL + path)
        if not res.ok:
            report.errors.append(f"listing {path}: {res.error or res.status}")
            continue
        if article_count(res.body) == 0:
            report.errors.append(f"listing {path}: no articles found (has the page format changed?)")
            continue
        for ref in ticket_articles(res.body):
            state.articles.setdefault(ref.url, {"title": ref.title, "published": ref.published.isoformat(),
                                                "matches": []})


def _read_article(state: State, url: str, info: dict, fetcher, now: datetime, dry_run: bool,
                  notices: list[Notice], owners_ok: set[str], report: Report) -> None:
    res = fetcher(url)
    if not res.ok:
        report.errors.append(f"{_slug(url)}: {res.error or res.status}")
        return
    owners_ok.add(url)
    check_key = f"check:{_slug(url)}"
    published = date.fromisoformat(info["published"])
    article = parse_article(res.body, url, published)
    if article is None or (not article.matches and not article.ignorable):
        first = _dt(info.setdefault("first_problem", now.isoformat()))
        if article is None:
            reason = "couldn't find the article text on the page"
        else:
            opening = next((l.strip() for l in article.text.splitlines() if l.strip()), "")
            reason = f"couldn't tell which match it's about; it starts “{opening[:60]}”"
        notices.append(check_this(check_key, url, article.title if article else info["title"], first, None,
                                  reason))
        return
    info.pop("first_problem", None)
    if not dry_run:
        snapshot(url, article.text, config.data_dir(), now)

    new_keys = [m.key for m in article.matches]
    dropped = set(info.get("matches", [])) - set(new_keys)
    owners_ok.update(dropped)  # read successfully and gone from the article: retire their events
    if dropped or info.get("dropped"):
        info["dropped"] = sorted(set(info.get("dropped", [])) | dropped)
        first = _dt(info.setdefault("dropped_seen", now.isoformat()))
        gone = [state.matches[k].summary.get("opponent", k) if k in state.matches else k for k in info["dropped"]]
        notices.append(check_this(check_key, url, article.title, first, None,
                                  f"{', '.join(gone)} no longer appears in it"))
    info["matches"] = new_keys
    if article.ignorable or (article.matches and not any(is_tracked(m) for m in article.matches)):
        info["untracked"] = True

    for m in article.matches:
        if is_tracked(m):
            owners_ok.add(m.key)
            notices.extend(_match_notices(state, m, now, report))


def _match_notices(state: State, m: Match, now: datetime, report: Report) -> list[Notice]:
    rec = state.matches.get(m.key)
    first = rec.first_sold_out_seen if rec else None
    provisional = decide(m, state.points, now, _dt(first))
    changes = observe(state, m, provisional.opens, now)
    rec = state.matches[m.key]
    outcome = decide(m, state.points, now, _dt(rec.first_sold_out_seen))
    if outcome.opens is not None and outcome.opens != provisional.opens:
        rec.stage_opens = {"value": outcome.opens.isoformat(), "seen": now.isoformat()}
    if outcome.kind == "unreadable":
        rec.first_problem = rec.first_problem or now.isoformat()
    else:
        rec.first_problem = None
    rec.summary = {
        "opponent": m.opponent, "home": m.home, "competition": m.competition, "url": m.url,
        "kind": outcome.kind, "opens": outcome.opens.isoformat() if outcome.opens else None,
        "sold_out_stage": outcome.sold_out_stage, "kickoff_confirmed": m.kickoff_confirmed,
        "worth": m.fixture_points,
        "stages": [{"label": st.label, "opens": st.opens.isoformat(), "min_points": st.min_points,
                    "pending": st.brackets_pending} for st in m.stages],
        "your_stage": outcome.stage.label if outcome.stage else None,
    }
    for c in changes:
        report.changes.append(f"{m.opponent}: {c.kind.replace('_', ' ')} {c.old} → {c.new}")
    return [
        *notices_for(m, outcome, state.points, now, _dt(rec.stage_opens.get("seen")),
                     _dt(rec.first_sold_out_seen), _dt(rec.first_problem)),
        *change_notices(changes, {m.key: m}, now),
    ]


def _owner(key: str, state: State) -> str:
    kind, rest = key.split(":", 1)
    if kind == "check":
        for url in state.articles:
            if _slug(url) == rest:
                return url
        return rest
    if kind == "attention":
        return "attention"
    return rest.split(":", 1)[0]


def _sync(cal: Calendar, state: State, notices: list[Notice], owners_ok: set[str],
          dry_run: bool, report: Report, progress: Callable[[str], None] = _silent) -> None:
    notices = [n for n in notices if n.key not in state.dismissed]
    wanted = {n.key for n in notices}
    to_write = []
    for n in notices:
        existing = state.events.get(n.key)
        fp = _fingerprint(n)
        if existing and (existing.get("fp") == fp or existing.get("one_shot")):
            continue
        (report.updated if existing else report.created).append(f"{_when(n.start)} · {n.title}")
        to_write.append((n, existing, fp))
    to_remove = []
    for key, ev in list(state.events.items()):
        owner = ev.get("owner")
        if key in wanted or ev.get("one_shot") or owner not in owners_ok:
            continue
        if f"check:{owner}" in wanted:  # something needs a look: keep what we had meanwhile
            continue
        report.removed.append(f"{_when(ev.get('start'))} · {ev.get('title', key)}")
        to_remove.append((key, ev))
    if dry_run:
        return
    total = len(to_write) + len(to_remove)
    for i, (n, existing, fp) in enumerate(to_write, 1):
        progress(f"Updating the calendar {i}/{total}…")
        try:
            uid = cal.upsert(n, existing["uid"] if existing else None)
        except CalendarError as exc:
            report.errors.append(f"calendar: {n.key}: {exc}")
            continue
        state.events[n.key] = {"uid": uid, "owner": _owner(n.key, state), "one_shot": n.one_shot, "fp": fp,
                               "start": n.start.isoformat(), "title": n.title}
    for i, (key, ev) in enumerate(to_remove, len(to_write) + 1):
        progress(f"Updating the calendar {i}/{total}…")
        try:
            cal.remove(ev["uid"])
        except CalendarError as exc:
            report.errors.append(f"calendar: remove {key}: {exc}")
            continue
        del state.events[key]
