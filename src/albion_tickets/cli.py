"""albion — reminders for Albion away and cup ticket sales."""
from __future__ import annotations

from datetime import date, datetime

import sys

import click

from . import config
from .calendar_app import MacCalendar
from .fetch import polite_fetcher
from .progress import Progress
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


def _count(n: int, word: str = "event") -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


@cli.command()
@click.option("--dry-run", is_flag=True, help="Show what would change; touch nothing.")
@click.option("--progress/--quiet", "show_progress", default=None,
              help="Show a status line while it runs (default: only in a terminal).")
@click.option("-v", "--verbose", is_flag=True, help="List every calendar change with its date.")
def check(dry_run, show_progress, verbose):
    """Read the club's ticket news and update the calendar."""
    now = datetime.now(config.TZ)
    if show_progress is None:
        show_progress = sys.stderr.isatty()
    progress = Progress(sys.stderr) if show_progress else None
    try:
        report = run_check(make_calendar(), make_fetcher(), _state_path(), now, dry_run,
                           **({"progress": progress} if progress else {}))
    finally:
        if progress:
            progress.close()

    added, updated, removed = len(report.created), len(report.updated), len(report.removed)
    if not (added or updated or removed):
        click.echo("Dry run: calendar already up to date." if dry_run else "Calendar up to date.")
    else:
        parts = [p for p in (f"add {added}" if added else "", f"update {updated}" if updated else "",
                             f"remove {removed}" if removed else "") if p]
        if dry_run:
            click.echo(f"Dry run: would {', '.join(parts)} {'event' if added + updated + removed == 1 else 'events'}"
                       " (nothing written).")
        else:
            done = {"add": "added", "update": "updated", "remove": "removed"}
            click.echo("Calendar: " + ", ".join(f"{done[p.split()[0]]} {p.split()[1]}" for p in parts) + ".")
    click.echo(f"Next sale: {report.next_sale}" if report.next_sale else "No sales for you coming up yet.")
    for change in report.changes:
        click.echo(f"⚠️ {change}")
    for title in report.needs_look:
        click.echo(f"Needs a look: {title}")
    if verbose:
        for label, items in [("Add", report.created), ("Update", report.updated), ("Remove", report.removed)]:
            if items:
                click.echo(f"{label}:")
                for item in items:
                    click.echo(f"  {item}")
    for err in report.errors:
        click.echo(f"Error: {err}", err=True)
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


def _stage_name(st: dict) -> str:
    if st.get("min_points") is not None:
        return f"STHs/1901 with {st['min_points']}+ points"
    return st["label"] + (" (points brackets not announced yet)" if st.get("pending") else "")


@cli.command()
def history():
    """Every tracked match: sale stages, your stage, sell-out and kick-off changes."""
    state = _load()
    recs = sorted(state.matches.values(), key=lambda r: r.kickoffs[-1][0] if r.kickoffs else "")
    blocks = []
    for rec in recs:
        s = rec.summary
        where = "home" if s.get("home") else "away"
        head = [f"{s.get('opponent', '?')} ({where})", s.get("competition", "")]
        if rec.kickoffs:
            head.append(_fmt(rec.kickoffs[-1][0]) + ("" if s.get("kickoff_confirmed", True) else " (not confirmed)"))
        if s.get("worth") is not None:
            head.append(f"worth {s['worth']} points")
        lines = [" · ".join(h for h in head if h)]
        for st in s.get("stages", []):
            mine = "  ← your stage" if st["label"] == s.get("your_stage") else ""
            lines.append(f"  {_fmt(st['opens'])}  {_stage_name(st)}{mine}")
        if s.get("sold_out_stage"):
            noticed = f" (noticed {_fmt(rec.first_sold_out_seen)})" if rec.first_sold_out_seen else ""
            lines.append(f"  Sold out at {s['sold_out_stage']}{noticed}")
        else:
            lines.append("  Sold out: not reported in the club's news")
        for (old, _), (new, seen) in zip(rec.kickoffs, rec.kickoffs[1:]):
            lines.append(f"  Kick-off moved: {_fmt(old)} → {_fmt(new)} (noticed {_fmt(seen)})")
        blocks.append("\n".join(lines))
    click.echo("\n\n".join(blocks) if blocks else "No matches tracked yet: run albion check.")


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
