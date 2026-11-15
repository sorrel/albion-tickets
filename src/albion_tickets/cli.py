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
from .rules import decide, sold_out_text
from .run import run_check, run_import
from .ticket_page import PdfError, parse_ticket_page, pdf_text
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
@click.pass_context
def cli(ctx):
    """Reminders for Brighton & Hove Albion away and cup ticket sales."""
    # A blank line after every command's output, so the shell prompt doesn't
    # butt up against it. A close callback also runs when a command exits
    # via SystemExit (as `check` does).
    ctx.call_on_close(click.echo)


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


_KIND = {"sale": "", "predicted_sale": "expected", "sold_out_before_you": "sold out before you",
         "exchange_open": "exchange", "unreadable": "check the article", "sold_out": "sold out",
         "no_dates": "no sale dates yet", "on_sale": "on sale now"}


@cli.command()
def upcoming():
    """Tracked matches and your sale day for each."""
    state = _load()
    now = datetime.now(config.TZ)
    pts = state.points if state.points is not None else "?"
    ahead, opened = [], []
    for key, rec in state.matches.items():
        ko = rec.kickoffs[-1][0] if rec.kickoffs else None
        if ko and datetime.fromisoformat(ko) < now:
            continue
        s = rec.summary
        opens = s.get("opens")
        notes = [_KIND.get(s.get("kind", ""), s.get("kind", "").replace("_", " "))]
        if key in state.have_tickets:
            notes = ["you have tickets"]
        elif rec.sold_out_at():
            notes = [sold_out_text(rec.sold_out_at())]
        if not s.get("kickoff_confirmed", True):
            notes.append("kick-off not confirmed")
        comp = "" if not s.get("home") else _COMP.get(s.get("competition", ""), s.get("competition", ""))
        row = (opens or ko or "", [
            _fmt(opens),
            f"{s.get('opponent', key)} ({'H' if s.get('home') else 'A'})" + (f" {comp}" if comp else ""),
            _fmt(ko) + ("" if s.get("kickoff_confirmed", True) else "?"),
            ", ".join(n for n in notes if n),
        ])
        (opened if opens and datetime.fromisoformat(opens) <= now else ahead).append(row)
    title = lambda text: click.echo(click.style(text, fg="yellow", bold=True))
    title(f"Sales coming up · you have {pts} points")
    if ahead:
        click.echo("\n".join(_table([r for _, r in sorted(ahead, key=lambda r: r[0])], _UPCOMING_HEADER)))
    else:
        click.echo("None yet: the next check will pick them up when the club announces them.")
    if opened:
        click.echo()
        title("Sale already opened · match still to come")
        click.echo("\n".join(_table([r for _, r in sorted(opened, key=lambda r: r[0])], _UPCOMING_HEADER)))
    checks = [k for k in state.events if k.startswith("check:")]
    if checks:
        click.echo()
        title("Needs a look")
        for k in checks:
            click.echo(f"{k}  (albion dismiss {k})")
    click.echo()
    click.echo(f"Last checked {_fmt(state.last_check)}." if state.last_check
               else "Not checked yet: run albion check.")


_UPCOMING_HEADER = ["Your sale", "Match", "Kick-off", "Note"]


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
        _tier(rec.sold_out_at()),
    ]


_HEADER = ["Kick-off", "Match", "Comp", "Worth", "Tue / Wed / Thu", "Your sale", "Sold out at"]


def _table(rows: list[list[str]], header: list[str] = _HEADER) -> list[str]:
    widths = [max(len(r[i]) for r in [header, *rows]) for i in range(len(header))]
    fmt = lambda r: "  ".join(c.ljust(w) for c, w in zip(r, widths)).rstrip()
    rule = "─" * len(fmt(["x" * w for w in widths]))
    return [click.style(fmt(header), bold=True), rule, *(fmt(r) for r in rows)]


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


def _dim(text: str) -> str:
    return click.style(text, dim=True)


