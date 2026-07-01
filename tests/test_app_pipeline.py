import types

import pytest

from app import cleanup as cleanup_mod
from app.__main__ import App, _shorten, _parse_words


def test_parse_words_splits_on_commas_and_newlines():
    assert _parse_words("Claude, OpenAI\nAnthropic") == ["Claude", "OpenAI", "Anthropic"]


def test_parse_words_keeps_multiword_terms_and_dedups():
    # spaces are NOT separators (so 'git diff' stays one entry); dedup is case-insensitive
    assert _parse_words("git diff, git diff\nGIT DIFF") == ["git diff"]


def test_parse_words_handles_cjk_separators():
    assert _parse_words("奇鋐、許勇，台積電") == ["奇鋐", "許勇", "台積電"]


def test_shorten_collapses_whitespace_and_keeps_short_text():
    assert _shorten("  make   this  formal ") == "make this formal"


def test_shorten_truncates_long_text_with_ellipsis():
    out = _shorten("turn this into a long bulleted list of every single item we discussed", n=20)
    assert len(out) <= 20
    assert out.endswith("…")


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


def test_maybe_cleanup_reverts_unsupported_script(monkeypatch):
    # cleanup must never turn English/Chinese into Korean etc.
    monkeypatch.setattr(cleanup_mod, "clean", lambda *a, **k: "안녕하세요")
    assert App._maybe_cleanup(_fake_app(), "hello there my friend", "auto") \
        == "hello there my friend"


def _fake_learn_app(tmp_path):
    return types.SimpleNamespace(
        cfg={"cleanup": {"dictionary": [], "auto_learned": []}, "learn": {"min_ratio": 0.6}},
        cfg_path=tmp_path / "config.json",
        notifier=types.SimpleNamespace(toast=lambda *a, **k: None),
        t=lambda key, **k: key,
        _just_learned=None,
    )


def test_learn_from_selection_adds_selected_term(tmp_path):
    # 'add to dictionary' adds the selected term directly.
    fake = _fake_learn_app(tmp_path)
    App._learn_from_selection(fake, "Adithya")
    assert "Adithya" in fake.cfg["cleanup"]["dictionary"]
    assert "Adithya" in fake.cfg["cleanup"]["auto_learned"]
    assert fake._just_learned == ["Adithya"]


def test_learn_from_selection_ignores_a_sentence(tmp_path):
    fake = _fake_learn_app(tmp_path)
    App._learn_from_selection(fake, "this is a whole sentence not a dictionary term")
    assert fake.cfg["cleanup"]["dictionary"] == []
    assert fake._just_learned is None


def test_looks_like_term():
    from app.__main__ import _looks_like_term
    assert _looks_like_term("Adithya")
    assert _looks_like_term("git diff")
    assert _looks_like_term("奇鋐")
    assert not _looks_like_term("this is a whole sentence that is clearly not a term")
    assert not _looks_like_term("12345")   # no letters
    assert not _looks_like_term("")


def test_ensure_api_key_no_prompt_when_key_present(monkeypatch):
    import app.__main__ as m
    monkeypatch.setattr(m, "get_api_key", lambda cfg, p: "sk-existing")
    monkeypatch.setattr(m.prompt, "ask_words",
                        lambda *a, **k: pytest.fail("must not prompt when a key exists"))
    assert m._ensure_api_key({"provider": "openai"}) is True


def test_ensure_api_key_saves_entered_openai_key(monkeypatch):
    import app.__main__ as m
    monkeypatch.setattr(m, "get_api_key", lambda cfg, p: "")
    monkeypatch.setattr(m.config_mod, "get_cleanup_api_key", lambda cfg: "")
    monkeypatch.setattr(m.prompt, "ask_words", lambda *a, **k: "  sk-newkey \n")
    monkeypatch.setattr(m.config_mod, "save_config", lambda *a, **k: None)
    cfg = {"provider": "openai", "providers": {}, "cleanup": {}}
    assert m._ensure_api_key(cfg) is True
    assert cfg["providers"]["openai"]["api_key"] == "sk-newkey"


