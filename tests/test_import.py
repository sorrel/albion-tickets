"""albion import (ticket pages saved as PDFs) and albion got (tickets in hand)."""
from datetime import date, datetime
from pathlib import Path

import pytest
from click.testing import CliRunner

from albion_tickets import cli as cli_mod
from albion_tickets import ticket_page
from albion_tickets.calendar_app import FakeCalendar
from albion_tickets.config import TZ
from albion_tickets.run import run_check, run_import
from albion_tickets.store import State, load, save
from albion_tickets.ticket_page import parse_ticket_page

from .test_run import Fetcher, pages

FIX = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 11, 13, 20, 0, tzinfo=TZ)
AWAY = (FIX / "ticket-page-away.txt").read_text()


def away(today=date(2026, 11, 13)):
    return parse_ticket_page(AWAY, today, "saved page")


@pytest.fixture
def state_path(tmp_path, monkeypatch):
    monkeypatch.setenv("ALBION_DATA_DIR", str(tmp_path))
    p = tmp_path / "state.json"
    save(State(points=184), p)
    return p


# --- parsing --------------------------------------------------------------

def test_parses_every_fixture_and_sets_the_fan_event_aside():
    r = away()
    assert len(r.matches) == 15
    assert r.skipped == ["Sat 5 Dec: Pre-match fans' event in Nottingham Forest"]


def test_short_names_become_the_articles_names():
    names = {m.opponent for m in away().matches}
    assert {"Tottenham Hotspur", "Nottingham Forest", "Manchester United", "Newcastle United"} <= names
    assert not names & {"Spurs", "Nott'm Forest", "Man Utd"}


def test_years_kickoffs_and_pending_brackets():
    m = next(m for m in away().matches if m.opponent == "Brentford")
    assert m.key == "2026-27-brentford-a-premier-league"
    assert m.kickoff == datetime(2027, 1, 16, 15, 0, tzinfo=TZ)
    sth, members = m.stages
    assert (sth.audience, sth.brackets_pending, sth.opens) == ("sth", True, datetime(2026, 12, 1, 9, 0, tzinfo=TZ))
    assert (members.audience, members.opens.date()) == ("myalbion", date(2026, 12, 8))


def test_competition_and_sell_out():
    m = next(m for m in away().matches if m.opponent == "Panathinaikos")
    assert m.competition == "UEFA Conference League"
    assert m.stages == []
    assert m.status.sold_out_to.startswith("All STHs")


def test_home_page_keeps_cup_ties_only(state_path):
    text = ("Home Games\nSat 9 Jan Sat 9 Jan\n3:00 PM\nAlbion v Leeds Albion v Leeds\nEmirates FA Cup\n"
            "On Sale Dates:\nSTHs/1901 Club Members: Tue 15 Dec, 9am\n"
            "Sat 16 Jan\n3:00 PM\nAlbion v Wolves\nPremier League\n")
    r = parse_ticket_page(text, date(2026, 11, 13), "saved page")
    assert [(m.opponent, m.home, m.competition) for m in r.matches] == [
        ("Leeds United", True, "FA Cup"), ("Wolverhampton Wanderers", True, "Premier League")]
    report = run_import(FakeCalendar(), [r], state_path, NOW, dry_run=False)
    assert report.imported == ["2026-27-leeds-united-h-fa-cup"]


def test_pdf_text_passes_the_path_as_an_argument(monkeypatch, tmp_path):
    seen = {}

    def fake_run(cmd, **kw):
        seen["cmd"] = cmd
        return type("Done", (), {"returncode": 0, "stdout": "text", "stderr": ""})()

    monkeypatch.setattr(ticket_page.subprocess, "run", fake_run)
    path = tmp_path / "a & b: c.pdf"
    assert ticket_page.pdf_text(path) == "text"
    assert seen["cmd"][-1] == str(path)


# --- importing ------------------------------------------------------------

def test_import_adds_sale_and_fixture_events(state_path):
    cal = FakeCalendar()
    report = run_import(cal, [away()], state_path, NOW, dry_run=False)
    keys = {n.key for n in cal.events.values()}
    assert "sale:2026-27-brentford-a-premier-league" in keys
    assert "fixture:2026-27-brentford-a-premier-league" in keys
    assert "fixture:2026-27-panathinaikos-a-uefa-conference-league" in keys
    assert not any(k.startswith("check:") for k in keys)  # sold out with no dates: never "check this"
    brentford = next(n for n in cal.events.values() if n.key == "sale:2026-27-brentford-a-premier-league")
    assert brentford.start == datetime(2026, 12, 4, 9, 0, tzinfo=TZ)  # predicted Friday
    assert "saved page" in brentford.notes
    assert report.next_sale.startswith("🎟️ Brentford")
    assert load(state_path).matches["2026-27-brentford-a-premier-league"].summary["source"] == "import"


def test_import_twice_changes_nothing(state_path):
    cal = FakeCalendar()
    run_import(cal, [away()], state_path, NOW, dry_run=False)
    again = run_import(cal, [away()], state_path, NOW, dry_run=False)
    assert (again.created, again.updated, again.removed) == ([], [], [])


