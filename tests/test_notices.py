from datetime import datetime, timedelta

from albion_tickets.config import TZ
from albion_tickets.model import Match, Stage, Status
from albion_tickets.notices import change_notices, check_this, notices_for
from albion_tickets.rules import Outcome
from albion_tickets.store import Change


def at(m, d, h=9, mi=0, y=2026):
    return datetime(y, m, d, h, mi, tzinfo=TZ)


FRI = Stage("All STHs/1901 Club members", "sth", None, False, at(12, 4), True)
STAGES = [Stage("STHs/1901 Club members with 290+pts", "sth", 290, False, at(12, 1), True), FRI]


def brentford(kickoff=at(1, 16, 15, y=2027), confirmed=True, home=False, status=Status()):
    return Match("2026-27-brentford-a-premier-league", "Brentford", home, "Premier League", kickoff, confirmed,
                 STAGES, status, 5, "https://www.brightonandhovealbion.com/media-article/brentford")


def kinds(ns):
    return {n.key.split(":")[0]: n for n in ns}


def test_sale_alarms_evening_and_morning():
    o = Outcome("sale", FRI, at(12, 4))
    ns = kinds(notices_for(brentford(), o, 184, at(11, 20), sale_seen=at(11, 20), sold_out_seen=None))
    sale = ns["sale"]
    assert sale.start == at(12, 4) and sale.end == at(12, 4, 9, 15)
    assert sale.alarms == [at(12, 3, 19), at(12, 4, 8, 30), at(12, 4, 8, 55)]
    assert sale.title == "🎟️ Brentford away: your sale Fri 4 Dec 9am (All STHs/1901 Club members, you have 184)"
    assert "time assumed 9am" in sale.notes and "STHs/1901 Club members with 290+pts" in sale.notes
    assert not sale.one_shot


def test_late_found_sale_gets_immediate_alarm():
    o = Outcome("sale", FRI, at(12, 4))
    seen = at(12, 4, 8, 58)
    (sale,) = [n for n in notices_for(brentford(), o, 184, seen, sale_seen=seen, sold_out_seen=None)
               if n.key.startswith("sale:")]
    assert sale.alarms == [seen + timedelta(minutes=2)]


def test_alarms_stable_across_runs():
    o = Outcome("sale", FRI, at(12, 4))
    a = notices_for(brentford(), o, 184, at(11, 20), sale_seen=at(11, 20), sold_out_seen=None)
    b = notices_for(brentford(), o, 184, at(12, 3, 21), sale_seen=at(11, 20), sold_out_seen=None)
    assert a == b


def test_predicted_title_marked():
    o = Outcome("predicted_sale", STAGES[0], at(12, 4))
    (sale,) = [n for n in notices_for(brentford(), o, 184, at(11, 13), at(11, 13), None) if n.key.startswith("sale:")]
    assert sale.title.endswith("(predicted: brackets not announced yet)")


def test_pattern_note_in_notes():
    o = Outcome("sale", FRI, at(12, 4), pattern_note="Not the usual Tuesday–Friday pattern")
    (sale,) = [n for n in notices_for(brentford(), o, 184, at(11, 13), at(11, 13), None) if n.key.startswith("sale:")]
    assert "Not the usual Tuesday–Friday pattern" in sale.notes


def test_sold_out_note_has_no_alarms_and_replaces_sale():
    o = Outcome("sold_out_before_you", FRI, at(12, 4), sold_out_stage="STHs w/ 239+ Points")
    ns = kinds(notices_for(brentford(), o, 184, at(12, 2), at(11, 13), at(12, 2)))
    assert ns["sale"].alarms == []
    assert ns["sale"].title == "Brentford sold out at STHs w/ 239+ Points (you have 184)"


def test_exchange_open_anchored_to_sell_out_and_closing_day_before_1900():
    status = Status(exchange_closes=at(1, 13, y=2027))
    o = Outcome("exchange_open", FRI, None, sold_out_stage="All STHs/1901 Club Members")
    ns = kinds(notices_for(brentford(status=status), o, 184, at(12, 10), at(11, 13), at(12, 5, 10)))
    assert ns["exchange"].start == at(12, 5, 10, 5) and ns["exchange"].alarms == [at(12, 5, 10, 5)]
    assert ns["exchange_closing"].start == at(1, 12, 19, y=2027)
    assert ns["exchange_closing"].alarms == [at(1, 12, 19, y=2027)]
    assert "sale" not in ns


def test_fixture_unconfirmed_title():
    o = Outcome("sale", FRI, at(12, 4))
    ns = kinds(notices_for(brentford(confirmed=False), o, 184, at(11, 13), at(11, 13), None))
    fx = ns["fixture"]
    assert fx.title == "Brentford v Albion (time not confirmed)"
    assert fx.start == at(1, 16, 15, y=2027) and fx.end == at(1, 16, 17, y=2027) and fx.alarms == []


def test_points_upkeep_away_only():
    o = Outcome("sale", FRI, at(12, 4))
    away = kinds(notices_for(brentford(), o, 184, at(11, 13), at(11, 13), None))
    assert away["points"].start == at(1, 17, y=2027) and away["points"].alarms == []
    assert away["points"].title == "Did you go to Brentford? If so, update your points (worth 5): albion points <n>"
    home = kinds(notices_for(brentford(home=True), o, 184, at(11, 13), at(11, 13), None))
    assert "points" not in home


def test_change_notice_is_one_shot_with_unique_key():
    m = brentford()
    c = Change("kickoff_moved", m.key, at(1, 16, 15, y=2027).isoformat(), at(1, 17, 14, y=2027).isoformat())
    (n,) = change_notices([c], {m.key: m}, at(11, 20))
    assert n.one_shot and n.key == f"kickoff_moved:{m.key}:{c.new}"
    assert n.title == "⚠️ Brentford: kick-off moved Sat 16 Jan 3pm → Sun 17 Jan 2pm"
    assert n.start == at(11, 20, 9, 5) and n.alarms == [n.start]


def test_check_this_next_morning():
    n = check_this("check:x", "https://u", "Leeds ticket information", first_seen=at(11, 13, 20), soonest=None)
    assert n.start == at(11, 14, 8, 30) and n.alarms == [n.start]
    assert n.title == "Check this ticket article: Leeds ticket information"


def test_check_this_sooner_when_a_stage_opens_first():
    n = check_this("check:x", "https://u", "t", first_seen=at(11, 13, 20), soonest=at(11, 14, 8))
    assert n.start == at(11, 13, 20, 5)