def test_import_words_reads_file_dedups_and_adds(monkeypatch, tmp_path):
    import app.__main__ as m
    f = tmp_path / "words.txt"
    f.write_text("Adithya\ngit diff\n奇鋐\nadithya\n\n", encoding="utf-8")
    monkeypatch.setattr(m.prompt, "ask_open_file", lambda *a, **k: str(f))
    monkeypatch.setattr(m.config_mod, "save_config", lambda *a, **k: None)
    toasts = []
    fake = types.SimpleNamespace(
        cfg={"cleanup": {"dictionary": [], "auto_learned": []}},
        cfg_path=tmp_path / "config.json",
        notifier=types.SimpleNamespace(toast=lambda msg, **k: toasts.append(msg)),
        t=lambda key, **k: key,
    )
    fake._add_words_and_report = lambda words: m.App._add_words_and_report(fake, words)
    m.App.import_words(fake)
    # one per line, spaces kept ("git diff"), case-insensitive dedup ("adithya" dropped)
    assert fake.cfg["cleanup"]["dictionary"] == ["Adithya", "git diff", "奇鋐"]


def test_import_words_cancelled_does_nothing(monkeypatch):
    import app.__main__ as m
    monkeypatch.setattr(m.prompt, "ask_open_file", lambda *a, **k: "")
    fake = types.SimpleNamespace(
        _add_words_and_report=lambda words: pytest.fail("should not add on cancel"),
        t=lambda key, **k: key)
    m.App.import_words(fake)   # no exception, no add


def test_run_command_add_to_dictionary_routes_to_learn(monkeypatch):
    # regression: _run_command called _learn_from_selection with a stale extra arg,
    # crashing every 'add to dictionary' as 'transcription failed'.
    import app.__main__ as m
    monkeypatch.setattr(m.inject, "capture_selection", lambda: "Adithya")
    monkeypatch.setattr(m.uia, "read_selected_text", lambda: None)
    monkeypatch.setattr(m, "beep", lambda *a, **k: None)
    seen = {}
    fake = types.SimpleNamespace(
        cfg={"beeps": False},
        notifier=types.SimpleNamespace(toast=lambda *a, **k: None),
        _transcribe_with_retry=lambda wav, language, prompt: "add to dictionary",
        _learn_from_selection=lambda selection: seen.__setitem__("sel", selection),
    )
    App._run_command(fake, b"x" * 200)
    assert seen.get("sel") == "Adithya"


def test_copy_recent_copies_to_clipboard(monkeypatch):
    from app import inject as inject_mod
    copied, toasts = {}, []
    monkeypatch.setattr(inject_mod, "set_clipboard", lambda t: copied.update(t=t) or True)
    fake = types.SimpleNamespace(
        notifier=types.SimpleNamespace(toast=lambda msg, **k: toasts.append(msg)),
        t=lambda key, **k: key,
    )
    App.copy_recent(fake, "hello world")
    assert copied["t"] == "hello world"
    assert toasts == ["copied_to_clipboard"]


def test_offer_transcript_shows_copyable_overlay(monkeypatch):
    seen = {}
    fake = types.SimpleNamespace(
        cfg={"show_overlay": True},
        overlay=types.SimpleNamespace(
            transcript=lambda text, label, cb: seen.update(text=text, label=label, cb=cb)),
        notifier=types.SimpleNamespace(toast=lambda *a, **k: seen.update(toasted=True)),
        t=lambda key, **k: key,
    )
    App._offer_transcript(fake, "hello world this is the dictated transcript")
    assert "hello world" in seen["text"]
    assert seen["label"] == "copy"
    assert callable(seen["cb"])          # Copy button copies the full text on demand
    assert "toasted" not in seen          # overlay shown, no toast


