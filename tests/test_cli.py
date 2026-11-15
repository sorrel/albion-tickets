import pytest
from click.testing import CliRunner

from albion_tickets import cli as cli_mod
from albion_tickets.calendar_app import FakeCalendar
from albion_tickets.fetch import FetchResult
from albion_tickets.rules import sold_out_tier
from albion_tickets.store import MatchRecord, load, save


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("ALBION_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(cli_mod, "make_calendar", FakeCalendar)
    monkeypatch.setattr(cli_mod, "make_fetcher", lambda: (lambda url: FetchResult(None, "", url, "offline")))
    return tmp_path


def run(*args):
    return CliRunner().invoke(cli_mod.cli, list(args))


def test_points_sets_and_upcoming_shows(env):
    r = run("points", "184")
    assert r.exit_code == 0 and "184" in r.output
    assert load(env / "state.json").points == 184
    r = run("upcoming")
    assert r.exit_code == 0 and "184 points" in r.output


def test_points_rejects_negative(env):
    assert run("points", "-5").exit_code != 0
    assert run("points", "5000").exit_code != 0


def test_check_dry_run_exit_zero_when_only_fetch_errors_are_absent(env, monkeypatch):
    run("points", "184")
    monkeypatch.setattr("albion_tickets.config.LISTING_PATHS", [])
    r = run("check", "--dry-run")
    assert r.exit_code == 0, r.output
    assert "dry run" in r.output.lower()


def test_check_exits_1_on_errors(env):
    run("points", "184")
    r = run("check")
    assert r.exit_code == 1 and "offline" in r.output


def test_dismiss_unknown_key_errors(env):
    run("points", "184")
    r = run("dismiss", "check:nothing")
    assert r.exit_code != 0 and "No such" in r.output


def test_dismiss_known_check_key(env):
    run("points", "184")
    st = load(env / "state.json")
    st.events["check:x"] = {"uid": "U", "owner": "u", "one_shot": False, "fp": "f", "start": "", "title": "t"}
    save(st, env / "state.json")
    assert run("dismiss", "check:x").exit_code == 0
    assert "check:x" in load(env / "state.json").dismissed


def test_add_accepts_only_main_site_articles(env):
    run("points", "184")
    assert run("add", "https://tickets.brightonandhovealbion.com/en-gb/categories/away").exit_code != 0
    url = "https://www.brightonandhovealbion.com/media-article/bournemouth-and-nottingham-forest-ticket-information"
    assert run("add", url).exit_code == 0
    assert url in load(env / "state.json").articles


def test_history_runs(env):
    run("points", "184")
    assert run("history").exit_code == 0


def _match(opponent, opens, kickoff):
    from albion_tickets.store import MatchRecord
    return MatchRecord(kickoffs=[(kickoff, kickoff)],
                       summary={"opponent": opponent, "home": False, "kind": "sale", "opens": opens})


def _sections(out: str) -> dict[str, str]:
    """`albion upcoming` output → {section title: its text}."""
    import re
    parts = re.split(r"^(You have tickets|Season ticket · home league|Sales to come[^\n]*|On sale now|Sold out|No sale dates yet|Needs a look)$",
                     out, flags=re.M)
    return {t.split(" ·")[0]: body for t, body in zip(parts[1::2], parts[2::2])}


def test_upcoming_groups_by_what_each_match_means(env):
    run("points", "184")
    st = load(env / "state.json")
    st.matches["a"] = _match("Already Open", "2000-01-07T09:00:00+00:00", "2099-01-01T15:00:00+00:00")
    st.matches["b"] = _match("Still To Come", "2099-01-01T09:00:00+00:00", "2099-02-01T15:00:00+00:00")
    st.matches["c"] = _match("Long Gone", "2000-01-01T09:00:00+00:00", "2000-01-08T15:00:00+00:00")
    st.matches["d"] = _match("Sold Before You", "2000-01-07T09:00:00+00:00", "2099-01-02T15:00:00+00:00")
    st.matches["d"].page_sold_out = {"label": "STHs/1901 Club Members w/ 239+ Points", "seen": "x"}
    st.matches["e"] = _match("Got Mine", "2000-01-07T09:00:00+00:00", "2099-01-03T15:00:00+00:00")
    st.have_tickets.add("e")
    st.last_check = "2099-01-01T12:00:00+00:00"
    save(st, env / "state.json")
    out = run("upcoming").output
    sec = _sections(out)
    assert "Got Mine" in sec["You have tickets"]
    assert "Still To Come" in sec["Sales to come"] and "Already Open" not in sec["Sales to come"]
    assert "Already Open" in sec["On sale now"]
    assert "Sold Before You" in sec["Sold out"] and "at 239+ points (STHs/1901)" in sec["Sold out"]
    assert "Long Gone" not in out
    assert "Last checked Thu 01 Jan 12:00" in out


def test_upcoming_colours_tickets_and_dims_sold_out(env):
    import click
    run("points", "184")
    st = load(env / "state.json")
    st.matches["d"] = _match("Sold Before You", "2000-01-07T09:00:00+00:00", "2099-01-02T15:00:00+00:00")
    st.matches["d"].page_sold_out = {"label": "All MyAlbion+ Members", "seen": "x"}
    st.matches["e"] = _match("Got Mine", "2000-01-07T09:00:00+00:00", "2099-01-03T15:00:00+00:00")
    st.have_tickets.add("e")
    save(st, env / "state.json")
    out = CliRunner().invoke(cli_mod.cli, ["upcoming"], color=True).output
    line = next(l for l in out.splitlines() if "Got Mine" in l)
    assert line.startswith(click.style("", fg="green", bold=True)[:-4])  # bold green, opened before the text
    assert click.unstyle(line).startswith("Got Mine (A)")
    sold = next(l for l in out.splitlines() if "Sold Before You" in l)
    assert sold.startswith("\x1b[2m")  # dim


def test_check_records_last_check(env, monkeypatch):
    run("points", "184")
    monkeypatch.setattr("albion_tickets.config.LISTING_PATHS", [])
    run("check")
    assert load(env / "state.json").last_check is not None
    assert "Not checked yet" not in run("upcoming").output


def test_sold_out_tier_names_the_widest_group():
    assert sold_out_tier("STHs/1901 Members, MyAlbion+ Members, and supporters with previous purchase history") \
        == "Purchase history"
    assert sold_out_tier("All MyAlbion+ Members") == "MyAlbion+"
    assert sold_out_tier("STHs/1901 Club Members w/ 239+ Points") == "239+"


def test_home_league_games_have_their_own_section_and_stay_out_of_history(env):
    run("points", "184")
    s = load(env / "state.json")
    s.matches["2026-27-everton-h-premier-league"] = MatchRecord(
        kickoffs=[("2099-12-13T14:00:00+00:00", "x")],
        summary={"opponent": "Everton", "home": True, "competition": "Premier League", "kind": "season_ticket"})
    save(s, env / "state.json")
    sections = _sections(run("upcoming").output)
    assert "Everton (H)" in sections["Season ticket"]
    assert "Everton" not in run("history", "--all").output
