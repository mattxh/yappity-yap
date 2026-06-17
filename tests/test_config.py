import json

from app import config


def test_defaults_when_file_missing(tmp_path):
    cfg = config.load_config(tmp_path / "nope.json")
    assert cfg["provider"] == "openai"
    assert cfg["tap_threshold_ms"] == 400
    assert cfg["providers"]["openai"]["model"] == "gpt-4o-transcribe"


def test_partial_file_deep_merges(tmp_path):
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"language": "zh", "providers": {"openai": {"api_key": "sk-x"}}}), encoding="utf-8")
    cfg = config.load_config(p)
    assert cfg["language"] == "zh"
    assert cfg["providers"]["openai"]["api_key"] == "sk-x"
    assert cfg["providers"]["openai"]["model"] == "gpt-4o-transcribe"  # default survives
    assert cfg["providers"]["groq"]["model"] == "whisper-large-v3-turbo"


def test_api_key_env_fallback(tmp_path, monkeypatch):
    cfg = config.load_config(tmp_path / "nope.json")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-env")
    assert config.get_api_key(cfg, "openai") == "sk-env"
    cfg["providers"]["openai"]["api_key"] = "sk-file"
    assert config.get_api_key(cfg, "openai") == "sk-file"  # file wins


def test_save_round_trip(tmp_path):
    p = tmp_path / "config.json"
    cfg = config.load_config(p)
    cfg["language"] = "en"
    config.save_config(cfg, p)
    assert config.load_config(p)["language"] == "en"


def test_bad_json_falls_back_to_defaults(tmp_path):
    p = tmp_path / "config.json"
    p.write_text("{not json", encoding="utf-8")
    cfg = config.load_config(p)
    assert cfg["provider"] == "openai"


def test_add_word_appends_new():
    cfg = {"cleanup": {"dictionary": []}}
    assert config.add_word(cfg, "Anthropic") is True
    assert cfg["cleanup"]["dictionary"] == ["Anthropic"]


def test_add_word_dedup_case_insensitive():
    cfg = {"cleanup": {"dictionary": ["Anthropic"]}}
    assert config.add_word(cfg, "  anthropic ") is False
    assert cfg["cleanup"]["dictionary"] == ["Anthropic"]


def test_add_word_empty_is_noop():
    cfg = {}
    assert config.add_word(cfg, "   ") is False
    assert config.add_word(cfg, "") is False


def test_add_words_reports_added_and_skipped():
    cfg = {"cleanup": {"dictionary": ["Anthropic"]}}
    added, skipped = config.add_words(cfg, ["Claude", "anthropic", "OpenAI"])
    assert added == ["Claude", "OpenAI"]
    assert skipped == ["anthropic"]      # already present (case-insensitive)
    assert cfg["cleanup"]["dictionary"] == ["Anthropic", "Claude", "OpenAI"]


def test_add_words_skips_blanks():
    cfg = {"cleanup": {"dictionary": []}}
    added, skipped = config.add_words(cfg, ["  ", "", "Foo"])
    assert added == ["Foo"]
    assert skipped == []


def test_remove_word_from_dictionary_and_auto():
    cfg = {"cleanup": {"dictionary": ["Anthropic", "Adithya"], "auto_learned": ["Adithya"]}}
    assert config.remove_word(cfg, "adithya") is True   # case-insensitive
    assert cfg["cleanup"]["dictionary"] == ["Anthropic"]
    assert cfg["cleanup"]["auto_learned"] == []


def test_remove_word_absent_is_noop():
    cfg = {"cleanup": {"dictionary": ["Anthropic"]}}
    assert config.remove_word(cfg, "nope") is False
    assert cfg["cleanup"]["dictionary"] == ["Anthropic"]


def test_cleanup_defaults_and_merge(tmp_path):
    import json as _json

    cfg = config.load_config(tmp_path / "nope.json")
    assert cfg["cleanup"]["enabled"] is True
    assert cfg["cleanup"]["model"] == "gpt-4o-mini"
    assert cfg["cleanup"]["style"] == "balanced"
    assert cfg["cleanup"]["dictionary"] == []

    p = tmp_path / "config.json"
    p.write_text(_json.dumps({"cleanup": {"dictionary": ["Adithya"]}}), encoding="utf-8")
    merged = config.load_config(p)
    assert merged["cleanup"]["dictionary"] == ["Adithya"]      # user value kept
    assert merged["cleanup"]["enabled"] is True                # default filled
    assert merged["cleanup"]["model"] == "gpt-4o-mini"          # default filled
