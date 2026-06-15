import json

import pytest

from app.providers import create_provider
from app.providers.base import TranscriptionError
from app.providers.openai_provider import OpenAIProvider
from app.providers.groq_provider import GroqProvider


class FakeResponse:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text or json.dumps(self._payload)

    def json(self):
        return self._payload


def _capture_post(monkeypatch, response):
    calls = {}

    def fake_post(url, headers=None, data=None, files=None, timeout=None):
        calls.update(url=url, headers=headers, data=data, files=files, timeout=timeout)
        return response

    monkeypatch.setattr("app.providers.openai_provider.requests.post", fake_post)
    return calls


def test_transcribe_success_builds_request(monkeypatch):
    calls = _capture_post(monkeypatch, FakeResponse(payload={"text": " hello "}))
    p = OpenAIProvider(api_key="sk-test", model="gpt-4o-mini-transcribe")
    out = p.transcribe(b"RIFFwav", language="en", prompt=None)
    assert out == "hello"
    assert calls["url"] == "https://api.openai.com/v1/audio/transcriptions"
    assert calls["headers"]["Authorization"] == "Bearer sk-test"
    assert calls["data"]["model"] == "gpt-4o-mini-transcribe"
    assert calls["data"]["language"] == "en"
    assert calls["files"]["file"][1] == b"RIFFwav"


def test_auto_language_omits_param_and_prompt_included(monkeypatch):
    calls = _capture_post(monkeypatch, FakeResponse(payload={"text": "hi"}))
    p = OpenAIProvider(api_key="sk-test")
    p.transcribe(b"x", language=None, prompt="請用繁體中文輸出。")
    assert "language" not in calls["data"]
    assert calls["data"]["prompt"] == "請用繁體中文輸出。"


def test_server_error_is_retryable(monkeypatch):
    _capture_post(monkeypatch, FakeResponse(status_code=500, text="boom"))
    p = OpenAIProvider(api_key="sk-test")
    with pytest.raises(TranscriptionError) as ei:
        p.transcribe(b"x", None, None)
    assert ei.value.retryable is True


def test_auth_error_not_retryable(monkeypatch):
    _capture_post(monkeypatch, FakeResponse(status_code=401, text="bad key"))
    p = OpenAIProvider(api_key="sk-bad")
    with pytest.raises(TranscriptionError) as ei:
        p.transcribe(b"x", None, None)
    assert ei.value.retryable is False


def test_network_error_is_retryable(monkeypatch):
    import requests as real_requests

    def fake_post(*a, **k):
        raise real_requests.ConnectionError("no net")

    monkeypatch.setattr("app.providers.openai_provider.requests.post", fake_post)
    p = OpenAIProvider(api_key="sk-test")
    with pytest.raises(TranscriptionError) as ei:
        p.transcribe(b"x", None, None)
    assert ei.value.retryable is True


def test_missing_key_raises_immediately():
    p = OpenAIProvider(api_key="")
    with pytest.raises(TranscriptionError) as ei:
        p.transcribe(b"x", None, None)
    assert ei.value.retryable is False


def test_groq_base_url_and_factory(monkeypatch):
    calls = _capture_post(monkeypatch, FakeResponse(payload={"text": "ok"}))
    cfg = {
        "provider": "groq",
        "providers": {
            "openai": {"api_key": "", "model": "gpt-4o-mini-transcribe"},
            "groq": {"api_key": "gsk-test", "model": "whisper-large-v3-turbo"},
        },
    }
    p = create_provider(cfg)
    assert isinstance(p, GroqProvider)
    p.transcribe(b"x", None, None)
    assert calls["url"] == "https://api.groq.com/openai/v1/audio/transcriptions"
    assert calls["data"]["model"] == "whisper-large-v3-turbo"


def test_factory_unknown_provider_raises():
    with pytest.raises(ValueError):
        create_provider({"provider": "nope", "providers": {}})
