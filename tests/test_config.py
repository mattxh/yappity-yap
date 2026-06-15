import json

from app import config


def test_defaults_when_file_missing(tmp_path):
    cfg = config.load_config(tmp_path / "nope.json")
    assert cfg["provider"] == "openai"
    assert cfg["tap_threshold_ms"] == 400
    assert cfg["providers"]["openai"]["model"] == "gpt-4o-mini-transcribe"


def test_partial_file_deep_merges(tmp_path):
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"language": "zh", "providers": {"openai": {"api_key": "sk-x"}}}), encoding="utf-8")
    cfg = config.load_config(p)
    assert cfg["language"] == "zh"
    assert cfg["providers"]["openai"]["api_key"] == "sk-x"
    assert cfg["providers"]["openai"]["model"] == "gpt-4o-mini-transcribe"  # default survives
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
