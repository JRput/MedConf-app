import extractors.eha_congress as eha


def _ext():
    return eha.EhaCongressExtractor.__new__(eha.EhaCongressExtractor)


def test_get_sends_bot_agent_and_browser(monkeypatch):
    calls = []

    def fake(url, **kw):
        calls.append((url, kw))
        return "x" * 600

    monkeypatch.setattr(eha, "fetch_html", fake)
    e = _ext()
    e.browser = "BR"
    assert e._get("https://ehaweb.org/a") == "x" * 600
    assert calls[0][1]["headers"]["User-Agent"] == "Mozilla/5.0 (compatible; MedConfBot)"
    assert calls[0][1]["browser"] == "BR"


def test_get_returns_none_after_short_bodies(monkeypatch):
    n = []
    monkeypatch.setattr(eha, "fetch_html", lambda url, **kw: n.append(1) or "short")
    monkeypatch.setattr(eha.time, "sleep", lambda s: None)
    assert _ext()._get("https://ehaweb.org/a", tries=3) is None
    assert len(n) == 3
