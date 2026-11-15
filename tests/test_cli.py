import pytest
from click.testing import CliRunner

from albion_tickets import cli as cli_mod
from albion_tickets.calendar_app import FakeCalendar
from albion_tickets.fetch import FetchResult
from albion_tickets.store import load, save


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


def test_upcoming_separates_opened_sales_and_shows_last_check(env):
    run("points", "184")
    st = load(env / "state.json")
    st.matches["a"] = _match("Already Open", "2000-01-07T09:00:00+00:00", "2099-01-01T15:00:00+00:00")
    st.matches["b"] = _match("Still To Come", "2099-01-01T09:00:00+00:00", "2099-02-01T15:00:00+00:00")
    st.matches["c"] = _match("Long Gone", "2000-01-01T09:00:00+00:00", "2000-01-08T15:00:00+00:00")
    st.last_check = "2099-01-01T12:00:00+00:00"
    save(st, env / "state.json")
    out = run("upcoming").output
    coming, _, opened = out.partition("Sale already opened")
    assert "Still To Come" in coming and "Already Open" not in coming
    assert "Already Open" in opened
    assert "Long Gone" not in out
    assert "Last checked Thu 01 Jan 12:00" in out


def test_check_records_last_check(env, monkeypatch):
    run("points", "184")
    monkeypatch.setattr("albion_tickets.config.LISTING_PATHS", [])
    run("check")
    assert load(env / "state.json").last_check is not None
    assert "Not checked yet" not in run("upcoming").output


def test_sold_out_tier_names_the_widest_group():
    assert cli_mod._tier("STHs/1901 Members, MyAlbion+ Members, and supporters with previous purchase history") \
        == "Purchase history"
    assert cli_mod._tier("All MyAlbion+ Members") == "MyAlbion+"
    assert cli_mod._tier("STHs/1901 Club Members w/ 239+ Points") == "239+"
