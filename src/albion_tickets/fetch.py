"""Polite, read-only HTTP GET of the club's main website — and nothing else.

One request at a time, honest User-Agent, no cookies kept, no JavaScript.
Never raises: failures come back as a FetchResult with an error string.
Any host other than the main website is refused before the network is touched,
so the protected ticket site can never be requested by this tool.
"""
from __future__ import annotations

import time
import urllib.error
import urllib.request
import urllib.robotparser
from dataclasses import dataclass
from urllib.parse import urlsplit

from . import config


@dataclass(frozen=True)
class FetchResult:
    status: int | None
    body: str
    final_url: str
    error: str | None

    @property
    def ok(self) -> bool:
        return self.error is None and self.status == 200


def _allowed(url: str) -> bool:
    parts = urlsplit(url)
    return parts.scheme == "https" and parts.hostname == config.ALLOWED_HOST


class SameSiteRedirects(urllib.request.HTTPRedirectHandler):
    """Follow redirects only within the main website; refuse before requesting."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not _allowed(newurl):
            raise urllib.error.HTTPError(newurl, code, "redirect off the main website refused", headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_robots: urllib.robotparser.RobotFileParser | None = None


def robots_allows(url: str) -> bool:
    global _robots
    if _robots is None:
        parser = urllib.robotparser.RobotFileParser()
        parser.set_url(config.BASE_URL + "/robots.txt")
        try:
            parser.read()
        except Exception:
            parser.allow_all = True
        _robots = parser
    return _robots.can_fetch(config.USER_AGENT, url)


def fetch(url: str) -> FetchResult:
    if not _allowed(url):
        return FetchResult(None, "", url, "host not allowed")
    if not robots_allows(url):
        return FetchResult(None, "", url, "disallowed by robots.txt")
    opener = urllib.request.build_opener(SameSiteRedirects())
    opener.addheaders = [("User-Agent", config.USER_AGENT)]
    try:
        with opener.open(url, timeout=config.REQUEST_TIMEOUT) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            final = resp.geturl()
            if not _allowed(final):
                return FetchResult(None, "", final, "redirected off the main website")
            return FetchResult(resp.status, body, final, None)
    except urllib.error.HTTPError as exc:
        return FetchResult(exc.code, "", url, f"HTTPError {exc.code}")
    except Exception as exc:  # timeout, DNS, connection refused …
        return FetchResult(None, "", url, str(exc) or type(exc).__name__)


def polite_fetcher():
    """A fetch function that waits REQUEST_PAUSE_S between requests."""
    last = [0.0]

    def _fetch(url: str) -> FetchResult:
        wait = config.REQUEST_PAUSE_S - (time.monotonic() - last[0])
        if wait > 0:
            time.sleep(wait)
        try:
            return fetch(url)
        finally:
            last[0] = time.monotonic()

    return _fetch
