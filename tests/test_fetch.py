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
