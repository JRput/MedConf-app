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


def test_cookie_banner_text_is_not_the_description(monkeypatch):
    """Runner DOM 2026-11-20: Cookiebot text came first and was stored as the description."""
    from extractors import eha_congress as m
    html = ("<html><body><p>Learn more about this provider</p>"
            "<p>Some of the data collected by this provider is for the purposes of personalization and measuring the effectiveness of advertising.</p>"
            "<h1>EHA2027 Congress</h1><p>June 10–13, 2027</p><p>Barcelona, Spain</p>"
            "<p>Let’s meet at EHA2027, where we connect the global hematology community.</p>"
            "<p>EHA2027 will once again offer an exceptional scientific program, featuring plenary sessions and more.</p>"
            "</body></html>")
    x = m.EhaCongressExtractor({"id": 165, "source_name": "EHA Congress"})
    monkeypatch.setattr(m.SingleCongressExtractor, "detail_from_html",
                        lambda self, h, u, sh, llm: {"description": "Learn more about this provider Some of the data collected by this provider is for the purp", "event_format": "in_person"})
    out = x.detail_from_html(html, "https://ehaweb.org/connect-network/eha2027-congress", {}, lambda p: None)
    assert out["description"].startswith("Let’s meet at EHA2027")
    assert "provider" not in out["description"]
    assert out["event_format"] == "hybrid"
