"""albion — reminders for Albion away and cup ticket sales."""
from __future__ import annotations

from datetime import date, datetime

import sys
from pathlib import Path

import click

from . import config
from .calendar_app import MacCalendar
from .export import export as export_history
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
    if not dry_run:
        state = _load()
        if state.export_dir:
            try:
                export_history(state, config.data_dir(), Path(state.export_dir))
            except OSError as exc:
                report.errors.append(f"export to {state.export_dir}: {exc}")
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


_COMP = {"Premier League": "PL", "FA Cup": "FA Cup", "League Cup": "League Cup",
         "UEFA Europa League": "Europa", "UEFA Conference League": "Conference",
         "UEFA Champions League": "Champions"}


def _today() -> date:
    return datetime.now(config.TZ).date()


def _season_of(d: date) -> str:
    start = d.year if d.month >= 8 else d.year - 1
    return f"{start}-{(start + 1) % 100:02d}"


def _season_label(season: str) -> str:
    return season.replace("-", "–")


def _day(iso: str | None) -> str:
    if not iso:
        return "—"
    dt = datetime.fromisoformat(iso).astimezone(config.TZ)
    return f"{dt:%a} {dt.day} {dt:%b}"


def _tier(label: str | None) -> str:
    import re
    if not label:
        return "—"
    m = re.search(r"(\d+)\s*\+", label)
    if m:
        return f"{m.group(1)}+"
    if "myalbion" in label.lower():
        return "MyAlbion+"
    if re.search(r"STH|1901", label, re.I):
        return "All STHs"
    return label


def _row(rec) -> list[str]:
    s = rec.summary
    stages = s.get("stages", [])
    brackets = [st for st in sorted(stages, key=lambda st: st["opens"]) if st.get("min_points") is not None]
    if brackets:
        thresholds = " / ".join(f"{st['min_points']}+" for st in brackets[:3])
    elif any(st.get("pending") for st in stages):
        thresholds = "not announced"
    else:
        thresholds = "—"
    yours = next((st for st in stages if st["label"] == s.get("your_stage")), None)
    ko = rec.kickoffs[-1][0] if rec.kickoffs else None
    return [
        _fmt(ko) + ("" if s.get("kickoff_confirmed", True) else "?"),
        f"{s.get('opponent', '?')} ({'H' if s.get('home') else 'A'})",
        _COMP.get(s.get("competition", ""), s.get("competition", "")),
        str(s["worth"]) if s.get("worth") is not None else "—",
        thresholds,
        _day(yours["opens"]) if yours else "—",
        _tier(s.get("sold_out_stage")),
    ]


_HEADER = ["Kick-off", "Match", "Comp", "Worth", "Tue / Wed / Thu", "Your sale", "Sold out at"]


def _table(rows: list[list[str]]) -> list[str]:
    widths = [max(len(r[i]) for r in [_HEADER, *rows]) for i in range(len(_HEADER))]
    fmt = lambda r: "  ".join(c.ljust(w) for c, w in zip(r, widths)).rstrip()
    rule = "─" * len(fmt(["x" * w for w in widths]))
    return [click.style(fmt(_HEADER), bold=True), rule, *(fmt(r) for r in rows)]


def _detail(rec) -> list[str]:
    s = rec.summary
    lines = [click.style(f"{s.get('opponent', '?')} ({'home' if s.get('home') else 'away'})", bold=True)]
    for st in s.get("stages", []):
        mine = "  ← your stage" if st["label"] == s.get("your_stage") else ""
        lines.append(f"  {_fmt(st['opens'])}  {_stage_name(st)}{mine}")
    return lines


@cli.command()
@click.option("--season", help="Season to show, e.g. 2025-26 (default: this season).")
@click.option("--all", "show_all", is_flag=True, help="Show every season recorded.")
@click.option("-v", "--verbose", is_flag=True, help="Also list every sale stage for each match.")
def history(season, show_all, verbose):
    """Tracked matches by season: kick-off, worth, points brackets, your sale, sell-out."""
    state = _load()
    by_season: dict[str, list] = {}
    for key, rec in state.matches.items():
        by_season.setdefault(key[:7], []).append(rec)
    if show_all:
        seasons = sorted(by_season)
    else:
        wanted = season or _season_of(_today())
        if wanted not in by_season and not season and by_season:
            wanted = max(by_season)  # nothing yet this season: show the latest there is
        seasons = [wanted]
    if not by_season:
        click.echo("No matches tracked yet: run albion check.")
        return
    out: list[str] = []
    for sn in seasons:
        recs = sorted(by_season.get(sn, []), key=lambda r: r.kickoffs[-1][0] if r.kickoffs else "")
        if out:
            out.append("")
        if not recs:
            out.append(f"No matches recorded for {_season_label(sn)}.")
            continue
        current = sn == _season_of(_today())
        pts = f" · you have {state.points} points" if current and state.points is not None else ""
        out.append(click.style(f"{_season_label(sn)} season{pts}", fg="yellow", bold=True))
        out.extend(_table([_row(r) for r in recs]))
        moves = [f"{r.summary.get('opponent', '?')} kick-off moved: {_fmt(old)} → {_fmt(new)} (noticed {_fmt(seen)})"
                 for r in recs for (old, _), (new, seen) in zip(r.kickoffs, r.kickoffs[1:])]
        if moves:
            out.append("")
            out.append(click.style("Kick-off changes", fg="yellow", bold=True))
            out.extend(moves)
        if verbose:
            for r in recs:
                out.append("")
                out.extend(_detail(r))
    click.echo("\n".join(out))


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
    if folder is None:
        if not state.export_dir:
            raise click.ClickException("No export folder yet: run albion export <folder> once.")
        folder = Path(state.export_dir)
    else:
        folder = folder.expanduser().resolve()
        state.export_dir = str(folder)
        save(state, _state_path())
    out = export_history(state, config.data_dir(), folder)
    click.echo(f"History copied to {out}. It will be refreshed after every check.")


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