@cli.command("import")
@click.argument("files", nargs=-1, required=True,
                type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--dry-run", is_flag=True, help="Show what would change; touch nothing.")
@click.option("--progress/--quiet", "show_progress", default=None,
              help="Show a status line while it runs (default: only in a terminal).")
def import_(files, dry_run, show_progress):
    """Read ticket pages you saved as PDFs (Away Games, Home Games).

    Open the page on the ticket site in your own browser, then File → Export
    as PDF (or Print → Save as PDF). The tool itself never visits that site.
    Only away games and home cup ties are kept: the season ticket covers home
    league games.
    """
    now = datetime.now(config.TZ)
    if show_progress is None:
        show_progress = sys.stderr.isatty()
    progress = Progress(sys.stderr) if show_progress else None
    try:
        pages = []
        for i, f in enumerate(files, 1):
            if progress:
                count = f" ({i}/{len(files)})" if len(files) > 1 else ""
                progress(f"Reviewing {f.name}{count}…")
            try:
                text = pdf_text(f)
            except PdfError as exc:
                raise click.ClickException(f"{f.name}: {exc}") from exc
            result = parse_ticket_page(text, now.date(), f"From the ticket page you saved ({f.name}), "
                                                         f"imported {now:%a} {now.day} {now:%b}")
            if not result.matches:
                raise click.ClickException(f"{f.name}: no fixtures found. Is it the Away Games or Home Games page?")
            pages.append(result)
        report = run_import(make_calendar(), pages, _state_path(), now, dry_run,
                            **({"progress": progress} if progress else {}))
    finally:
        if progress:
            progress.close()
    for err in report.errors:
        click.echo(f"Error: {err}", err=True)
    if report.errors and not report.imported:
        raise SystemExit(1)

    state = _load()
    rows = []
    for page in pages:
        for m in page.matches:
            if m.key not in report.imported:
                continue
            ko = m.kickoff.isoformat() if m.kickoff else None
            outcome = decide(m, state.points, now, None) if m.stages else None
            opens = outcome.opens.isoformat() if outcome and outcome.opens else None
            if m.key in state.have_tickets:
                note = "you have tickets"
            elif outcome is None:
                sold = m.status.sold_out_to or m.status.sold_out_label_seen
                note = (sold_out_text(m.status.sold_out_to) if sold
                        else "on sale now" if m.on_sale_now else "no sale dates yet")
            elif outcome.kind == "predicted_sale":
                note = "predicted: brackets not announced"
            else:
                note = _KIND.get(outcome.kind, outcome.kind.replace("_", " "))
            rows.append((ko or "", [_fmt(opens), f"{m.opponent} ({'H' if m.home else 'A'})", _fmt(ko), note]))
    heading = "Would import" if dry_run else "Imported"
    click.echo(click.style(f"{heading} · {len(rows)} {'match' if len(rows) == 1 else 'matches'}",
                           fg="yellow", bold=True))
    if rows:
        click.echo("\n".join(_table([r for _, r in sorted(rows, key=lambda r: r[0])],
                                     _UPCOMING_HEADER)))
    if report.skipped:
        click.echo()
        click.echo(click.style("Left alone", bold=True))
        for item in report.skipped:
            what, why = item.rsplit(": ", 1) if ": " in item else (item, "")
            click.echo(f"  {what}  {_dim(why)}")
    click.echo()
    added, updated = len(report.created), len(report.updated)
    if not (added or updated or report.removed):
        click.echo("Calendar already up to date." if not dry_run else "Dry run: calendar already up to date.")
    else:
        parts = [p for p in (f"{added} added" if added else "", f"{updated} updated" if updated else "",
                             f"{len(report.removed)} removed" if report.removed else "") if p]
        click.echo(("Dry run, nothing written. Calendar would have " if dry_run else "Calendar: ")
                   + ", ".join(parts) + ".")
    if report.next_sale:
        click.echo(f"Next sale: {report.next_sale}")
    click.echo(_dim("Sale days are predicted until the club announces points brackets; "
                    "albion check takes over once it publishes the match's ticket news."))
    raise SystemExit(1 if report.errors else 0)


_REMINDERS = ("sale", "exchange", "exchange_closing", "check")


def _find_match(state, query: str) -> str:
    if query in state.matches:
        return query
    now = datetime.now(config.TZ)
    q = query.lower()
    hits = [k for k, rec in state.matches.items()
            if q in rec.summary.get("opponent", k).lower()
            and not (rec.kickoffs and datetime.fromisoformat(rec.kickoffs[-1][0]) < now)]
    if not hits:
        raise click.ClickException(f"No upcoming match matches “{query}”. See albion upcoming.")
    if len(hits) > 1:
        raise click.ClickException(f"“{query}” matches several: " + ", ".join(sorted(hits))
                                   + ". Give the full key.")
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
    name = state.matches[key].summary.get("opponent", key)
    if undo:
        state.have_tickets.discard(key)
        save(state, _state_path())
        source = state.matches[key].summary.get("source")
        again = "albion import (with the saved page)" if source == "import" else "albion check"
        click.echo(f"{name}: no longer marked as having tickets. Reminders return at the next {again}.")
        return
    state.have_tickets.add(key)
    cal = make_calendar()
    removed, failed = 0, []
    for ev_key in [k for k in state.events if k.split(":", 1)[0] in _REMINDERS and k.split(":", 1)[1] == key]:
        try:
            cal.remove(state.events[ev_key]["uid"])
        except Exception as exc:  # keep going: the next check retires what's left
            failed.append(f"{ev_key}: {exc}")
            continue
        del state.events[ev_key]
        removed += 1
    save(state, _state_path())
    click.echo(f"{name}: marked as having tickets." + (f" Removed {_count(removed, 'reminder')}." if removed else ""))
    for f in failed:
        click.echo(f"Error: calendar: {f}", err=True)
    if failed:
        raise SystemExit(1)
