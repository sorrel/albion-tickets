"""albion — reminders for Albion away and cup ticket sales.

Commands only: the work is in run (check), importing (import), upcoming and
history. make_calendar, make_fetcher, pdf_text and _today are looked up here
at call time so tests can swap them.
"""
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path

import click

from . import config
from .calendar_app import MacCalendar
from .calendar_app import remove as remove_event
from .display import dim, table, title, when
from .export import export as export_history
from .fetch import polite_fetcher
from .history import render as render_history
from .importing import run_import
from .model import Match, short_name
from .progress import Progress
from .records import season_ticket
from .rules import decide, sold_out_text
from .run import run_check
from .store import State, StateError, load, save
from .sync import Report, silent
from .ticket_page import PageResult, PdfError, parse_ticket_page, pdf_text
from .upcoming import render as render_upcoming


def make_calendar():
    return MacCalendar(config.CALENDAR_NAME)


def make_fetcher():
    return polite_fetcher()


def _today() -> date:
    return datetime.now(config.TZ).date()


def _state_path() -> Path:
    return config.data_dir() / "state.json"


def _load() -> State:
    try:
        return load(_state_path())
    except StateError as exc:
        raise click.ClickException(str(exc)) from exc


def _plural(n: int, word: str, many: str | None = None) -> str:
    return f"{n} {word if n == 1 else many or word + 's'}"


@contextmanager
def _progress(show: bool | None) -> Iterator:
    """A status line on stderr (by default only in a terminal), cleared afterwards."""
    if not (sys.stderr.isatty() if show is None else show):
        yield silent
        return
    line = Progress(sys.stderr)
    try:
        yield line
    finally:
        line.close()


def _calendar_line(report: Report, dry_run: bool) -> str:
    """'Calendar: added 2, updated 1.' or 'Dry run: would add 2, update 1 events (nothing written).'"""
    done = [(n, verb, past) for n, verb, past in ((len(report.created), "add", "added"),
                                                  (len(report.updated), "update", "updated"),
                                                  (len(report.removed), "remove", "removed")) if n]
    if not done:
        return "Dry run: calendar already up to date." if dry_run else "Calendar up to date."
    if dry_run:
        total = sum(n for n, _, _ in done)
        return (f"Dry run: would {', '.join(f'{verb} {n}' for n, verb, _ in done)} "
                f"{'event' if total == 1 else 'events'} (nothing written).")
    return "Calendar: " + ", ".join(f"{past} {n}" for n, _, past in done) + "."


def _errors(report: Report) -> None:
    for err in report.errors:
        click.echo(f"Error: {err}", err=True)


_dry_run = click.option("--dry-run", is_flag=True, help="Show what would change; touch nothing.")
_show_progress = click.option("--progress/--quiet", "show_progress", default=None,
                              help="Show a status line while it runs (default: only in a terminal).")


@click.group()
@click.pass_context
def cli(ctx):
    """Reminders for Brighton & Hove Albion away and cup ticket sales."""
    # A blank line after every command's output, so the shell prompt doesn't
    # butt up against it. A close callback also runs when a command exits
    # via SystemExit (as `check` does).
    ctx.call_on_close(click.echo)


@cli.command()
@_dry_run
@_show_progress
@click.option("-v", "--verbose", is_flag=True, help="List every calendar change with its date.")
def check(dry_run, show_progress, verbose):
    """Read the club's ticket news and update the calendar."""
    with _progress(show_progress) as progress:
        report = run_check(make_calendar(), make_fetcher(), _state_path(), datetime.now(config.TZ), dry_run,
                           progress)
    click.echo(_calendar_line(report, dry_run))
    click.echo(f"Next sale: {report.next_sale}" if report.next_sale else "No sales for you coming up yet.")
    for change in report.changes:
        click.echo(f"⚠️ {change}")
    for what in report.needs_look:
        click.echo(f"Needs a look: {what}")
    if verbose:
        for label, items in (("Add", report.created), ("Update", report.updated), ("Remove", report.removed)):
            if items:
                click.echo("\n".join([f"{label}:", *(f"  {item}" for item in items)]))
    if not dry_run and (state := _load()).export_dir:
        try:
            export_history(state, config.data_dir(), Path(state.export_dir))
        except OSError as exc:
            report.errors.append(f"export to {state.export_dir}: {exc}")
    _errors(report)
    raise SystemExit(1 if report.errors else 0)


