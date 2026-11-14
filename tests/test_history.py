from click.testing import CliRunner

from albion_tickets import cli as cli_mod
from albion_tickets.calendar_app import FakeCalendar
from albion_tickets.run import run_check
from albion_tickets.store import State, load, save

from tests.test_run import NOW, Fetcher, pages


def _history(tmp_path, monkeypatch):
    monkeypatch.setenv("ALBION_DATA_DIR", str(tmp_path))
    p = tmp_path / "state.json"
    save(State(points=184), p)
    run_check(FakeCalendar(), Fetcher(pages()), p, NOW, dry_run=False)
    return CliRunner().invoke(cli_mod.cli, ["history"]).stdout


def test_history_shows_each_match_with_its_sale_stages(tmp_path, monkeypatch):
    out = _history(tmp_path, monkeypatch)
    blocks = out.strip().split("\n\n")
    spurs = next(b for b in blocks if b.startswith("Tottenham Hotspur"))
    assert spurs.splitlines() == [
        "Tottenham Hotspur (away) · Premier League · Tue 29 Dec 19:30 · worth 5 points",
        "  Tue 10 Nov 09:00  STHs/1901 with 291+ points",
        "  Wed 11 Nov 09:00  STHs/1901 with 239+ points",
        "  Thu 12 Nov 09:00  STHs/1901 with 208+ points",
        "  Fri 13 Nov 09:00  All STHs/1901 Club members  ← your stage",
        "  Tue 17 Nov 09:00  All MyAlbion+ members",
        "  Sold out: not reported in the club's news",
    ]


def test_history_is_in_kick_off_order(tmp_path, monkeypatch):
    out = _history(tmp_path, monkeypatch)
    heads = [b.splitlines()[0].split(" (")[0] for b in out.strip().split("\n\n")]
    assert heads == ["Fulham", "Tottenham Hotspur"]  # Sat 26 Dec, then Tue 29 Dec


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
    out = CliRunner().invoke(cli_mod.cli, ["history"]).stdout
    spurs = next(b for b in out.strip().split("\n\n") if b.startswith("Tottenham Hotspur"))
    assert "  Sold out at STHs w/ 239+ Points (noticed Wed 11 Nov 13:00)" in spurs.splitlines()
    assert "  Kick-off moved: Mon 28 Dec 15:00 → Tue 29 Dec 19:30 (noticed Fri 13 Nov 20:00)" in spurs.splitlines()
