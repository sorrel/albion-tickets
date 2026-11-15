"""A ticket-site page the user saved by hand (Away Games or Home Games) → matches.

The tool never requests the ticket site (see CLAUDE.md). The user opens it in
their own browser, saves it as a PDF, and `albion import` reads that file.

PDFKit gives each fixture as a block that starts with its date line:

    Sat 16 Jan            (repeated: the page draws each heading several times)
    3:00 PM               (home cup ties put the heading first, then
    Brentford v Albion     "TICKET INFORMATION", then the time)
    Premier League
    Gtech Community Stadium (Brentford FC)
    …
    On Sale Dates:
    STHs/1901 Club Members *: Tue 01 Dec, 9am
"""
import re
import subprocess
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from . import venues
from .dates import at_london, parse_day_date, parse_time
from .model import Match, match_key
from .parse_article import competition, heading
from .parse_stages import parse_stages, parse_status

SCRIPT = Path(__file__).with_name("pdf_text.js")

# The ticket site's short names → the names the club's news articles use, so
# an imported match and a later article share one record.
ALIASES = {
    "spurs": "Tottenham Hotspur",
    "nott'm forest": "Nottingham Forest",
    "notts forest": "Nottingham Forest",
    "man utd": "Manchester United",
    "man united": "Manchester United",
    "man city": "Manchester City",
    "newcastle": "Newcastle United",
    "leeds": "Leeds United",
    "west ham": "West Ham United",
    "wolves": "Wolverhampton Wanderers",
    "sheff utd": "Sheffield United",
    "sheff wed": "Sheffield Wednesday",
    "hull": "Hull City",
    "leicester": "Leicester City",
    "ipswich": "Ipswich Town",
    "norwich": "Norwich City",
    "cardiff": "Cardiff City",
    "coventry": "Coventry City",
    "burnley": "Burnley",
    "stoke": "Stoke City",
    "luton": "Luton Town",
    "swansea": "Swansea City",
}

_DATE_LINE = re.compile(r"^(mon|tue|wed|thu|fri|sat|sun)[a-z]*\s+\d{1,2}(st|nd|rd|th)?\s+[a-z]{3,9}$", re.I)
_TIME_LINE = re.compile(r"^\d{1,2}[:.]\d{2}\s*(am|pm)$", re.I)
_REPEATED = re.compile(r"^(.+?)(?:\s+\1)+$")
_ON_SALE = re.compile(r"^On (?:General )?Sale\b", re.I | re.M)
_FOOTER = re.compile(r"^Company Details\b|^©")


class PdfError(Exception):
    pass


@dataclass(frozen=True)
class PageResult:
    matches: list[Match]
    skipped: list[str]  # blocks that aren't matches, as "Sat 5 Dec: Pre-match fans' event …"


def pdf_text(path: Path) -> str:
    try:
        done = subprocess.run(["osascript", "-l", "JavaScript", str(SCRIPT), str(path)],
                              capture_output=True, text=True, timeout=60)
    except subprocess.TimeoutExpired as exc:
        raise PdfError("reading the PDF took over 60 s") from exc
    if done.returncode != 0:
        raise PdfError(done.stderr.strip() or f"osascript exited {done.returncode}")
    return done.stdout


def _dedupe(line: str) -> str:
    line = re.sub(r"\s+", " ", line.replace("’", "'")).strip()
    m = _REPEATED.match(line)
    return m.group(1) if m else line


def canonical(opponent: str) -> str:
    return ALIASES.get(opponent.lower(), opponent)


def parse_ticket_page(text: str, today: date, source: str) -> PageResult:
    lines = [_dedupe(l) for l in text.splitlines()]
    lines = [l for l in lines if l]
    starts = [i for i, l in enumerate(lines) if _DATE_LINE.match(l)]
    matches: list[Match] = []
    skipped: list[str] = []
    for n, start in enumerate(starts):
        end = starts[n + 1] if n + 1 < len(starts) else len(lines)
        block = lines[start:end]
        footer = next((i for i, l in enumerate(block) if _FOOTER.search(l)), None)
        block = block[:footer] if footer is not None else block
        day = parse_day_date(block[0], before=None, after=today)
        # The heading and the time come in either order, sometimes with a
        # "TICKET INFORMATION" line between them; the competition follows both.
        top = block[1:5]
        when = next((i for i, l in enumerate(top, 1) if _TIME_LINE.match(l)), None)
        named = next((i for i, l in enumerate(top, 1) if heading(l, "") is not None), None)
        if day is None or when is None or named is None:
            skipped.append(f"{block[0]}: {block[1] if len(block) > 1 else '(nothing after the date)'}")
            continue
        opponent, home = heading(block[named], "")
        opponent = canonical(opponent)
        after = max(when, named) + 1
        comp = competition(block[after] if after < len(block) else "")
        body = "\n".join(block[after + 1:])
        stages, unreadable = parse_stages(body, day, today)
        pts = re.search(r"points allocated for this fixture\s*:?\s*(\d+)", body, re.I)
        matches.append(Match(
            key=match_key(day, opponent, home, comp),
            opponent=opponent,
            home=home,
            competition=comp,
            kickoff=at_london(day, parse_time(block[when])[0]),
            kickoff_confirmed=True,
            stages=stages,
            status=parse_status(body, day, today),
            fixture_points=int(pts.group(1)) if pts else None,
            url=source,
            unreadable=unreadable,
            on_sale_now=bool(_ON_SALE.search(body)),
            venue=venues.from_page(block[after + 1] if after + 1 < len(block) else None, body),
        ))
    return PageResult(matches, skipped)
