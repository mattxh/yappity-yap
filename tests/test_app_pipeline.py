import types

from app import cleanup as cleanup_mod
from app.__main__ import App


def _fake_app(enabled=True, dictionary=None):
    return types.SimpleNamespace(
        cfg={
            "cleanup": {"enabled": enabled, "model": "m", "style": "balanced",
                        "dictionary": dictionary or [], "app_aware": False,
                        "base_url": "http://cleanup", "api_key": "ck"},
            "providers": {"openai": {"api_key": "openai-key"}},
        },
        # transcription provider is irrelevant to cleanup now (decoupled)
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
    assert seen["api_key"] == "ck"            # cleanup's own key, not the provider's
    assert seen["base_url"] == "http://cleanup"  # cleanup's own endpoint
    assert seen["dictionary"] == ["Foo"]
    assert seen["language"] == "zh"


def test_maybe_cleanup_key_falls_back_to_openai(monkeypatch):
    seen = {}
    monkeypatch.setattr(cleanup_mod, "clean", lambda text, **kw: seen.update(kw) or "C")
    # No explicit cleanup.api_key -> resolves to providers.openai.api_key
    fake = types.SimpleNamespace(
        cfg={
            "cleanup": {"enabled": True, "model": "m", "style": "balanced",
                        "dictionary": [], "base_url": "https://api.openai.com/v1",
                        "api_key": ""},
            "providers": {"openai": {"api_key": "openai-key"}},
        },
        provider=types.SimpleNamespace(api_key="k", base_url="http://x"),
    )
    App._maybe_cleanup(fake, "raw", "auto")
    assert seen["api_key"] == "openai-key"


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


def _fake_learn_app(tmp_path, last_dictation):
    return types.SimpleNamespace(
        cfg={"cleanup": {"dictionary": [], "auto_learned": []}, "learn": {"min_ratio": 0.6}},
        cfg_path=tmp_path / "config.json",
        notifier=types.SimpleNamespace(toast=lambda *a, **k: None),
        t=lambda key, **k: key,
        _last_dictation=last_dictation,
        _just_learned=None,
    )


def test_learn_from_selection_adds_corrected_word(tmp_path):
    fake = _fake_learn_app(tmp_path, "email aditya today")
    App._learn_from_selection(fake, "email Adithya today")   # user fixed the name
    assert "Adithya" in fake.cfg["cleanup"]["dictionary"]
    assert "Adithya" in fake.cfg["cleanup"]["auto_learned"]
    assert fake._just_learned == ["Adithya"]


def test_learn_from_selection_no_change_learns_nothing(tmp_path):
    fake = _fake_learn_app(tmp_path, "hello world")
    App._learn_from_selection(fake, "hello world")
    assert fake.cfg["cleanup"]["dictionary"] == []
    assert fake._just_learned is None


def test_build_transcription_prompt(monkeypatch):
    fake = types.SimpleNamespace(cfg={"cleanup": {"dictionary": ["Foo", "Bar"]}})
    # vocabulary is included, but NO forced-Chinese directive (that translated English)
    p_zh = App._build_transcription_prompt(fake, "zh")
    assert "Foo" in p_zh and "Bar" in p_zh
    assert "繁體" not in p_zh
    # empty dictionary -> nothing to send, in any language
    fake_empty = types.SimpleNamespace(cfg={"cleanup": {"dictionary": []}})
    assert App._build_transcription_prompt(fake_empty, "zh") is None
    assert App._build_transcription_prompt(fake_empty, "auto") is None
