"""One check: fetch → discover → parse → decide → sync the calendar.

Removal is deliberately timid: an event is removed only when the article that
owns it was fetched and read successfully in this very run, and never while a
"check this" for the same match is open. A failed or partial fetch therefore
never deletes anything.
"""
import hashlib
import json
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta
from pathlib import Path
from collections.abc import Callable
from urllib.parse import urlsplit

from . import config
from .calendar_app import Calendar, CalendarError, Change
from . import news_updates
from .discover import FIXTURE_NEWS, TICKET_NEWS, article_count, articles
from .fetch import FetchResult
from .model import Match, Status
from .notices import SOON, Notice, change_notices, check_this, notices_for, points_due
from .parse_article import article_text, is_tracked, parse_article
from .rules import Outcome, decide, sold_out_text
from .store import State, load, observe, save, snapshot
from . import venues
from .ticket_page import PageResult

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
    imported: list[str] = field(default_factory=list)  # match keys an import added or refreshed
    skipped: list[str] = field(default_factory=list)  # "<what>: <why>" for everything an import left alone


def _fingerprint(n: Notice) -> str:
    parts = [n.title, n.start.isoformat(), n.end.isoformat(), [a.isoformat() for a in n.alarms], n.notes]
    if n.location:  # only when set, so events without one keep their fingerprint
        parts.append(n.location)
    if n.geo:
        parts.append(list(n.geo))
    raw = json.dumps(parts)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _dt(iso: str | None) -> datetime | None:
    return datetime.fromisoformat(iso) if iso else None


def _when(start: datetime | str | None) -> str:
    if isinstance(start, str):
        start = datetime.fromisoformat(start)
    if start is None:
        return "?"
    start = start.astimezone(config.TZ)
    return f"{start:%a} {start:%d %b %H:%M}"


def _slug(url: str) -> str:
    return urlsplit(url).path.rstrip("/").rsplit("/", 1)[-1]


def _active(info: dict, state: State, now: datetime) -> bool:
    if info.get("kind") == "fixture":
        return news_updates.due(info, now)
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
    active.sort(key=lambda a: a[1].get("kind") != "fixture")  # fixture news first: ticket articles defer to it
    for i, (url, info) in enumerate(active, 1):
        progress(f"Reading article {i}/{len(active)}: {info.get('title') or _slug(url)}…")
        try:
            read = _read_fixture_news if info.get("kind") == "fixture" else _read_article
            read(state, url, info, fetcher, now, dry_run, notices, owners_ok, report)
        except Exception as exc:  # one broken article must not block the others
            report.errors.append(f"{_slug(url)}: {type(exc).__name__}: {exc}")

    notices.extend(_refresh_fixtures(state, notices, owners_ok, now))
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


def _refresh_fixtures(state: State, notices: list[Notice], owners_ok: set[str], now: datetime) -> list[Notice]:
    """Match events this run didn't produce (imported matches, articles no longer
    read), rebuilt from their records so a change in how events look reaches
    every match. For matches from the club's news only events that exist are
    refreshed, so one an article retired is never brought back. A match from a
    saved page is never retired that way, so its event is also written if an
    earlier attempt failed. A match an article read this run covers
    (owners_ok) is left to that article, including dropping it."""
    produced = {n.key for n in notices}
    out: list[Notice] = []
    for key, rec in state.matches.items():
        fixture = f"fixture:{key}"
        from_page = rec.summary.get("source") in ("import", "draw")  # never retired by an article
        if fixture in produced or key in owners_ok or not rec.kickoffs:
            continue
        if fixture not in state.events and not from_page:
            continue
        kickoff = datetime.fromisoformat(rec.kickoffs[-1][0])
        if kickoff + KEEP_TRACKING < now:
            continue
        s = rec.summary
        m = Match(key, s.get("opponent", key), s.get("home", False), s.get("competition", ""), kickoff,
                  s.get("kickoff_confirmed", True), [], Status(), s.get("worth"), s.get("url", ""),
                  venue=rec.venue, date_confirmed=s.get("date_confirmed", True))
        m = news_updates.with_news(m, rec, None)
        built = notices_for(m, Outcome("unreadable", None, None), state.points, now, None, None)
        out.extend(_located([n for n in built if n.key == fixture], state, m))
    return out


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
        for category, kind in ((TICKET_NEWS, "ticket"), (FIXTURE_NEWS, "fixture")):
            for ref in articles(res.body, category):
                state.articles.setdefault(ref.url, {"title": ref.title, "published": ref.published.isoformat(),
                                                    "matches": [], "kind": kind})


