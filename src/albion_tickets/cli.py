"""albion — reminders for Albion away and cup ticket sales."""
from __future__ import annotations

from datetime import date, datetime

import click

from . import config
from .calendar_app import MacCalendar
from .fetch import polite_fetcher
from .run import run_check
from .store import StateError, load, save


def make_calendar():
    return MacCalendar(config.CALENDAR_NAME)


def make_fetcher():
    return polite_fetcher()


def _state_path():
    return config.data_dir() / "state.json"


def _load():
    try:
        return load(_state_path())
    except StateError as exc:
        raise click.ClickException(str(exc)) from exc


def _fmt(iso: str | None) -> str:
    if not iso:
        return "—"
    dt = datetime.fromisoformat(iso)
    return f"{dt:%a} {dt.day} {dt:%b %H:%M}"


@click.group()
def cli():
    """Reminders for Brighton & Hove Albion away and cup ticket sales."""


@cli.command()
@click.option("--dry-run", is_flag=True, help="Show what would change; touch nothing.")
def check(dry_run):
    """Read the club's ticket news and update the calendar."""
    now = datetime.now(config.TZ)
    report = run_check(make_calendar(), make_fetcher(), _state_path(), now, dry_run)
    if dry_run:
        click.echo("Dry run: nothing written.")
    for label, items in [("Created", report.created), ("Updated", report.updated),
                         ("Removed", report.removed), ("Changes", report.changes)]:
        for item in items:
            click.echo(f"{label}: {item}")
    for err in report.errors:
        click.echo(f"Error: {err}", err=False)
    if not any([report.created, report.updated, report.removed, report.changes, report.errors]):
        click.echo("Nothing new.")
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
    """Tracked matches and your sale day for each."""
    state = _load()
    click.echo(f"You have {state.points if state.points is not None else '?'} points.")
    now = datetime.now(config.TZ)
    rows = []
    for key, rec in state.matches.items():
        ko = rec.kickoffs[-1][0] if rec.kickoffs else None
        if ko and datetime.fromisoformat(ko) < now:
            continue
        s = rec.summary
        where = "away" if not s.get("home") else s.get("competition", "")
        rows.append((s.get("opens") or ko or "", f"{s.get('opponent', key)} ({where})", ko, s))
    for _, name, ko, s in sorted(rows, key=lambda r: r[0]):
        confirmed = "" if s.get("kickoff_confirmed", True) else " (not confirmed)"
        click.echo(f"{name}: kick-off {_fmt(ko)}{confirmed}; {s.get('kind', '?').replace('_', ' ')} "
                   f"{_fmt(s.get('opens'))}" + (f"; sold out at {s['sold_out_stage']}" if s.get("sold_out_stage") else ""))
    checks = [k for k in state.events if k.startswith("check:")]
    for k in checks:
        click.echo(f"Needs a look: {k}  (albion dismiss {k})")


@cli.command()
def history():
    """Kick-off changes and sell-outs, match by match."""
    state = _load()
    for key, rec in state.matches.items():
        s = rec.summary
        click.echo(f"{s.get('opponent', key)} ({'home' if s.get('home') else 'away'}, {s.get('competition', '')})")
        for ko, seen in rec.kickoffs:
            click.echo(f"  kick-off {_fmt(ko)}  (seen {_fmt(seen)})")
        if s.get("sold_out_stage"):
            click.echo(f"  sold out at {s['sold_out_stage']}")


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
@click.argument("url")
def add(url):
    """Track a ticket article the news listing no longer shows."""
    prefix = config.BASE_URL + "/media-article/"
    if not url.startswith(prefix):
        raise click.ClickException(f"Only club news articles are accepted ({prefix}…)")
    state = _load()
    state.articles.setdefault(url, {"title": url[len(prefix):], "published": date.today().isoformat(),
                                    "matches": []})
    save(state, _state_path())
    click.echo("Added. It will be read at the next check.")
