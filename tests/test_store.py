from datetime import datetime

import pytest

from albion_tickets.config import TZ
from albion_tickets.model import Match, Stage, Status
from albion_tickets.store import State, StateError, load, observe, save, snapshot


def at(m, d, h=9, mi=0):
    return datetime(2026, m, d, h, mi, tzinfo=TZ)


STAGES = [Stage("All STHs/1901 Club members", "sth", None, False, at(10, 30), False)]


def match(kickoff=at(12, 5, 17, 30), status=Status()):
    return Match("2026-27-nottingham-forest-a-premier-league", "Nottingham Forest", False, "Premier League",
                 kickoff, True, STAGES, status, 10, "u")


def test_first_observation_no_change():
    s = State()
    assert observe(s, match(), at(10, 30), at(10, 20)) == []
    rec = s.matches[match().key]
    assert rec.kickoffs == [(at(12, 5, 17, 30).isoformat(), at(10, 20).isoformat())]


def test_kickoff_moved_detected_and_history_kept():
    s = State()
    observe(s, match(), at(10, 30), at(10, 20))
    changes = observe(s, match(kickoff=at(12, 6, 14)), at(10, 30), at(10, 21))
    assert [(c.kind, c.old, c.new) for c in changes] == [
        ("kickoff_moved", at(12, 5, 17, 30).isoformat(), at(12, 6, 14).isoformat())]
    assert len(s.matches[match().key].kickoffs) == 2


def test_same_kickoff_no_change():
    s = State()
    observe(s, match(), at(10, 30), at(10, 20))
    assert observe(s, match(), at(10, 30), at(10, 21)) == []
    assert len(s.matches[match().key].kickoffs) == 1


def test_sale_moved_detected():
    s = State()
    observe(s, match(), at(10, 30), at(10, 20))
    (c,) = observe(s, match(), at(10, 29), at(10, 21))
    assert c.kind == "sale_moved" and c.new == at(10, 29).isoformat()


def test_sale_appearing_is_not_a_move():
    s = State()
    observe(s, match(), None, at(10, 20))
    assert observe(s, match(), at(10, 30), at(10, 21)) == []


def test_first_sold_out_seen_recorded_once_and_only_after_sales_open():
    s = State()
    sold = match(status=Status(sold_out_label_seen=True))
    observe(s, sold, at(10, 30), at(10, 20))  # before the first stage: a pre-sale label
    assert s.matches[sold.key].first_sold_out_seen is None
    observe(s, sold, at(10, 30), at(10, 30, 12))
    observe(s, sold, at(10, 30), at(10, 31))
    assert s.matches[sold.key].first_sold_out_seen == at(10, 30, 12).isoformat()


def test_snapshot_dedupes_identical_text(tmp_path):
    assert snapshot("u", "Fulham  v Albion\n", tmp_path, at(11, 13)) is True
    assert snapshot("u", "Fulham v Albion", tmp_path, at(11, 13)) is False
    assert len(list((tmp_path / "snapshots").glob("*.txt"))) == 1


def test_round_trip_and_atomic(tmp_path):
    p = tmp_path / "state.json"
    s = State(points=184)
    observe(s, match(), at(10, 30), at(10, 20))
    s.events["sale:k"] = {"uid": "U1", "match": "k", "one_shot": False}
    s.dismissed.add("check:x")
    save(s, p)
    assert not list(tmp_path.glob("*.tmp"))
    again = load(p)
    assert again.points == 184 and again.events == s.events and again.dismissed == {"check:x"}
    assert again.matches[match().key].kickoffs == s.matches[match().key].kickoffs


def test_missing_state_is_empty(tmp_path):
    assert load(tmp_path / "nope.json").points is None


def test_corrupt_state_raises(tmp_path):
    p = tmp_path / "state.json"
    p.write_text("{not json")
    with pytest.raises(StateError):
        load(p)