def _read_fixture_news(state: State, url: str, info: dict, fetcher, now: datetime, dry_run: bool,
                       notices: list[Notice], owners_ok: set[str], report: Report) -> None:
    """A Fixture News article: moves, postponements and draws, recorded on the matches."""
    res = fetcher(url)
    if not res.ok:
        report.errors.append(f"{_slug(url)}: {res.error or res.status}")
        return
    text = article_text(res.body, _slug(url))
    if text is None:
        first = _dt(info.setdefault("first_problem", now.isoformat()))
        notices.append(check_this(f"check:{_slug(url)}", url, info["title"], first, None,
                                  "couldn't find the article text on the page"))
        return
    notices.extend(news_updates.apply(state, url, info, text, now, report.changes))


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
            _adopt_import(state, m, owners_ok)
            owners_ok.add(m.key)
            notices.extend(_match_notices(state, m, now, report, published))


def _match_notices(state: State, m: Match, now: datetime, report: Report,
                   published: date | None = None) -> list[Notice]:
    """Notices for a match read from a ticket article or saved page published on `published`."""
    rec = state.matches.get(m.key)
    m = news_updates.with_news(m, rec, published)
    if rec and rec.summary.get("source") == "draw":
        rec.kickoffs.clear()  # the draw's provisional date: the real one is not a "move"
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
    out = [
        *notices_for(m, outcome, state.points, now, _dt(rec.stage_opens.get("seen")),
                     _dt(rec.first_sold_out_seen), _dt(rec.first_problem)),
        *change_notices(changes, {m.key: m}, now),
    ]
    if m.key in state.have_tickets:
        out = [n for n in out if n.key.split(":", 1)[0] in KEEP_WITH_TICKETS]
    return _located(out, state, m)


def _located(notices: list[Notice], state: State, m: Match) -> list[Notice]:
    """Give the fixture event its ground."""
    rec = state.matches.get(m.key)
    where = venues.location(m.opponent, m.home, m.venue or (rec.venue if rec else None), state.venues)
    if where is None:
        return notices
    geo = (where.lat, where.lon) if where.lat is not None else None
    return [replace(n, location=where.address, geo=geo) if n.key.startswith("fixture:") else n
            for n in notices]


KEEP_WITH_TICKETS = {"fixture", "kickoff_moved"}  # with a ticket in hand, sale news is noise


def same_fixture(state: State, m: Match) -> str | None:
    """The key of a recorded match on the same day, at the same end, as m."""
    if m.kickoff is None:
        return None
    for key, rec in state.matches.items():
        if (rec.kickoffs and rec.summary.get("home") == m.home
                and datetime.fromisoformat(rec.kickoffs[-1][0]).date() == m.kickoff.date()):
            return key
    return None


def _adopt_import(state: State, m: Match, owners_ok: set[str]) -> None:
    """The club's article now covers a match first seen on a saved ticket page.

    Names differ between the two ("Spurs" / "Tottenham Hotspur"), so the match
    is found by its day. Its record moves to the article's key, keeping its
    first-seen times, and the import's events are retired: the article's
    notices replace them in this same run.
    """
    if m.key in state.matches:
        return
    old = same_fixture(state, m)
    if old is None or state.matches[old].summary.get("source") != "import":
        return
    state.matches[m.key] = state.matches.pop(old)
    owners_ok.add(old)
    if old in state.have_tickets:
        state.have_tickets.discard(old)
        state.have_tickets.add(m.key)


def run_import(cal: Calendar, pages: list[PageResult], state_path: Path, now: datetime,
               dry_run: bool, progress: Callable[[str], None] = _silent) -> Report:
    """Matches from ticket pages the user saved by hand → records and calendar events.

    The club's news stays in charge: a match already tracked from an article is
    left alone. Nothing is ever removed here, so an import can only add.
    """
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
    notices: list[Notice] = []
    retired: set[str] = set()  # old keys of records renamed here: their events give way to the new ones
    for page in pages:
        report.skipped.extend(f"{s}: not a match" for s in page.skipped)
        for m in page.matches:
            name = f"{m.opponent} ({'H' if m.home else 'A'})"
            if not is_tracked(m):
                continue  # home league games: the season ticket covers them
            if m.kickoff is not None and m.kickoff < now:
                report.skipped.append(f"{name}: already played")
                continue
            existing = m.key if m.key in state.matches else same_fixture(state, m)
            if existing and state.matches[existing].summary.get("source") not in ("import", "draw"):
                st = m.status
                page = f"; the page says {sold_out_text(st.sold_out_to)}" if st.sold_out_to else ""
                report.skipped.append(f"{name}: already tracked from the club's news{page}")
                _remember_page(state, existing, m, now)
                continue
            if existing and existing != m.key:
                state.matches[m.key] = state.matches.pop(existing)
                retired.add(existing)
                if existing in state.have_tickets:
                    state.have_tickets.discard(existing)
                    state.have_tickets.add(m.key)
            if m.stages:
                found = _match_notices(state, m, now, report, now.date())
                state.matches[m.key].summary["source"] = "import"
            else:  # sold out, or no dates yet: the fixture alone, never a "check this"
                found = _fixture_only(state, m, now, report)
            notices.extend(found)
            _remember_page(state, m.key, m, now)
            report.imported.append(m.key)
    upcoming = sorted((n for n in notices if n.key.startswith("sale:") and n.alarms and n.start > now),
                      key=lambda n: n.start)
    report.next_sale = upcoming[0].title if upcoming else None
    _sync(cal, state, notices, retired, dry_run, report, progress)
    if not dry_run:
        save(state, state_path)
    return report


