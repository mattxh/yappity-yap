import types

from app import cleanup as cleanup_mod
from app.__main__ import App


def _fake_app(enabled=True, dictionary=None):
    return types.SimpleNamespace(
        cfg={"cleanup": {"enabled": enabled, "model": "m", "style": "balanced",
                          "dictionary": dictionary or []}},
        provider=types.SimpleNamespace(api_key="k", base_url="http://x"),
    )


def test_maybe_cleanup_disabled_returns_raw(monkeypatch):
    called = []
    monkeypatch.setattr(cleanup_mod, "clean", lambda *a, **k: called.append(1) or "X")
    assert App._maybe_cleanup(_fake_app(enabled=False), "raw text", "auto") == "raw text"
    assert called == []


def test_maybe_cleanup_enabled_calls_clean(monkeypatch):
    seen = {}

    def fake_clean(text, **kw):
        seen.update(text=text, **kw)
        return "CLEANED"

    monkeypatch.setattr(cleanup_mod, "clean", fake_clean)
    out = App._maybe_cleanup(_fake_app(dictionary=["Foo"]), "raw text", "zh")
    assert out == "CLEANED"
    assert seen["text"] == "raw text"
    assert seen["model"] == "m"
    assert seen["api_key"] == "k"
    assert seen["base_url"] == "http://x"
    assert seen["dictionary"] == ["Foo"]
    assert seen["language"] == "zh"


def test_maybe_cleanup_falls_back_to_raw_on_error(monkeypatch):
    def boom(*a, **k):
        raise cleanup_mod.CleanupError("nope")

    monkeypatch.setattr(cleanup_mod, "clean", boom)
    assert App._maybe_cleanup(_fake_app(), "raw text", "auto") == "raw text"


def test_maybe_cleanup_empty_text_returns_raw(monkeypatch):
    called = []
    monkeypatch.setattr(cleanup_mod, "clean", lambda *a, **k: called.append(1) or "X")
    assert App._maybe_cleanup(_fake_app(), "   ", "auto") == "   "
    assert called == []


def test_build_transcription_prompt(monkeypatch):
    fake = types.SimpleNamespace(cfg={"cleanup": {"dictionary": ["Foo", "Bar"]}})
    # zh adds the Traditional prompt AND the vocabulary line
    p_zh = App._build_transcription_prompt(fake, "zh")
    assert "繁體" in p_zh
    assert "Foo" in p_zh and "Bar" in p_zh
    # auto with empty dictionary -> None
    fake_empty = types.SimpleNamespace(cfg={"cleanup": {"dictionary": []}})
    assert App._build_transcription_prompt(fake_empty, "auto") is None
