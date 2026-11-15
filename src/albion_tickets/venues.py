"""Where a match is played, for the calendar's location field.

Grounds are kept as "Ground, Town" so Calendar and Maps can find them. Order:
the built-in table of English grounds (this season's Premier League, plus
recent and likely visitors), then what saved ticket pages have taught us
(cup ties, European grounds, one-off venues), then the Amex for home games.
"""
from __future__ import annotations

import re

HOME = "American Express Stadium, Brighton"

GROUNDS = {
    # Premier League 2026–27
    "Arsenal": "Emirates Stadium, London",
    "Aston Villa": "Villa Park, Birmingham",
    "Bournemouth": "Vitality Stadium, Bournemouth",
    "Brentford": "Gtech Community Stadium, Brentford",
    "Chelsea": "Stamford Bridge, London",
    "Coventry City": "Coventry Building Society Arena, Coventry",
    "Crystal Palace": "Selhurst Park, London",
    "Everton": "Hill Dickinson Stadium, Liverpool",
    "Fulham": "Craven Cottage, London",
    "Hull City": "MKM Stadium, Hull",
    "Ipswich Town": "Portman Road, Ipswich",
    "Leeds United": "Elland Road, Leeds",
    "Liverpool": "Anfield, Liverpool",
    "Manchester City": "Etihad Stadium, Manchester",
    "Manchester United": "Old Trafford, Manchester",
    "Newcastle United": "St James' Park, Newcastle upon Tyne",
    "Nottingham Forest": "City Ground, Nottingham",
    "Sunderland": "Stadium of Light, Sunderland",
    "Tottenham Hotspur": "Tottenham Hotspur Stadium, London",
    # Recently in the Premier League: likely league or cup opponents
    "Burnley": "Turf Moor, Burnley",
    "Leicester City": "King Power Stadium, Leicester",
    "Luton Town": "Kenilworth Road, Luton",
    "Norwich City": "Carrow Road, Norwich",
    "Sheffield United": "Bramall Lane, Sheffield",
    "Southampton": "St Mary's Stadium, Southampton",
    "West Ham United": "London Stadium, London",
    "Wolverhampton Wanderers": "Molineux Stadium, Wolverhampton",
}

_KNOWN = {k.lower(): v for k, v in GROUNDS.items()}
_PLAYED_AT = re.compile(r"\bplayed at (?:the )?(.+?)\s*\.?$", re.I | re.M)
_PLACEHOLDER = re.compile(r"^(away stadium|tbc|to be confirmed)$", re.I)


def from_page(line: str | None, body: str) -> str | None:
    """The ground a ticket page gives: 'MKM Stadium (Hull City)' → 'MKM Stadium, Hull City'.

    Some pages say only "Away Stadium" and name the real ground in the text
    ("The fixture will be played at Olympic Stadium of Athens.").
    """
    played = _PLAYED_AT.search(body)
    if played:
        return played.group(1).strip()
    if not line or line.isupper() or _PLACEHOLDER.match(line.strip()):  # "BUY", "ACCESS GUIDE"…
        return None
    m = re.match(r"^(.+?)\s*\((.+)\)$", line.strip())
    return f"{m.group(1)}, {m.group(2)}" if m else line.strip()


def location(opponent: str, home: bool, page_venue: str | None, learnt: dict[str, str]) -> str:
    if home:
        elsewhere = page_venue and "american express" not in page_venue.lower()
        return page_venue if elsewhere else HOME
    return _KNOWN.get(opponent.lower()) or page_venue or learnt.get(opponent) or ""