def _remember_page(state: State, key: str, m: Match, now: datetime) -> None:
    """Keep what a saved page says that the club's news may not: sell-out level and ground."""
    rec = state.matches[key]
    if m.venue:
        rec.venue = m.venue
        if not m.home:
            state.venues[m.opponent] = m.venue
    label = m.status.sold_out_to
    if label and rec.page_sold_out.get("label") != label:
        rec.page_sold_out = {"label": label, "seen": now.isoformat()}


def _fixture_only(state: State, m: Match, now: datetime, report: Report) -> list[Notice]:
    changes = observe(state, m, None, now)
    rec = state.matches[m.key]
    st = m.status
    sold = st.sold_out_label_seen or st.sold_out_to is not None
    rec.summary = {
        "opponent": m.opponent, "home": m.home, "competition": m.competition, "url": m.url,
        "kind": "sold_out" if sold else "on_sale" if m.on_sale_now else "no_dates", "opens": None,
        "sold_out_stage": st.sold_out_to, "kickoff_confirmed": m.kickoff_confirmed,
        "worth": m.fixture_points, "stages": [], "your_stage": None, "source": "import",
    }
    for c in changes:
        report.changes.append(f"{m.opponent}: {c.kind.replace('_', ' ')} {c.old} → {c.new}")
    out = [n for n in notices_for(m, Outcome("unreadable", None, None), state.points, now, None, None)
           if n.key.startswith("fixture:")]
    return _located(out, state, m) + change_notices(changes, {m.key: m}, now)


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
    """Bring the calendar in line, in one batch. Only what succeeded is recorded or
    reported: a failed change keeps its old fingerprint and is retried next time."""
    notices = [n for n in notices if n.key not in state.dismissed]
    wanted = {n.key for n in notices}
    writes: list[tuple[Notice, dict | None, str]] = []
    for n in notices:
        existing = state.events.get(n.key)
        fp = _fingerprint(n)
        if existing and (existing.get("fp") == fp or existing.get("one_shot")):
            continue
        writes.append((n, existing, fp))
    writes.sort(key=lambda w: w[0].start)  # so the report reads in date order
    removals: list[tuple[str, dict]] = []
    for key, ev in list(state.events.items()):
        owner = ev.get("owner")
        if key in wanted or ev.get("one_shot") or owner not in owners_ok:
            continue
        if f"check:{owner}" in wanted:  # something needs a look: keep what we had meanwhile
            continue
        removals.append((key, ev))

    line = lambda start, title: f"{_when(start)} · {title}"
    if dry_run:
        for n, existing, _ in writes:
            (report.updated if existing else report.created).append(line(n.start, n.title))
        report.removed.extend(line(ev.get("start"), ev.get("title", key)) for key, ev in removals)
        return
    changes = [Change(existing["uid"] if existing else None, n) for n, existing, _ in writes]
    changes += [Change(ev["uid"]) for _, ev in removals]
    if changes:
        progress(f"Updating the calendar ({len(changes)} {'change' if len(changes) == 1 else 'changes'})…")
    results = cal.apply(changes) if changes else []
    for (n, existing, fp), result in zip(writes, results):
        if isinstance(result, CalendarError):
            report.errors.append(f"calendar: {n.key}: {result}")
            continue
        (report.updated if existing else report.created).append(line(n.start, n.title))
        state.events[n.key] = {"uid": result, "owner": _owner(n.key, state), "one_shot": n.one_shot, "fp": fp,
                               "start": n.start.isoformat(), "title": n.title}
    for (key, ev), result in zip(removals, results[len(writes):]):
        if isinstance(result, CalendarError):
            report.errors.append(f"calendar: remove {key}: {result}")
            continue
        report.removed.append(line(ev.get("start"), ev.get("title", key)))
        del state.events[key]
