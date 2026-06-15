import pytest

from app import cleanup
from app.cleanup import CleanupError, build_messages, clean


class FakeResponse:
    def __init__(self, status_code=200, content="cleaned text", payload=None, text=""):
        self.status_code = status_code
        self._payload = payload if payload is not None else {
            "choices": [{"message": {"content": content}}]
        }
        self.text = text or "resp"

    def json(self):
        return self._payload


def _capture_post(monkeypatch, response):
    calls = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        calls.update(url=url, headers=headers, json=json, timeout=timeout)
        return response

    monkeypatch.setattr("app.cleanup.requests.post", fake_post)
    return calls


def test_build_messages_balanced_includes_rules_and_text():
    msgs = build_messages("hi there", style="balanced", dictionary=[], language="auto")
    assert msgs[0]["role"] == "system"
    assert "filler" in msgs[0]["content"]
    assert "Never translate" in msgs[0]["content"]
    assert msgs[1] == {"role": "user", "content": "hi there"}


def test_build_messages_dictionary_only_when_present():
    without = build_messages("x", style="balanced", dictionary=[], language="auto")
    assert "Spell these names" not in without[0]["content"]
    with_terms = build_messages("x", style="balanced",
                                dictionary=["Adithya", "git diff"], language="auto")
    assert "Adithya" in with_terms[0]["content"]
    assert "git diff" in with_terms[0]["content"]


def test_build_messages_language_hint():
    zh = build_messages("x", style="balanced", dictionary=[], language="zh")
    assert "Traditional Chinese" in zh[0]["content"]
    auto = build_messages("x", style="balanced", dictionary=[], language="auto")
    # auto must not pin a language ("The text is in ...")
    assert "The text is in" not in auto[0]["content"]


def test_clean_success(monkeypatch):
    calls = _capture_post(monkeypatch, FakeResponse(content="Hello, world."))
    out = clean("hello world", model="gpt-4o-mini", api_key="sk-x",
                base_url="https://api.openai.com/v1")
    assert out == "Hello, world."
    assert calls["url"] == "https://api.openai.com/v1/chat/completions"
    assert calls["headers"]["Authorization"] == "Bearer sk-x"
    assert calls["json"]["model"] == "gpt-4o-mini"
    assert calls["json"]["temperature"] == 0


def test_clean_strips_one_pair_of_wrapping_quotes(monkeypatch):
    _capture_post(monkeypatch, FakeResponse(content='"Quoted output"'))
    assert clean("x", model="m", api_key="k", base_url="u") == "Quoted output"


def test_clean_keeps_inner_quotes(monkeypatch):
    _capture_post(monkeypatch, FakeResponse(content='He said "hi" to me'))
    assert clean("x", model="m", api_key="k", base_url="u") == 'He said "hi" to me'


def test_clean_empty_input_makes_no_call(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("should not call API for empty text")

    monkeypatch.setattr("app.cleanup.requests.post", boom)
    assert clean("   ", model="m", api_key="k", base_url="u") == ""


def test_clean_missing_key_raises_without_call(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("should not call API without key")

    monkeypatch.setattr("app.cleanup.requests.post", boom)
    with pytest.raises(CleanupError):
        clean("hi", model="m", api_key="", base_url="u")


def test_clean_http_error_raises(monkeypatch):
    _capture_post(monkeypatch, FakeResponse(status_code=500, text="boom"))
    with pytest.raises(CleanupError):
        clean("hi", model="m", api_key="k", base_url="u")


def test_clean_network_error_raises(monkeypatch):
    import requests as real_requests

    def fake_post(*a, **k):
        raise real_requests.ConnectionError("no net")

    monkeypatch.setattr("app.cleanup.requests.post", fake_post)
    with pytest.raises(CleanupError):
        clean("hi", model="m", api_key="k", base_url="u")