def test_dry_run_writes_nothing(state_path):
    cal = FakeCalendar()
    report = run_import(cal, [away()], state_path, NOW, dry_run=True)
    assert report.created and cal.calls == []
    assert load(state_path).matches == {}


def test_import_never_overrides_the_clubs_news(state_path):
    cal = FakeCalendar()
    run_check(cal, Fetcher(pages()), state_path, NOW, dry_run=False)
    before = load(state_path).matches["2026-27-tottenham-hotspur-a-premier-league"].summary
    report = run_import(cal, [away()], state_path, NOW, dry_run=False)
    assert ("Tottenham Hotspur (A): already tracked from the club's news; "
            "the page says sold out at 239+ points (STHs/1901)") in report.skipped
    spurs = load(state_path).matches["2026-27-tottenham-hotspur-a-premier-league"]
    assert spurs.summary == before
    assert spurs.page_sold_out["label"] == "STHs/1901 Club Members w/ 239+ Points"


def test_page_sell_out_survives_the_next_check_and_reaches_history(state_path, monkeypatch):
    cal = FakeCalendar()
    run_check(cal, Fetcher(pages()), state_path, NOW, dry_run=False)
    run_import(cal, [away()], state_path, NOW, dry_run=False)
    run_check(cal, Fetcher(pages()), state_path, NOW, dry_run=False)
    spurs = load(state_path).matches["2026-27-tottenham-hotspur-a-premier-league"]
    assert spurs.sold_out_at() == "STHs/1901 Club Members w/ 239+ Points"
    monkeypatch.setattr(cli_mod, "_today", lambda: date(2026, 11, 13))
    out = CliRunner().invoke(cli_mod.cli, ["history"]).output
    assert next(l for l in out.splitlines() if "Tottenham" in l).rstrip().endswith("239+")


def test_sold_out_text_names_level_and_points():
    from albion_tickets.rules import sold_out_text
    assert sold_out_text("STHs/1901 Club Members w/ 225+ Points:") == "sold out at 225+ points (STHs/1901)"
    assert sold_out_text("All MyAlbion+ Members") == "sold out to all MyAlbion+ members"
    assert sold_out_text("all STHs/1901 Club Members") == "sold out to all STHs/1901 members"
    assert sold_out_text("STHs/1901 Members, MyAlbion+ Members, and supporters with previous purchase history") \
        == "sold out to supporters with purchase history"


def test_article_takes_over_an_import_under_another_name(state_path, monkeypatch):
    monkeypatch.setattr(ticket_page, "ALIASES", {})  # imported as "Spurs"
    cal = FakeCalendar()
    run_import(cal, [away()], state_path, NOW, dry_run=False)
    assert "2026-27-spurs-a-premier-league" in load(state_path).matches
    run_check(cal, Fetcher(pages()), state_path, NOW, dry_run=False)
    state = load(state_path)
    assert "2026-27-spurs-a-premier-league" not in state.matches
    assert "source" not in state.matches["2026-27-tottenham-hotspur-a-premier-league"].summary
    fixtures = [n.title for n in cal.events.values() if n.key.startswith("fixture:")]
    assert fixtures.count("⚽ Tottenham Hotspur v Albion") == 1
    assert "⚽ Spurs v Albion" not in fixtures


def test_checks_leave_imported_events_alone(state_path):
    cal = FakeCalendar()
    run_import(cal, [away()], state_path, NOW, dry_run=False)
    report = run_check(cal, Fetcher(pages()), state_path, NOW, dry_run=False)
    assert not any("Brentford" in r for r in report.removed)
    assert any(n.key == "sale:2026-27-brentford-a-premier-league" for n in cal.events.values())


def test_tickets_in_hand_drop_sale_reminders_but_keep_the_fixture(state_path):
    s = load(state_path)
    s.have_tickets.add("2026-27-brentford-a-premier-league")
    save(s, state_path)
    cal = FakeCalendar()
    run_import(cal, [away()], state_path, NOW, dry_run=False)
    keys = {n.key for n in cal.events.values()}
    assert "sale:2026-27-brentford-a-premier-league" not in keys
    assert "fixture:2026-27-brentford-a-premier-league" in keys


def test_tickets_in_hand_also_apply_to_the_clubs_news(state_path):
    s = load(state_path)
    s.have_tickets.add("2026-27-fulham-a-premier-league")
    save(s, state_path)
    cal = FakeCalendar()
    run_check(cal, Fetcher(pages()), state_path, NOW, dry_run=False)
    keys = {n.key for n in cal.events.values()}
    assert not any(k.endswith(":2026-27-fulham-a-premier-league") and not k.startswith("fixture:") for k in keys)
    assert "fixture:2026-27-fulham-a-premier-league" in keys


def test_have_tickets_survives_a_save(tmp_path):
    p = tmp_path / "state.json"
    save(State(points=1, have_tickets={"k"}), p)
    assert load(p).have_tickets == {"k"}


# --- CLI ------------------------------------------------------------------

