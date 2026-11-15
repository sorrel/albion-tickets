"""Polite, read-only HTTP GET of the club's main website — and nothing else.

One request at a time, honest User-Agent, no cookies kept, no JavaScript.
Rate limits and passing server errors are retried with backoff (see fetch).
Never raises: failures come back as a FetchResult with an error string.
Any host other than the main website is refused before the network is touched,
so the protected ticket site can never be requested by this tool.
"""
import time
import urllib.error
import urllib.request
import urllib.robotparser
from dataclasses import dataclass
from functools import cache
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


@cache
def _robots() -> urllib.robotparser.RobotFileParser:
    """The site's robots.txt, read once per run (unreadable: everything allowed)."""
    parser = urllib.robotparser.RobotFileParser(config.BASE_URL + "/robots.txt")
    try:
        parser.read()
    except Exception:
        parser.allow_all = True
    return parser


def robots_allows(url: str) -> bool:
    return _robots().can_fetch(config.USER_AGENT, url)


BACKOFF_S = (5, 15, 45)  # waits between tries; one more try than waits
RETRY_AFTER_CAP_S = 120
RETRY_STATUSES = {429, 500, 502, 503, 504}
_PERMANENT = ("host not allowed", "redirected off the main website", "disallowed by robots.txt")
_sleep = time.sleep


def _retry_after(exc: urllib.error.HTTPError) -> float | None:
    value = exc.headers.get("Retry-After") if exc.headers else None
    try:
        return float(value) if value is not None else None
    except ValueError:  # an HTTP date: fall back to our own backoff
        return None


def _attempt(url: str) -> tuple[FetchResult, float | None]:
    """One GET. Returns the result and any Retry-After the server asked for."""
    opener = urllib.request.build_opener(SameSiteRedirects())
    opener.addheaders = [("User-Agent", config.USER_AGENT)]
    try:
        with opener.open(url, timeout=config.REQUEST_TIMEOUT) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            final = resp.geturl()
            if not _allowed(final):
                return FetchResult(None, "", final, "redirected off the main website"), None
            return FetchResult(resp.status, body, final, None), None
    except urllib.error.HTTPError as exc:
        return FetchResult(exc.code, "", url, f"HTTPError {exc.code}"), _retry_after(exc)
    except Exception as exc:  # timeout, DNS, connection refused …
        return FetchResult(None, "", url, str(exc) or type(exc).__name__), None


def _transient(r: FetchResult) -> bool:
    if r.status in RETRY_STATUSES:
        return True
    return r.status is None and r.error is not None and r.error not in _PERMANENT


def fetch(url: str) -> FetchResult:
    """GET with backoff: 429, 5xx and network failures are retried, honouring Retry-After."""
    if not _allowed(url):
        return FetchResult(None, "", url, "host not allowed")
    if not robots_allows(url):
        return FetchResult(None, "", url, "disallowed by robots.txt")
    tries = len(BACKOFF_S) + 1
    for i in range(tries):
        result, retry_after = _attempt(url)
        if not _transient(result):
            return result
        if i == tries - 1:
            break
        wait = BACKOFF_S[i] if retry_after is None else max(0.0, retry_after)
        _sleep(min(wait, RETRY_AFTER_CAP_S))
    return FetchResult(result.status, result.body, result.final_url, f"{result.error} (after {tries} tries)")


def polite_fetcher():
    """A fetch function that waits REQUEST_PAUSE_S between requests."""
    last = 0.0

    def _fetch(url: str) -> FetchResult:
        nonlocal last
        wait = config.REQUEST_PAUSE_S - (time.monotonic() - last)
        if wait > 0:
            time.sleep(wait)
        try:
            return fetch(url)
        finally:
            last = time.monotonic()

    return _fetch
