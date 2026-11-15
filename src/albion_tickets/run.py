"""`albion check`: read the club's news, then bring the calendar in line.

Each run: find Ticket and Fixture News in the all-news listing, read every
article still relevant (Fixture News first, as ticket articles defer to it),
add the events no article produced this run, and sync (see sync.py for why
nothing is ever removed on a failed read).
"""
from collections.abc import Callable
from datetime import date, datetime, timedelta
from pathlib import Path

from . import config, news_updates
from .calendar_app import Calendar
from .discover import FIXTURE_NEWS, TICKET_NEWS, article_count, articles
from .fetch import FetchResult
from .model import url_slug
from .notices import Notice, alert, check_this, import_reminder
from .parse_article import article_text, is_tracked, parse_article
from .records import KEEP_TRACKING, adopt_import, last_import, match_notices, points_reminders, refresh_fixtures
from .store import State, save, snapshot
from .sync import Progress, Report, begin, next_sale, silent, sync

type Fetcher = Callable[[str], FetchResult]

FORGET_EMPTY_ARTICLE = timedelta(days=30)
ATTENTION_AFTER = 6  # failing runs in a row (about half a day) before the calendar is told


def run_check(cal: Calendar, fetcher: Fetcher, state_path: Path, now: datetime, dry_run: bool,
              progress: Progress = silent) -> Report:
    report = Report()
    if (state := begin(cal, state_path, report, progress)) is None:
        return report
    progress("Reading the club's ticket news…")
    _discover(state, fetcher, report)
    notices: list[Notice] = []
    owners_ok: set[str] = set()  # what was read successfully this run: only its events may be removed
    due = sorted((a for a in state.articles.items() if _due(*a, state, now)),
                 key=lambda a: a[1].get("kind") != "fixture")
    for i, (url, info) in enumerate(due, 1):
        progress(f"Reading article {i}/{len(due)}: {info.get('title') or url_slug(url)}…")
        read = _read_fixture_news if info.get("kind") == "fixture" else _read_ticket_news
        try:
            notices.extend(read(state, url, info, fetcher, now, dry_run, owners_ok, report))
        except Exception as exc:  # one broken article must not block the others
            report.errors.append(f"{url_slug(url)}: {type(exc).__name__}: {exc}")

    notices += refresh_fixtures(state, notices, owners_ok, now) + points_reminders(state, now)
    if (imported := last_import(state)) is not None:
        notices.append(import_reminder(imported, now))
    state.failing_runs = state.failing_runs + 1 if report.errors else 0
    if state.failing_runs >= ATTENTION_AFTER:
        notices.append(alert(f"attention:{now.date().isoformat()}",
                             f"albion-tickets needs attention: {report.errors[0]}",
                             "\n".join(report.errors) + "\n\nRun: albion check", now))
    report.next_sale = next_sale(state, notices, now)
    report.needs_look = [n.title.removeprefix("Check this ticket article: ") + (f" ({n.why})" if n.why else "")
                         for n in notices if n.key.startswith("check:") and n.key not in state.dismissed]
    sync(cal, state, notices, owners_ok, dry_run, report, progress)
    if not dry_run:
        state.last_check = now.isoformat()
        save(state, state_path)
    return report


def _discover(state: State, fetcher: Fetcher, report: Report) -> None:
    """Add the listing's Ticket and Fixture News articles not yet known."""
    for path in config.LISTING_PATHS:
        res = fetcher(config.BASE_URL + path)
        if not res.ok:
            report.errors.append(f"listing {path}: {res.error or res.status}")
        elif article_count(res.body) == 0:
            report.errors.append(f"listing {path}: no articles found (has the page format changed?)")
        else:
            for category, kind in ((TICKET_NEWS, "ticket"), (FIXTURE_NEWS, "fixture")):
                for ref in articles(res.body, category):
                    state.articles.setdefault(ref.url, {"title": ref.title, "published": ref.published.isoformat(),
                                                        "matches": [], "kind": kind})


def _due(url: str, info: dict, state: State, now: datetime) -> bool:
    """Whether an article is worth reading this run."""
    if info.get("kind") == "fixture":
        return news_updates.due(info, now)
    if info.get("untracked"):  # read once: only home league games, which the season ticket covers
        return False
    if not (keys := info.get("matches", [])):  # nothing found in it yet: keep trying for a month
        published = date.fromisoformat(info.get("published", now.date().isoformat()))
        return now.date() - published <= FORGET_EMPTY_ARTICLE
    recs = [state.matches.get(k) for k in keys]  # otherwise until its last match has been played
    return any(r is None or r.kickoff is None or r.kickoff + KEEP_TRACKING >= now for r in recs)


def _fetch_or_report(url: str, fetcher: Fetcher, report: Report) -> str | None:
    res = fetcher(url)
    if not res.ok:
        report.errors.append(f"{url_slug(url)}: {res.error or res.status}")
        return None
    return res.body


def _problem(url: str, info: dict, title: str, why: str, now: datetime, since: str = "first_problem") -> Notice:
    """A "check this" for an article, dated from when the problem was first seen."""
    first = datetime.fromisoformat(info.setdefault(since, now.isoformat()))
    return check_this(f"check:{url_slug(url)}", url, title, first, None, why)


def _read_fixture_news(state: State, url: str, info: dict, fetcher: Fetcher, now: datetime, dry_run: bool,
                       owners_ok: set[str], report: Report) -> list[Notice]:
    """A Fixture News article: moves, postponements and draws, recorded on the matches."""
    if (html := _fetch_or_report(url, fetcher, report)) is None:
        return []
    if (text := article_text(html, url_slug(url))) is None:
        return [_problem(url, info, info["title"], "couldn't find the article text on the page", now)]
    return news_updates.apply(state, url, info, text, now, report.changes)


def _read_ticket_news(state: State, url: str, info: dict, fetcher: Fetcher, now: datetime, dry_run: bool,
                      owners_ok: set[str], report: Report) -> list[Notice]:
    """A Ticket News article: each tracked match in it, recorded with its notices."""
    if (html := _fetch_or_report(url, fetcher, report)) is None:
        return []
    owners_ok.add(url)
    published = date.fromisoformat(info["published"])
    article = parse_article(html, url, published)
    if article is None:
        return [_problem(url, info, info["title"], "couldn't find the article text on the page", now)]
    if not article.matches and not article.ignorable:
        opening = next((l.strip() for l in article.text.splitlines() if l.strip()), "")
        return [_problem(url, info, article.title,
                         f"couldn't tell which match it's about; it starts “{opening[:60]}”", now)]
    info.pop("first_problem", None)
    if not dry_run:
        snapshot(url, article.text, config.data_dir(), now)

    out: list[Notice] = []
    new_keys = [m.key for m in article.matches]
    dropped = set(info.get("matches", [])) - set(new_keys)
    owners_ok.update(dropped)  # read successfully and gone from the article: retire their events
    if dropped or info.get("dropped"):
        info["dropped"] = sorted(set(info.get("dropped", [])) | dropped)
        gone = [state.matches[k].opponent if k in state.matches else k for k in info["dropped"]]
        out.append(_problem(url, info, article.title, f"{', '.join(gone)} no longer appears in it", now,
                            since="dropped_seen"))
    info["matches"] = new_keys
    tracked = [m for m in article.matches if is_tracked(m)]
    if not tracked:  # ignorable, or only home league games
        info["untracked"] = True
    for m in tracked:
        adopt_import(state, m, owners_ok)
        owners_ok.add(m.key)
        out.extend(match_notices(state, m, now, report, published))
    return out
