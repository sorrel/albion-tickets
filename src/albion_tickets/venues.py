"""Where a match is played, for the calendar's location field.

Each ground is a full postal address plus its map pin, so the calendar event
shows a map. Order: the built-in table of English grounds (this season's
Premier League, plus recent visitors), then what saved ticket pages have
taught us (cup ties, European grounds, one-off venues: text only, pinned by
Maps when the event is written), then the Amex for home games.
"""
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Ground:
    address: str  # full postal address, so Maps finds it from the text alone
    lat: float | None = None  # the pin, from Apple Maps (None: Calendar looks it up)
    lon: float | None = None


HOME = Ground("American Express Stadium, Village Way, Brighton BN1 9BL, England", 50.86146, -0.08358)

# Checked 15 November 2026 against Apple's geocoder and Maps: every pin lies
# within 0.65 km of its address (most within 0.1 km). Newcastle's pin is the
# address's own position, as a name search finds the London park first.
GROUNDS = {
    # Premier League 2026–27
    "Arsenal": Ground("Emirates Stadium, Hornsey Road, London N7 7AJ, England", 51.55509, -0.10845),
    "Aston Villa": Ground("Villa Park, Trinity Road, Birmingham B6 6HE, England", 52.50873, -1.88573),
    "Bournemouth": Ground("Vitality Stadium, Kings Park, Bournemouth BH7 7AF, England", 50.73517, -1.83824),
    "Brentford": Ground("Gtech Community Stadium, Lionel Road South, Brentford TW8 0RU, England", 51.49080, -0.28874),
    "Chelsea": Ground("Stamford Bridge, Fulham Road, London SW6 1HS, England", 51.48171, -0.19095),
    "Coventry City": Ground("Coventry Building Society Arena, Judds Lane, Coventry CV6 6GE, England", 52.44867, -1.49714),
    "Crystal Palace": Ground("Selhurst Park, Holmesdale Road, London SE25 6PU, England", 51.39822, -0.08545),
    "Everton": Ground("Hill Dickinson Stadium, Regent Road, Liverpool L3 0BW, England", 53.42485, -3.00266),
    "Fulham": Ground("Craven Cottage, Stevenage Road, London SW6 6HH, England", 51.47485, -0.22164),
    "Hull City": Ground("MKM Stadium, West Park, Hull HU3 6HU, England", 53.74665, -0.36771),
    "Ipswich Town": Ground("Portman Road, Ipswich IP1 2DA, England", 52.05481, 1.14634),
    "Leeds United": Ground("Elland Road, Leeds LS11 0ES, England", 53.77775, -1.57227),
    "Liverpool": Ground("Anfield, Anfield Road, Liverpool L4 0TH, England", 53.43101, -2.96125),
    "Manchester City": Ground("Etihad Stadium, Ashton New Road, Manchester M11 3FF, England", 53.48306, -2.20036),
    "Manchester United": Ground("Old Trafford, Sir Matt Busby Way, Manchester M16 0RA, England", 53.46308, -2.29133),
    "Newcastle United": Ground("St James' Park, Strawberry Place, Newcastle upon Tyne NE1 4ST, England", 54.97446, -1.62116),
    "Nottingham Forest": Ground("City Ground, Pavilion Road, Nottingham NG2 5FJ, England", 52.93975, -1.13275),
    "Sunderland": Ground("Stadium of Light, Millennium Way, Sunderland SR5 1SU, England", 54.91444, -1.38846),
    "Tottenham Hotspur": Ground("Tottenham Hotspur Stadium, 782 High Road, London N17 0BX, England", 51.60420, -0.06627),
    # Recently in the Premier League: likely league or cup opponents
    "Burnley": Ground("Turf Moor, Harry Potts Way, Burnley BB10 4BX, England", 53.78847, -2.23032),
    "Leicester City": Ground("King Power Stadium, Filbert Way, Leicester LE2 7FL, England", 52.62028, -1.14218),
    "Luton Town": Ground("Kenilworth Road, 1 Maple Road, Luton LU4 8AW, England", 51.88433, -0.42932),
    "Norwich City": Ground("Carrow Road, Norwich NR1 1JE, England", 52.62215, 1.30878),
    "Sheffield United": Ground("Bramall Lane, Sheffield S2 4SU, England", 53.37038, -1.47091),
    "Southampton": Ground("St Mary's Stadium, Britannia Road, Southampton SO14 5FP, England", 50.90652, -1.39081),
    "West Ham United": Ground("London Stadium, Marshgate Lane, Queen Elizabeth Olympic Park, London E20 2ST, England", 51.53865, -0.01648),
    "Wolverhampton Wanderers": Ground("Molineux Stadium, Waterloo Road, Wolverhampton WV1 4QR, England", 52.59022, -2.13038),
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


def location(opponent: str, home: bool, page_venue: str | None, learnt: dict[str, str]) -> Ground | None:
    if home:
        if page_venue and "american express" not in page_venue.lower():
            return Ground(page_venue)  # a neutral ground, e.g. a final
        return HOME
    if opponent.lower() in _KNOWN:
        return _KNOWN[opponent.lower()]
    text = page_venue or learnt.get(opponent)
    return Ground(text) if text else None
