import pytest

from app import command
from app.command import CommandError, build_messages, transform


class FakeResponse:
    def __init__(self, status_code=200, content="done", text=""):
        self.status_code = status_code
        self._content = content
        self.text = text or "resp"

    def json(self):
        return {"choices": [{"message": {"content": self._content}}]}


def test_build_messages_has_selection_instruction_and_constraint():
    msgs = build_messages("the quick brown fox", "make it formal")
    sys = msgs[0]["content"].lower()
    assert "only" in sys                       # output-only constraint
    joined = " ".join(m["content"] for m in msgs)
    assert "the quick brown fox" in joined
    assert "make it formal" in joined


def test_transform_success(monkeypatch):
    calls = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        calls.update(url=url, json=json)
        return FakeResponse(content="The quick brown fox.")

    monkeypatch.setattr("app.net.post", fake_post)
    out = transform("the quick brown fox", "add a period", model="m",
                    api_key="k", base_url="https://api.openai.com/v1")
    assert out == "The quick brown fox."
    assert calls["url"] == "https://api.openai.com/v1/chat/completions"


def test_transform_noop_when_empty(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("should not call API")

    monkeypatch.setattr("app.net.post", boom)
    assert transform("", "do stuff", model="m", api_key="k", base_url="u") == ""
    assert transform("sel", "  ", model="m", api_key="k", base_url="u") == "sel"


def test_transform_http_error_raises(monkeypatch):
    monkeypatch.setattr("app.net.post",
                        lambda *a, **k: FakeResponse(status_code=500, text="boom"))
    with pytest.raises(CommandError):
        transform("sel", "do", model="m", api_key="k", base_url="u")
