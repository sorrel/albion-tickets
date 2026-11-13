from datetime import datetime

from albion_tickets.config import TZ
from albion_tickets.model import Match, Stage, Status
from albion_tickets.rules import decide

PTS = 184


def at(m, d, h=9, mi=0, y=2026):
    return datetime(y, m, d, h, mi, tzinfo=TZ)


def stage(label, aud, pts, opens, pending=False):
    return Stage(label, aud, pts, pending, opens, False)


FOREST = [
    stage("STHs/1901 Club members with 284+pts", "sth", 284, at(10, 27)),
    stage("STHs/1901 Club members with 225+pts", "sth", 225, at(10, 28)),
    stage("STHs/1901 Club members with 205+pts", "sth", 205, at(10, 29)),
    stage("All STHs/1901 Club members", "sth", None, at(10, 30)),
    stage("All MyAlbion+ members", "myalbion", None, at(11, 3)),
]


def match(stages=FOREST, status=Status(), unreadable=()):
    return Match("k", "Nottingham Forest", False, "Premier League", at(12, 5, 17, 30), True,
                 list(stages), status, 10, "u", list(unreadable))


BEFORE = at(10, 20)


def test_184_gets_friday_on_forest():
    o = decide(match(), PTS, BEFORE, None)
    assert o.kind == "sale" and o.opens == at(10, 30) and o.stage.min_points is None
    assert o.pattern_note is None


def test_300_points_gets_tuesday():
    o = decide(match(), 300, BEFORE, None)
    assert o.opens == at(10, 27)


def test_210_points_gets_thursday():
    assert decide(match(), 210, BEFORE, None).opens == at(10, 29)


def test_brentford_predicted_friday():
    stages = [stage("STHs/1901 Club Members", "sth", None, at(12, 1), pending=True),
              stage("All MyAlbion+ Members", "myalbion", None, at(12, 8))]
    o = decide(match(stages), PTS, at(11, 13), None)
    assert o.kind == "predicted_sale" and o.opens == at(12, 4)


def test_pending_not_tuesday_uses_published_with_note():
    stages = [stage("STHs/1901 Club Members", "sth", None, at(12, 21), pending=True)]  # a Monday
    o = decide(match(stages), PTS, at(11, 13), None)
    assert o.kind == "predicted_sale" and o.opens == at(12, 21)
    assert o.pattern_note == "Not the usual Tuesday–Friday pattern"


def test_irregular_brackets_note():
    stages = [FOREST[0], FOREST[1], stage("All STHs/1901 Club members", "sth", None, at(10, 29))]
    o = decide(match(stages), PTS, BEFORE, None)
    assert o.pattern_note == "Not the usual Tuesday–Friday pattern"


def test_sold_out_before_first_stage_is_ignored():
    o = decide(match(status=Status(sold_out_label_seen=True)), PTS, BEFORE, BEFORE)
    assert o.kind == "sale"


def test_spurs_sold_out_at_239_is_before_you():
    status = Status(sold_out_to="STHs/1901 Club Members w/ 239+ Points", sold_out_min_points=239,
                    sold_out_label_seen=True)
    o = decide(match(status=status), PTS, at(10, 28, 12), at(10, 28, 12))
    assert o.kind == "sold_out_before_you"
    assert o.sold_out_stage == "STHs/1901 Club Members w/ 239+ Points"
    assert o.opens == at(10, 30)


def test_sold_out_to_all_myalbion_is_exchange_open():
    status = Status(sold_out_to="All MyAlbion+ Members", sold_out_label_seen=True)
    o = decide(match(status=status), PTS, at(11, 4), at(11, 4))
    assert o.kind == "exchange_open"


def test_wheelchair_only_after_thursday_opened_means_sold_at_thursday():
    o = decide(match(status=Status(wheelchair_only=True)), PTS, at(10, 29, 12), at(10, 29, 12))
    assert o.kind == "sold_out_before_you"
    assert "205+" in o.sold_out_stage


def test_wheelchair_only_after_friday_opened_is_exchange_open():
    o = decide(match(status=Status(wheelchair_only=True)), PTS, at(10, 30, 12), at(10, 30, 12))
    assert o.kind == "exchange_open"


def test_first_seen_time_used_not_now():
    o = decide(match(status=Status(wheelchair_only=True)), PTS, at(11, 10), at(10, 29, 12))
    assert o.kind == "sold_out_before_you"


def test_sold_out_unknown_stage_is_unreadable():
    o = decide(match(stages=[], status=Status(sold_out_label_seen=True)), PTS, BEFORE, BEFORE)
    assert o.kind == "unreadable"


def test_unreadable_lines_without_stages():
    o = decide(match(stages=[], unreadable=["STHs with 284+pts: Wed 27 Oct"]), PTS, BEFORE, None)
    assert o.kind == "unreadable"


def test_no_sth_stage_is_unreadable():
    o = decide(match(stages=[FOREST[4]]), PTS, BEFORE, None)
    assert o.kind == "unreadable"
