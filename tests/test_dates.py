from datetime import date, datetime, time

import pytest

from albion_tickets.dates import at_london, parse_day_date, parse_time

MATCH = date(2026, 12, 5)


@pytest.mark.parametrize(
    "text, expected",
    [
        ("Tue 27 Oct", date(2026, 10, 27)),
        ("Tues 27 Oct", date(2026, 10, 27)),
        ("Thur 29 Oct", date(2026, 10, 29)),
        ("Thu 29 Oct", date(2026, 10, 29)),
        ("Wednesday 18 Nov", date(2026, 11, 18)),
        ("Mon 30th Nov", date(2026, 11, 30)),
        ("Fri 30 October", date(2026, 10, 30)),
        ("9am, Tuesday 10 Nov", date(2026, 11, 10)),
    ],
)
def test_parses_abbreviations(text, expected):
    assert parse_day_date(text, before=MATCH, after=None) == expected


def test_year_rolls_back_across_new_year():
    assert parse_day_date("Tue 29 Dec", before=date(2027, 1, 30), after=None) == date(2026, 12, 29)


def test_after_picks_next_occurrence():
    assert parse_day_date("Tue 5 Jan", before=None, after=date(2026, 11, 13)) == date(2027, 1, 5)


def test_weekday_mismatch_returns_none():
    assert parse_day_date("Wed 27 Oct", before=MATCH, after=None) is None


def test_no_date_returns_none():
    assert parse_day_date("Pricing:", before=MATCH, after=None) is None


def test_missing_time_is_assumed_9am():
    assert parse_time("Tue 27 Oct") == (time(9, 0), True)


@pytest.mark.parametrize(
    "text, expected",
    [("9am", time(9)), ("9:30am", time(9, 30)), ("10.00am", time(10)), ("2:05 PM", time(14, 5)),
     ("kick-off 7.30pm", time(19, 30)), ("kick-off 12:30pm", time(12, 30)), ("kick-off 3pm", time(15))],
)
def test_times(text, expected):
    assert parse_time(text) == (expected, False)


def test_at_london_is_aware_and_gmt_in_winter():
    dt = at_london(date(2026, 12, 4), time(9))
    assert dt.utcoffset().total_seconds() == 0
    assert isinstance(dt, datetime)