@pytest.fixture
def env(state_path, monkeypatch):
    cal = FakeCalendar()
    monkeypatch.setattr(cli_mod, "make_calendar", lambda: cal)
    monkeypatch.setattr(cli_mod, "pdf_text", lambda path: AWAY)
    return cal


def invoke(*args):
    return CliRunner().invoke(cli_mod.cli, list(args))


def test_cli_import_lists_matches_and_what_it_left_alone(env, tmp_path):
    pdf = tmp_path / "Away.pdf"
    pdf.write_bytes(b"%PDF")
    res = invoke("import", str(pdf))
    assert res.exit_code == 0, res.output
    assert "Imported · 15 matches" in res.output
    assert "Brentford (A)" in res.output
    assert "Pre-match fans' event in Nottingham Forest" in res.output
    assert "Calendar: " in res.output


def test_cli_import_rejects_a_page_without_fixtures(env, tmp_path, monkeypatch):
    monkeypatch.setattr(cli_mod, "pdf_text", lambda path: "Hello")
    pdf = tmp_path / "x.pdf"
    pdf.write_bytes(b"%PDF")
    res = invoke("import", str(pdf))
    assert res.exit_code == 1
    assert "no fixtures found" in res.output


def test_cli_got_removes_reminders_and_undo_restores_the_mark(env, tmp_path):
    pdf = tmp_path / "Away.pdf"
    pdf.write_bytes(b"%PDF")
    invoke("import", str(pdf))
    res = invoke("got", "brentford")
    assert res.exit_code == 0, res.output
    assert "Brentford: marked as having tickets. Removed 1 reminder." in res.output
    assert not any(n.key == "sale:2026-27-brentford-a-premier-league" for n in env.events.values())
    assert "you have tickets" in invoke("upcoming").output
    res = invoke("got", "--undo", "brentford")
    assert "albion import" in res.output
    assert load(Path(cli_mod._state_path())).have_tickets == set()


def test_cli_got_ambiguous_or_unknown(env, tmp_path):
    pdf = tmp_path / "Away.pdf"
    pdf.write_bytes(b"%PDF")
    invoke("import", str(pdf))
    assert "matches several" in invoke("got", "united").output
    assert "No upcoming match" in invoke("got", "real madrid").output


HOME = (FIX / "ticket-page-home.txt").read_text()


def test_home_page_heading_before_time_and_cup_ties_only(state_path):
    r = parse_ticket_page(HOME, date(2026, 11, 13), "saved page")
    assert len(r.matches) == 16 and r.skipped == []
    craiova = r.matches[0]
    assert (craiova.opponent, craiova.home, craiova.competition) == (
        "Universitatea Craiova", True, "UEFA Conference League")
    assert craiova.kickoff == datetime(2026, 11, 26, 17, 45, tzinfo=TZ)
    assert craiova.on_sale_now and craiova.stages == []
    report = run_import(FakeCalendar(), [r], state_path, NOW, dry_run=False)
    assert report.imported == ["2026-27-universitatea-craiova-h-uefa-conference-league",
                               "2026-27-as-monaco-h-uefa-conference-league"]


def test_cup_tie_with_tickets_in_hand_keeps_its_fixture(env, tmp_path, monkeypatch):
    monkeypatch.setattr(cli_mod, "pdf_text", lambda path: HOME)
    pdf = tmp_path / "Home.pdf"
    pdf.write_bytes(b"%PDF")
    assert invoke("import", str(pdf)).exit_code == 0
    assert invoke("got", "monaco").exit_code == 0
    assert any(n.title == "⚽ Albion v AS Monaco" for n in env.events.values())
    assert "you have tickets" in invoke("upcoming").output


def test_cup_ties_to_come_fa_cup_and_conference_knockouts(state_path):
    page = ("Sat 9 Jan\n3:00 PM\nTBC v Albion\nEmirates FA Cup: Third Round\nAway Stadium\nBUY\n"
            "On Sale Dates:\nSTHs/1901 Club Members: Tue 15 Dec, 9am\n"
            "Thu 18 Feb\nAlbion v AS Roma\nTICKET INFORMATION\n8:00 PM\n"
            "UEFA Conference League: Knockout Round Play-offs\nAmerican Express Stadium\nBUY\n")
    r = parse_ticket_page(page, date(2026, 11, 13), "saved page")
    assert [(m.key, m.home) for m in r.matches] == [
        ("2026-27-tbc-a-fa-cup", False), ("2026-27-as-roma-h-uefa-conference-league", True)]
    cal = FakeCalendar()
    run_import(cal, [r], state_path, NOW, dry_run=False)
    # The draw is made: same day, real name. The placeholder gives way, with no duplicate.
    named = parse_ticket_page(page.replace("TBC v Albion", "Wrexham v Albion"), date(2026, 11, 13), "saved page")
    run_import(cal, [named], state_path, NOW, dry_run=False)
    state = load(state_path)
    assert "2026-27-tbc-a-fa-cup" not in state.matches and "2026-27-wrexham-a-fa-cup" in state.matches
    titles = [n.title for n in cal.events.values() if n.key.startswith("fixture:")]
    assert "⚽ TBC v Albion" not in titles and titles.count("⚽ Wrexham v Albion") == 1
