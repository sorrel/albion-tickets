import urllib.request

from albion_tickets import config, fetch


def test_ticket_site_is_refused(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("network must not be touched")

    monkeypatch.setattr(urllib.request, "build_opener", boom)
    result = fetch.fetch("https://tickets.brightonandhovealbion.com/")
    assert result.error == "host not allowed"
    assert result.status is None


def test_other_hosts_are_refused_too(monkeypatch):
    monkeypatch.setattr(urllib.request, "build_opener", lambda *a, **k: (_ for _ in ()).throw(AssertionError()))
    assert fetch.fetch("https://example.com/").error == "host not allowed"


def test_user_agent_has_no_email():
    assert "@" not in config.USER_AGENT


URL = config.BASE_URL + "/all-latest-news"


def _scripted(monkeypatch, outcomes):
    """Each outcome is (FetchResult, retry_after); returns the list of sleeps taken."""
    seq, sleeps = list(outcomes), []
    monkeypatch.setattr(fetch, "robots_allows", lambda url: True)
    monkeypatch.setattr(fetch, "_attempt", lambda url: seq.pop(0))
    monkeypatch.setattr(fetch, "_sleep", sleeps.append)
    return sleeps


def _ok():
    return fetch.FetchResult(200, "<html/>", URL, None), None


def _http(code, retry_after=None):
    return fetch.FetchResult(code, "", URL, f"HTTPError {code}"), retry_after


def test_rate_limit_waits_as_asked_then_succeeds(monkeypatch):
    sleeps = _scripted(monkeypatch, [_http(429, 7.0), _ok()])
    assert fetch.fetch(URL).ok and sleeps == [7.0]


def test_server_errors_back_off_increasingly(monkeypatch):
    sleeps = _scripted(monkeypatch, [_http(503), _http(502), _ok()])
    assert fetch.fetch(URL).ok and sleeps == [5, 15]


def test_gives_up_after_four_tries_and_says_so(monkeypatch):
    sleeps = _scripted(monkeypatch, [_http(500)] * 4)
    r = fetch.fetch(URL)
    assert not r.ok and r.status == 500 and r.error == "HTTPError 500 (after 4 tries)"
    assert sleeps == [5, 15, 45]


def test_not_found_is_not_retried(monkeypatch):
    sleeps = _scripted(monkeypatch, [_http(404)])
    assert fetch.fetch(URL).status == 404 and sleeps == []


def test_timeouts_are_retried(monkeypatch):
    sleeps = _scripted(monkeypatch, [(fetch.FetchResult(None, "", URL, "timed out"), None), _ok()])
    assert fetch.fetch(URL).ok and sleeps == [5]


def test_retry_after_is_capped(monkeypatch):
    sleeps = _scripted(monkeypatch, [_http(429, 3600.0), _ok()])
    fetch.fetch(URL)
    assert sleeps == [120]


def test_off_site_redirect_is_never_retried(monkeypatch):
    sleeps = _scripted(monkeypatch, [(fetch.FetchResult(None, "", "https://x", "redirected off the main website"), None)])
    assert fetch.fetch(URL).error == "redirected off the main website" and sleeps == []
