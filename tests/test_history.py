from click.testing import CliRunner

from albion_tickets import cli as cli_mod
from albion_tickets.calendar_app import FakeCalendar
from albion_tickets.run import run_check
from albion_tickets.store import State, load, save

from tests.test_run import NOW, Fetcher, pages


def _history(tmp_path, monkeypatch):
    monkeypatch.setenv("ALBION_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(cli_mod, "_today", lambda: NOW.date())
    p = tmp_path / "state.json"
    save(State(points=184), p)
    run_check(FakeCalendar(), Fetcher(pages()), p, NOW, dry_run=False)
    return CliRunner().invoke(cli_mod.cli, ["history"]).stdout


def _run(*args, color=False):
    return CliRunner().invoke(cli_mod.cli, ["history", *args], color=color).stdout


def _row(out, kickoff):
    return next(l for l in out.splitlines() if l.startswith(kickoff))


def test_history_is_a_table_per_season(tmp_path, monkeypatch):
    out = _history(tmp_path, monkeypatch)
    lines = out.splitlines()
    assert lines[0] == "2026–27 season · you have 184 points"
    header = next(l for l in lines if l.startswith("Kick-off"))
    for col in ["Match", "Comp", "Worth", "Tue / Wed / Thu", "Your sale", "Sold out at"]:
        assert col in header
    spurs = _row(out, "Tue 29 Dec 19:30")
    for cell in ["Tottenham Hotspur (A)", "PL", "5", "291+ / 239+ / 208+", "Fri 13 Nov", "—"]:
        assert cell in spurs
    assert spurs.index("Tottenham") < spurs.index("291+") < spurs.index("Fri 13 Nov")


def test_history_rows_are_in_kick_off_order(tmp_path, monkeypatch):
    out = _history(tmp_path, monkeypatch)
    rows = [l for l in out.splitlines() if l[:3] in {"Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"}]
    assert [r.split("  ")[0] for r in rows] == ["Sat 26 Dec 15:00", "Tue 29 Dec 19:30"]


def test_history_headings_are_bold_yellow_in_a_terminal(tmp_path, monkeypatch):
    _history(tmp_path, monkeypatch)
    out = _run(color=True)
    assert "\x1b[1m" in out and "\x1b[33m" in out
    assert "\x1b[" not in _run()  # plain when piped or logged


def _add_old_season(tmp_path):
    p = tmp_path / "state.json"
    st = load(p)
    key = next(iter(st.matches))
    old = type(st.matches[key])(**{**st.matches[key].__dict__})
    old.kickoffs = [["2026-03-14T15:00:00+00:00", "2026-02-20T10:00:00+00:00"]]
    old.summary = {**old.summary, "opponent": "Leeds United"}
    st.matches["2025-26-leeds-united-a-premier-league"] = old
    save(st, p)


def test_history_shows_the_current_season_by_default(tmp_path, monkeypatch):
    _history(tmp_path, monkeypatch)
    _add_old_season(tmp_path)
    out = _run()
    assert "Leeds United" not in out and "2025–26" not in out


def test_history_one_season_or_all(tmp_path, monkeypatch):
    _history(tmp_path, monkeypatch)
    _add_old_season(tmp_path)
    one = _run("--season", "2025-26")
    assert one.splitlines()[0] == "2025–26 season"  # your points today say nothing about last season
    assert "Leeds United (A)" in one
    assert "Tottenham" not in one
    every = _run("--all")
    assert every.index("2025–26 season") < every.index("2026–27 season")


def test_history_unknown_season_says_so(tmp_path, monkeypatch):
    _history(tmp_path, monkeypatch)
    assert "No matches recorded for 2019–20." in _run("--season", "2019-20")


def test_history_shows_sell_out_tier_and_kick_off_moves(tmp_path, monkeypatch):
    _history(tmp_path, monkeypatch)
    p = tmp_path / "state.json"
    st = load(p)
    key = next(k for k, r in st.matches.items() if r.summary["opponent"] == "Tottenham Hotspur")
    rec = st.matches[key]
    rec.summary["sold_out_stage"] = "STHs w/ 239+ Points"
    rec.first_sold_out_seen = "2026-11-11T13:00:00+00:00"
    rec.kickoffs.insert(0, ["2026-12-28T15:00:00+00:00", "2026-11-01T10:00:00+00:00"])
    save(st, p)
    out = _run()
    assert _row(out, "Tue 29 Dec 19:30").rstrip().endswith("239+")
    assert "Tottenham Hotspur kick-off moved: Mon 28 Dec 15:00 → Tue 29 Dec 19:30 (noticed Fri 13 Nov 20:00)" in out


def test_history_verbose_lists_every_stage(tmp_path, monkeypatch):
    _history(tmp_path, monkeypatch)
    out = _run("-v")
    assert "  Fri 13 Nov 09:00  All STHs/1901 Club members  ← your stage" in out.splitlines()
    assert "  Tue 17 Nov 09:00  All MyAlbion+ members" in out.splitlines()
