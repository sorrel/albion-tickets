import io
import re
import time

from click.testing import CliRunner

from albion_tickets import cli as cli_mod
from albion_tickets.calendar_app import FakeCalendar
from albion_tickets.progress import Progress
from albion_tickets.run import run_check
from albion_tickets.store import save, State

from tests.test_run import NOW, Fetcher, pages


def test_run_check_reports_each_slow_step(tmp_path, monkeypatch):
    monkeypatch.setenv("ALBION_DATA_DIR", str(tmp_path))
    p = tmp_path / "state.json"
    save(State(points=184), p)
    lines = []
    run_check(FakeCalendar(), Fetcher(pages()), p, NOW, dry_run=False, progress=lines.append)
    assert lines[0].startswith("Checking the calendar")
    assert "Reading the club's ticket news…" in lines
    reads = [l for l in lines if l.startswith("Reading article ")]
    assert reads and reads[0].startswith("Reading article 1/")
    assert any(l.startswith("Updating the calendar 1/") for l in lines)
    assert not any("Would add" in l or "Adding" in l for l in lines)  # status only, no event list


def test_status_line_overwrites_itself():
    out = io.StringIO()
    pr = Progress(out, quiet_after=60, width=200)
    pr("Reading the club's ticket news…")
    pr("Reading article 1/5…")
    pr.close()
    text = out.getvalue()
    assert "\n" not in text
    assert text.count("\r\x1b[K") == 3  # two updates, then cleared
    assert text.endswith("\r\x1b[K")


def test_status_line_is_cut_to_the_terminal_width():
    out = io.StringIO()
    pr = Progress(out, quiet_after=60, width=20)
    pr("Reading article 1/5: a very long article title indeed…")
    pr.close()
    shown = out.getvalue().split("\r\x1b[K")[1]
    assert len(shown) <= 19 and shown.endswith("…")


def test_heartbeat_ticks_the_seconds_on_the_same_line():
    out = io.StringIO()
    pr = Progress(out, quiet_after=0.05, tick=0.05, width=200)
    try:
        pr("Reading the club's ticket news…")
        time.sleep(0.3)
    finally:
        pr.close()
    text = out.getvalue()
    assert "\n" not in text
    assert re.search(r"Reading the club's ticket news… \(\d+s\)", text)


def test_heartbeat_stops_after_close():
    out = io.StringIO()
    pr = Progress(out, quiet_after=0.05, tick=0.05, width=200)
    pr("Working…")
    pr.close()
    n = len(out.getvalue())
    time.sleep(0.2)
    assert len(out.getvalue()) == n


def test_cli_check_progress_flag_prints_steps(tmp_path, monkeypatch):
    monkeypatch.setenv("ALBION_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(cli_mod, "make_calendar", FakeCalendar)
    monkeypatch.setattr(cli_mod, "make_fetcher", lambda: Fetcher(pages()))
    save(State(points=184), tmp_path / "state.json")
    r = CliRunner().invoke(cli_mod.cli, ["check", "--dry-run", "--progress"])
    assert "Reading article 1/" in r.stderr
    assert "Reading article" not in r.stdout


def test_cli_check_quiet_by_default_when_not_a_terminal(tmp_path, monkeypatch):
    monkeypatch.setenv("ALBION_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(cli_mod, "make_calendar", FakeCalendar)
    monkeypatch.setattr(cli_mod, "make_fetcher", lambda: Fetcher(pages()))
    save(State(points=184), tmp_path / "state.json")
    r = CliRunner().invoke(cli_mod.cli, ["check", "--dry-run"])
    assert "Reading article" not in r.stderr


def test_report_lines_lead_with_the_event_date(tmp_path, monkeypatch):
    import re
    monkeypatch.setenv("ALBION_DATA_DIR", str(tmp_path))
    p = tmp_path / "state.json"
    save(State(points=184), p)
    report = run_check(FakeCalendar(), Fetcher(pages()), p, NOW, dry_run=True)
    assert report.created
    for line in report.created:
        assert re.match(r"^(Mon|Tue|Wed|Thu|Fri|Sat|Sun) \d{1,2} [A-Z][a-z]{2} \d{2}:\d{2} · ", line), line
    assert any(l.endswith("· ⚽ Fulham v Albion") for l in report.created)


def _cli(tmp_path, monkeypatch, *args):
    monkeypatch.setenv("ALBION_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(cli_mod, "make_calendar", FakeCalendar)
    monkeypatch.setattr(cli_mod, "make_fetcher", lambda: Fetcher(pages()))
    save(State(points=184), tmp_path / "state.json")
    return CliRunner().invoke(cli_mod.cli, ["check", *args])


def test_check_summary_is_a_few_lines(tmp_path, monkeypatch):
    r = _cli(tmp_path, monkeypatch, "--dry-run")
    out = r.stdout.splitlines()
    assert out[0].startswith("Dry run: would add ") and "nothing written" in out[0]
    assert out[1] == "No sales for you coming up yet."
    assert len(out) <= 4
    assert "manchester-united-ticket-information" in r.stderr  # a 404 in this fixture set: errors go to stderr
    assert "Created" not in r.stdout and "Fulham v Albion" not in r.stdout


def test_check_verbose_lists_every_event_with_its_date(tmp_path, monkeypatch):
    r = _cli(tmp_path, monkeypatch, "--dry-run", "--verbose")
    assert re.search(r"^  \w{3} 26 Dec 15:00 · ⚽ Fulham v Albion$", r.stdout, re.M)


def test_cli_import_progress_flag_reviews_each_file(tmp_path, monkeypatch):
    from pathlib import Path
    monkeypatch.setenv("ALBION_DATA_DIR", str(tmp_path))
    save(State(points=184), tmp_path / "state.json")
    monkeypatch.setattr(cli_mod, "make_calendar", FakeCalendar)
    away = (Path(__file__).parent / "fixtures" / "ticket-page-away.txt").read_text()
    monkeypatch.setattr(cli_mod, "pdf_text", lambda path: away)
    pdfs = [tmp_path / "Away.pdf", tmp_path / "Home.pdf"]
    for p in pdfs:
        p.write_bytes(b"%PDF")
    r = CliRunner().invoke(cli_mod.cli, ["import", "--dry-run", "--progress", *map(str, pdfs)])
    assert r.exit_code == 0, r.output
    assert "Reviewing Away.pdf (1/2)…" in r.stderr
    assert "Reviewing Home.pdf (2/2)…" in r.stderr
    assert "Reviewing" not in r.stdout
