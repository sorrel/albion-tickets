"""Find ticket-news articles in the all-news listing page."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from . import config
from .payload import unescape

_ITEM = re.compile(
    r'(\w+)\.name="((?:[^"\\]|\\.)*)";\1\.slug="([^"]+)";\1\.mediaType="Article";'
    r'.{0,2000}?\1\.publishDateTime="([^"]+)";\1\.categories=\[\{name:"([^"]+)"',
    re.DOTALL,
)
_EXCLUDE = re.compile(r"\b(wsl|women'?s?|academy|under-\d+s|u\d{2}s?)\b", re.IGNORECASE)


@dataclass(frozen=True)
class ArticleRef:
    url: str
    title: str
    published: date


def article_count(listing_html: str) -> int:
    """How many articles of any kind the listing holds (0 means the format changed)."""
    return sum(1 for _ in _ITEM.finditer(listing_html))


def ticket_articles(listing_html: str) -> list[ArticleRef]:
    found: dict[str, ArticleRef] = {}
    for m in _ITEM.finditer(listing_html):
        title, slug, when, category = unescape(m.group(2)), m.group(3), m.group(4), m.group(5)
        if category != "Ticket News" or _EXCLUDE.search(title) or _EXCLUDE.search(slug.replace("-", " ")):
            continue
        url = f"{config.BASE_URL}/media-article/{slug}"
        found.setdefault(url, ArticleRef(url, title, date.fromisoformat(when[:10])))
    return list(found.values())