@cli.command()
@click.argument("n", type=click.IntRange(0, 2000))
def points(n):
    """Set your loyalty points total."""
    state = _load()
    state.points = n
    save(state, _state_path())
    click.echo(f"Points set to {n}.")


@cli.command()
def upcoming():
    """Matches to come: tickets you have, sales to come, and what has sold out."""
    click.echo(render_upcoming(_load(), datetime.now(config.TZ)))


@cli.command()
@click.option("--season", help="Season to show, e.g. 2025-26 (default: this season).")
@click.option("--all", "show_all", is_flag=True, help="Show every season recorded.")
@click.option("-v", "--verbose", is_flag=True, help="Also list every sale stage for each match.")
def history(season, show_all, verbose):
    """Tracked matches by season: kick-off, worth, points brackets, your sale, sell-out."""
    click.echo(render_history(_load(), season, show_all, verbose, _today()))


@cli.command()
@click.argument("key")
def dismiss(key):
    """Stop a 'check this' reminder (keys are shown by `albion upcoming`)."""
    state = _load()
    if not key.startswith("check:") or key not in state.events:
        raise click.ClickException(f"No such 'check this' reminder: {key}")
    state.dismissed.add(key)
    save(state, _state_path())
    click.echo(f"Dismissed {key}. It goes from the calendar at the next check.")


@cli.command()
@click.argument("folder", required=False, type=click.Path(file_okay=False, path_type=Path))
def export(folder):
    """Copy your history to FOLDER (remembered, and refreshed after every check)."""
    state = _load()
    if folder is not None:
        state.export_dir = str(folder.expanduser().resolve())
        save(state, _state_path())
    elif not state.export_dir:
        raise click.ClickException("No export folder yet: run albion export <folder> once.")
    out = export_history(state, config.data_dir(), Path(state.export_dir))
    click.echo(f"History copied to {out}. It will be refreshed after every check.")


@cli.command()
@click.argument("url")
def add(url):
    """Track a ticket article the news listing no longer shows."""
    prefix = config.BASE_URL + "/media-article/"
    if not url.startswith(prefix):
        raise click.ClickException(f"Only club news articles are accepted ({prefix}…)")
    state = _load()
    state.articles.setdefault(url, {"title": url.removeprefix(prefix), "published": _today().isoformat(),
                                    "matches": []})
    save(state, _state_path())
    click.echo("Added. It will be read at the next check.")


# --- import ------------------------------------------------------------------

_NOTE = {"sale": "", "predicted_sale": "predicted: brackets not announced",  # outcome kind → the table's note
         "sold_out_before_you": "sold out before you", "exchange_open": "exchange", "unreadable": "check the article"}


@cli.command("import")
@click.argument("files", nargs=-1, required=True, type=click.Path(exists=True, dir_okay=False, path_type=Path))
@_dry_run
@_show_progress
def import_(files, dry_run, show_progress):
    """Read ticket pages you saved as PDFs (Away Games, Home Games).

    Open the page on the ticket site in your own browser, then File → Export
    as PDF (or Print → Save as PDF). The tool itself never visits that site.
    Away games and home cup ties get sale reminders; home league games (the
    season ticket covers them) only their fixture.
    """
    now = datetime.now(config.TZ)
    with _progress(show_progress) as progress:
        pages = [_read_page(f, i, len(files), now, progress) for i, f in enumerate(files, 1)]
        report = run_import(make_calendar(), pages, _state_path(), now, dry_run, progress)
    _errors(report)
    if report.errors and not report.imported:
        raise SystemExit(1)

    state = _load()
    imported = sorted((m for page in pages for m in page.matches if m.key in report.imported),
                      key=lambda m: m.kickoff.isoformat() if m.kickoff else "")
    click.echo(title(f"{'Would import' if dry_run else 'Imported'} · {_plural(len(imported), 'match', 'matches')}"))
    if imported:
        click.echo(table([_imported_row(m, state, now) for m in imported], ["Your sale", "Match", "Kick-off", "Note"]))
    if report.skipped:
        click.echo("\n" + click.style("Left alone", bold=True))
        for item in report.skipped:
            what, _, why = item.rpartition(": ") if ": " in item else (item, "", "")
            click.echo(f"  {what}  {dim(why)}")
    click.echo("\n" + _calendar_line(report, dry_run))
    if report.next_sale:
        click.echo(f"Next sale: {report.next_sale}")
    click.echo(dim("Sale days are predicted until the club announces points brackets; "
                   "albion check takes over once it publishes the match's ticket news."))
    raise SystemExit(1 if report.errors else 0)


