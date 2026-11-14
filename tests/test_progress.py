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
    text = "\n".join(lines)
    assert lines[0].startswith("Checking the calendar")
    assert "Reading the club's ticket news" in text
    assert any(l.startswith("Found ") and "ticket articles" in l for l in lines)
    reads = [l for l in lines if l.startswith("Reading article ")]
    assert reads and reads[0].startswith("Reading article 1/")
    assert any("Fulham" in l and l.lstrip().startswith("Adding") for l in lines)


def test_dry_run_progress_says_would(tmp_path, monkeypatch):
    monkeypatch.setenv("ALBION_DATA_DIR", str(tmp_path))
    p = tmp_path / "state.json"
    save(State(points=184), p)
    lines = []
    run_check(FakeCalendar(), Fetcher(pages()), p, NOW, dry_run=True, progress=lines.append)
    assert any(l.lstrip().startswith("Would add") for l in lines)
    assert not any(l.lstrip().startswith("Adding") for l in lines)


def test_heartbeat_speaks_up_during_silence():
    out = []
    pr = Progress(out.append, quiet_after=0.05)
    try:
        pr("Reading the club's ticket news…")
        time.sleep(0.3)
    finally:
        pr.close()
    assert out[0] == "Reading the club's ticket news…"
    assert any("still" in l and "ticket news" in l for l in out[1:])


def test_heartbeat_stops_after_close():
    out = []
    pr = Progress(out.append, quiet_after=0.05)
    pr("Working…")
    pr.close()
    n = len(out)
    time.sleep(0.2)
    assert len(out) == n


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
    assert any(l.endswith("· Fulham v Albion") for l in report.created)
