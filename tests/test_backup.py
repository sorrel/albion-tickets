import csv
import json
from datetime import date, timedelta

from click.testing import CliRunner

from albion_tickets import cli as cli_mod
from albion_tickets.calendar_app import FakeCalendar
from albion_tickets.export import export
from albion_tickets.run import run_check
from albion_tickets.store import State, load, save

from tests.test_run import NOW, Fetcher, pages


def test_first_save_makes_no_backup(tmp_path):
    save(State(points=1), tmp_path / "state.json", today=date(2026, 11, 14))
    assert not (tmp_path / "backups").exists()


def test_one_backup_a_day_holding_the_state_before_that_days_first_save(tmp_path):
    p = tmp_path / "state.json"
    save(State(points=1), p, today=date(2026, 11, 13))
    save(State(points=2), p, today=date(2026, 11, 14))
    save(State(points=3), p, today=date(2026, 11, 14))
    files = sorted((tmp_path / "backups").iterdir())
    assert [f.name for f in files] == ["state-2026-11-14.json"]
    assert json.loads(files[0].read_text())["points"] == 1
    assert load(p).points == 3


def test_backups_keep_14_days_and_the_first_of_each_month(tmp_path):
    p = tmp_path / "state.json"
    day = date(2026, 9, 1)
    for i in range(70):  # 1 Sep → 9 Nov
        save(State(points=i), p, today=day + timedelta(days=i))
    names = sorted(f.name for f in (tmp_path / "backups").iterdir())
    recent = [f"state-{day + timedelta(days=i)}.json" for i in range(56, 70)]
    monthly = ["state-2026-09-02.json", "state-2026-10-01.json"]  # 1 Sep had nothing to back up yet
    assert names == sorted(set(recent + monthly + ["state-2026-11-01.json"]))


def _checked(tmp_path, monkeypatch):
    monkeypatch.setenv("ALBION_DATA_DIR", str(tmp_path / "data"))
    p = tmp_path / "data" / "state.json"
    save(State(points=184), p)
    run_check(FakeCalendar(), Fetcher(pages()), p, NOW, dry_run=False)
    return p


def test_export_writes_state_history_csv_and_snapshots(tmp_path, monkeypatch):
    p = _checked(tmp_path, monkeypatch)
    out = export(load(p), tmp_path / "data", tmp_path / "safe")
    assert out == tmp_path / "safe" / "albion-tickets"
    assert json.loads((out / "state.json").read_text())["points"] == 184
    rows = list(csv.DictReader((out / "history-2026-27.csv").open()))
    spurs = next(r for r in rows if r["opponent"] == "Tottenham Hotspur")
    assert spurs["venue"] == "away" and spurs["worth"] == "5"
    assert spurs["brackets"] == "291+ / 239+ / 208+" and spurs["your_sale"].startswith("2026-11-13T09:00")
    assert spurs["kickoff"].startswith("2026-12-29T19:30")
    assert any((out / "snapshots").iterdir())


def test_export_folder_is_remembered_and_refreshed_by_each_check(tmp_path, monkeypatch):
    p = _checked(tmp_path, monkeypatch)
    monkeypatch.setattr(cli_mod, "make_calendar", FakeCalendar)
    monkeypatch.setattr(cli_mod, "make_fetcher", lambda: Fetcher(pages()))
    r = CliRunner().invoke(cli_mod.cli, ["export", str(tmp_path / "safe")])
    assert r.exit_code == 0 and "safe" in r.stdout
    assert load(p).export_dir == str(tmp_path / "safe")
    target = tmp_path / "safe" / "albion-tickets" / "state.json"
    target.unlink()
    CliRunner().invoke(cli_mod.cli, ["check", "--dry-run"])
    assert not target.exists()  # a dry run writes nothing anywhere
    CliRunner().invoke(cli_mod.cli, ["check"])
    assert target.exists()
    assert CliRunner().invoke(cli_mod.cli, ["export"]).exit_code == 0  # uses the remembered folder


def test_export_without_a_folder_the_first_time_explains(tmp_path, monkeypatch):
    monkeypatch.setenv("ALBION_DATA_DIR", str(tmp_path))
    save(State(points=184), tmp_path / "state.json")
    r = CliRunner().invoke(cli_mod.cli, ["export"])
    assert r.exit_code != 0 and "albion export <folder>" in r.output
