import gzip
from datetime import date
from pathlib import Path

from albion_tickets.discover import ticket_articles

FIX = Path(__file__).parent / "fixtures"


def test_discover_finds_only_ticket_articles():
    html = gzip.open(FIX / "listing-all.html.gz", "rt").read()
    found = ticket_articles(html)
    assert [(a.url.rsplit("/", 1)[1], a.published) for a in found] == [
        ("newcastle-united-sold-out-ticket-exchange-now-open", date(2026, 11, 13)),
        ("tottenham-hotspur-ticket-information", date(2026, 11, 5)),
        ("fulham-ticket-information", date(2026, 11, 5)),
        ("manchester-united-ticket-information", date(2026, 11, 5)),
    ]


def test_womens_articles_excluded():
    html = ('a.name="WSL tickets for Liverpool";a.slug="wsl-tickets";a.mediaType="Article";'
            'a.publishDateTime="2026-11-13T10:00+00:00";a.categories=[{name:"Ticket News",slug:"Ticket-News"}];')
    assert ticket_articles(html) == []