def _read_page(f: Path, i: int, of: int, now: datetime, progress) -> PageResult:
    progress(f"Reviewing {f.name}" + (f" ({i}/{of})" if of > 1 else "") + "…")
    try:
        text = pdf_text(f)
    except PdfError as exc:
        raise click.ClickException(f"{f.name}: {exc}") from exc
    page = parse_ticket_page(text, now.date(), f"From the ticket page you saved ({f.name}), "
                                               f"imported {now:%a} {now.day} {now:%b}")
    if not page.matches:
        raise click.ClickException(f"{f.name}: no fixtures found. Is it the Away Games or Home Games page?")
    return page


def _imported_row(m: Match, state: State, now: datetime) -> list[str]:
    """Your sale, match, kick-off, and a note on where it stands."""
    outcome = decide(m, state.points, now, None) if m.stages and not season_ticket(m) else None
    if season_ticket(m):
        note = "season ticket"
    elif m.key in state.have_tickets:
        note = "you have tickets"
    elif outcome is not None:
        note = _NOTE.get(outcome.kind, outcome.kind.replace("_", " "))
    elif m.status.sold:
        note = sold_out_text(m.status.sold_out_to)
    else:
        note = "on sale now" if m.on_sale_now else "no sale dates yet"
    return [when(outcome.opens if outcome else None), short_name(m.opponent, m.home), when(m.kickoff), note]


# --- got ---------------------------------------------------------------------

_REMINDERS = ("sale", "exchange", "exchange_closing", "check")  # what `got` takes out of the calendar


def _find_match(state: State, query: str) -> str:
    """A match key, or the one upcoming match whose opponent contains `query`."""
    if query in state.matches:
        return query
    now = datetime.now(config.TZ)
    hits = [k for k, rec in state.matches.items()
            if query.lower() in rec.summary.get("opponent", k).lower() and not (rec.kickoff and rec.kickoff < now)]
    if not hits:
        raise click.ClickException(f"No upcoming match matches “{query}”. See albion upcoming.")
    if len(hits) > 1:
        raise click.ClickException(f"“{query}” matches several: {', '.join(sorted(hits))}. Give the full key.")
    return hits[0]


@cli.command()
@click.argument("match")
@click.option("--undo", is_flag=True, help="You no longer have tickets: bring the reminders back.")
def got(match, undo):
    """Record that you already have tickets for MATCH (an opponent's name, or a key).

    Its sale and exchange reminders go from the calendar; the fixture stays.
    """
    state = _load()
    key = _find_match(state, match)
    rec = state.matches[key]
    if undo:
        state.have_tickets.discard(key)
        save(state, _state_path())
        again = "albion import (with the saved page)" if rec.summary.get("source") == "import" else "albion check"
        click.echo(f"{rec.opponent}: no longer marked as having tickets. Reminders return at the next {again}.")
        return
    state.have_tickets.add(key)
    cal = make_calendar()
    removed, failed = 0, []
    for ev_key in [k for k in state.events if k.split(":", 1)[0] in _REMINDERS and k.split(":", 1)[1] == key]:
        try:
            remove_event(cal, state.events[ev_key]["uid"])
        except Exception as exc:  # keep going: the next check retires what's left
            failed.append(f"{ev_key}: {exc}")
            continue
        del state.events[ev_key]
        removed += 1
    save(state, _state_path())
    click.echo(f"{rec.opponent}: marked as having tickets."
               + (f" Removed {_plural(removed, 'reminder')}." if removed else ""))
    for f in failed:
        click.echo(f"Error: calendar: {f}", err=True)
    if failed:
        raise SystemExit(1)
