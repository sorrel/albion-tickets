from datetime import date, datetime

from albion_tickets.config import TZ
from albion_tickets.parse_stages import parse_stages, parse_status

FOREST_TICKET_SITE = """On Sale Dates:
STHs/1901 Club Members w/ 284+ Points: Tue 27 Oct 9am
STHs/1901 Club Members w/ 225+ Points: Wed 28 Oct 9am
STHs/1901 Club Members w/ 205+ Points: Thu 29 Oct 9am
All STHs/1901 Club Members: Fri 30 Oct 9am
All MyAlbion+ Members: Tue 03 Nov 9am
Purchase History Thu 05 Nov 9am
Digital tickets will be issued to attendees on Thursday 3rd Dec."""

FOREST_ARTICLE = """On sale dates:
STHs/1901 Club members with 284+pts: Tue 27 Oct
STHs/1901 Club members with 225+pts: Wed 28 Oct
STHs/1901 Club members with 205+pts: Thu 29 Oct
All STHs/1901 Club members: Fri 30 Oct
All MyAlbion+ members: Tue 3 Nov
Pricing:
Adult: £30"""

FOREST_DAY = date(2026, 12, 5)


def at(y, m, d, h=9, mi=0):
    return datetime(y, m, d, h, mi, tzinfo=TZ)


def test_forest_four_brackets():
    stages, bad = parse_stages(FOREST_TICKET_SITE, FOREST_DAY, None)
    assert bad == []
    assert [(s.audience, s.min_points, s.opens) for s in stages[:5]] == [
        ("sth", 284, at(2026, 10, 27)),
        ("sth", 225, at(2026, 10, 28)),
        ("sth", 205, at(2026, 10, 29)),
        ("sth", None, at(2026, 10, 30)),
        ("myalbion", None, at(2026, 11, 3)),
    ]
    assert stages[5].audience == "other"
    assert all(not s.time_assumed for s in stages)


def test_article_variant_with_pts_and_no_time():
    stages, bad = parse_stages(FOREST_ARTICLE, FOREST_DAY, None)
    assert bad == []
    assert [s.min_points for s in stages] == [284, 225, 205, None, None]
    assert stages[0].time_assumed and stages[0].opens == at(2026, 10, 27)


def test_brackets_pending():
    text = "STHs/1901 Club Members *: Tue 01 Dec, 9am\nAll MyAlbion+ Members: Tue 08 Dec, 9am"
    stages, _ = parse_stages(text, date(2027, 1, 16), None)
    assert stages[0].brackets_pending and stages[0].audience == "sth"
    assert stages[0].min_points is None
    assert stages[0].opens == at(2026, 12, 1)


def test_time_before_date_and_guests():
    text = ("MyAlbion+ Members: 9am, Tuesday 10 Nov\n"
            "STH/1901 Club Member/MyAlbion+ Member Guests (2 Guests): 9am, Thursday 12 Nov")
    stages, _ = parse_stages(text, date(2027, 1, 2), None)
    assert [s.audience for s in stages] == ["myalbion", "guests"]
    assert not stages[1].time_assumed


def test_general_sale_and_season_ticket_holders():
    text = "Season Ticket Holders: Mon 7 Sep 9am\nGeneral Sale: Thu 10 Sep, 9am"
    stages, _ = parse_stages(text, date(2026, 10, 1), None)
    assert [s.audience for s in stages] == ["sth", "general"]


def test_weekday_mismatch_is_unreadable():
    text = "STHs/1901 Club members with 284+pts: Wed 27 Oct\nAll STHs/1901 Club members: Fri 30 Oct"
    stages, bad = parse_stages(text, FOREST_DAY, None)
    assert bad == ["STHs/1901 Club members with 284+pts: Wed 27 Oct"]
    assert len(stages) == 1


def test_non_stage_lines_ignored():
    stages, bad = parse_stages("Digital tickets will be issued on Thursday 3rd Dec.\nAdult: £30", FOREST_DAY, None)
    assert stages == [] and bad == []


def test_sold_out_to_bracket():
    s = parse_status("Sold out to STHs/1901 Club Members w/ 239+ Points", date(2026, 12, 29), None)
    assert s.sold_out_min_points == 239 and s.sold_out_label_seen
    assert s.sold_out_to.startswith("STHs/1901")


def test_sold_out_to_all_myalbion():
    s = parse_status("Sold out to All MyAlbion+ Members", date(2026, 11, 22), None)
    assert s.sold_out_to == "All MyAlbion+ Members" and s.sold_out_min_points is None


def test_sold_out_headline_without_stage():
    s = parse_status("Newcastle United sold out - ticket exchange now open", None, None)
    assert s.sold_out_label_seen and s.sold_out_to is None


def test_wheelchair_only():
    assert parse_status("Wheelchair Only", None, None).wheelchair_only


def test_exchange_close():
    s = parse_status("The resale for this fixture will close on Wednesday 18 Nov, 9am", date(2026, 11, 22), None)
    assert s.exchange_closes == at(2026, 11, 18)


def test_plain_text_has_no_status():
    s = parse_status("Pricing: Adult £30", None, None)
    assert not s.sold_out_label_seen and not s.wheelchair_only and s.exchange_closes is None
