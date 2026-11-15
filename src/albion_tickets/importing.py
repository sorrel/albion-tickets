"""`albion import`: matches from ticket pages the user saved by hand → records and calendar events.

The club's news stays in charge: a match already tracked from an article is
left alone, apart from what only the saved page says (sell-out level, ground).
Nothing is ever removed here, so an import can only add.
"""
from datetime import datetime
from pathlib import Path

from .calendar_app import Calendar
from .model import Match, short_name
from .notices import Notice
from .parse_article import is_tracked
from .records import FROM_PAGE, fixture_only, match_notices, rename, same_fixture
from .rules import sold_out_text
from .store import State, save
from .sync import Progress, Report, begin, next_sale, silent, sync
from .ticket_page import PageResult


def run_import(cal: Calendar, pages: list[PageResult], state_path: Path, now: datetime,
               dry_run: bool, progress: Progress = silent) -> Report:
    report = Report()
    if (state := begin(cal, state_path, report, progress)) is None:
        return report
    notices: list[Notice] = []
    retired: set[str] = set()  # old keys of records renamed here: their events give way to the new ones
    for page in pages:
        report.skipped.extend(f"{s}: not a match" for s in page.skipped)
        for m in filter(is_tracked, page.matches):  # home league games: the season ticket covers them
            notices.extend(_import(state, m, now, report, retired))
    report.next_sale = next_sale(state, notices, now)
    sync(cal, state, notices, retired, dry_run, report, progress)
    if not dry_run:
        save(state, state_path)
    return report


def _import(state: State, m: Match, now: datetime, report: Report, retired: set[str]) -> list[Notice]:
    """One saved-page match: recorded with its notices, or noted as left alone."""
    if m.kickoff is not None and m.kickoff < now:
        report.skipped.append(f"{short_name(m.opponent, m.home)}: already played")
        return []
    existing = m.key if m.key in state.matches else same_fixture(state, m)
    if existing and state.matches[existing].summary.get("source") not in FROM_PAGE:
        said = f"; the page says {sold_out_text(m.status.sold_out_to)}" if m.status.sold_out_to else ""
        report.skipped.append(f"{short_name(m.opponent, m.home)}: already tracked from the club's news{said}")
        _remember_page(state, existing, m, now)
        return []
    if existing and existing != m.key:
        rename(state, existing, m.key)
        retired.add(existing)
    if m.stages:
        found = match_notices(state, m, now, report, now.date())
        state.matches[m.key].summary["source"] = "import"
    else:  # sold out, or no dates yet: the fixture alone, never a "check this"
        found = fixture_only(state, m, now, report)
    _remember_page(state, m.key, m, now)
    report.imported.append(m.key)
    return found


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