def test_offer_transcript_without_overlay_copies_and_toasts(monkeypatch):
    from app import inject as inject_mod
    copied, toasts = {}, []
    monkeypatch.setattr(inject_mod, "set_clipboard", lambda t: copied.update(t=t))
    fake = types.SimpleNamespace(
        cfg={"show_overlay": False},
        overlay=types.SimpleNamespace(
            transcript=lambda *a, **k: pytest.fail("overlay disabled; must not show")),
        notifier=types.SimpleNamespace(toast=lambda msg, **k: toasts.append(msg)),
        t=lambda key, **k: key,
    )
    App._offer_transcript(fake, "hello")
    assert copied["t"] == "hello"
    assert toasts == ["paste_failed_copied"]


def _dictation_fake(calls):
    return types.SimpleNamespace(
        cfg={"language": "auto", "snippets": {}, "spoken_formatting": False,
             "append_space": False, "notify_on_insert": False, "show_overlay": True},
        notifier=types.SimpleNamespace(toast=lambda *a, **k: None),
        _consume_pending_learn=lambda: None,
        _transcribe_with_retry=lambda wav, language, prompt: "hello",
        _maybe_cleanup=lambda text, lang: text,
        _estimate_cost=lambda dur: 0.0,
        _transcription_model=lambda: "m",
        on_history_changed=lambda: None,
        _set_pending_learn=lambda final: calls.__setitem__("pending", final),
        _offer_transcript=lambda final: calls.__setitem__("offered", final),
    )


def _patch_dictation(monkeypatch, tmp_path, calls, editable):
    import app.__main__ as m
    monkeypatch.setattr(m, "LAST_RECORDING", tmp_path / "lr.wav")
    monkeypatch.setattr(m.uia, "focused_is_text_input", lambda: editable)
    monkeypatch.setattr(m.inject, "insert_text",
                        lambda final, **k: calls.__setitem__("inserted", final))
    monkeypatch.setattr(m.history, "append_entry", lambda *a, **k: None)


def test_transcribe_pastes_when_focus_is_text_field(monkeypatch, tmp_path):
    # regression: this path was uncovered and a wrong module reference (inject vs uia)
    # crashed every dictation as "transcription failed".
    calls = {}
    _patch_dictation(monkeypatch, tmp_path, calls, editable=True)
    App._transcribe_and_insert(_dictation_fake(calls), b"x" * 200)
    assert calls.get("inserted") == "hello"
    assert "offered" not in calls


def test_transcribe_offers_copy_when_focus_not_text_field(monkeypatch, tmp_path):
    calls = {}
    _patch_dictation(monkeypatch, tmp_path, calls, editable=False)
    App._transcribe_and_insert(_dictation_fake(calls), b"x" * 200)
    assert calls.get("offered") == "hello"
    assert "inserted" not in calls


def test_transcribe_retries_in_english_on_unsupported_script(monkeypatch, tmp_path):
    # auto-detect returned Korean -> re-transcribe pinned to English
    calls = {}
    _patch_dictation(monkeypatch, tmp_path, calls, editable=True)
    fake = _dictation_fake(calls)
    fake._transcribe_with_retry = lambda wav, language, prompt: (
        "안녕하세요" if language is None else "hello")
    App._transcribe_and_insert(fake, b"x" * 200)
    assert calls.get("inserted") == "hello"


def test_transcribe_sends_no_prompt(monkeypatch, tmp_path):
    # the dictionary must NOT be sent as the transcription prompt — a Chinese vocabulary
    # prompt biased the model into translating English speech to Chinese.
    calls = {}
    _patch_dictation(monkeypatch, tmp_path, calls, editable=True)
    fake = _dictation_fake(calls)
    seen = {}
    fake._transcribe_with_retry = lambda wav, language, prompt: (
        seen.update(language=language, prompt=prompt) or "hello")
    App._transcribe_and_insert(fake, b"x" * 200)
    assert seen["prompt"] is None
