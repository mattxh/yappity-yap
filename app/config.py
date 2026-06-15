"""Load/save config.json with defaults and env-var API key fallback."""
import copy
import json
import logging
import os
from pathlib import Path

log = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = PROJECT_ROOT / "config.json"

DEFAULTS = {
    "provider": "openai",
    "providers": {
        "openai": {"api_key": "", "model": "gpt-4o-mini-transcribe"},
        "groq": {"api_key": "", "model": "whisper-large-v3-turbo"},
    },
    "hotkey": "ctrl+windows",
    "tap_threshold_ms": 400,
    "max_recording_s": 300,
    "language": "auto",       # auto | en | zh
    "ui_language": "en",      # en | zh-TW
    "input_device": None,
    "beeps": True,
    "show_overlay": True,
    "append_space": True,
}

ENV_KEYS = {"openai": "OPENAI_API_KEY", "groq": "GROQ_API_KEY"}


def _deep_merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in override.items():
        if k in out and isinstance(out[k], dict) and isinstance(v, dict):
            out[k] = _deep_merge(out[k], v)
        else:
            if k not in base:
                log.warning("config: unknown key %r", k)
            out[k] = copy.deepcopy(v)
    return out


def load_config(path: Path = CONFIG_PATH) -> dict:
    path = Path(path)
    if not path.exists():
        return copy.deepcopy(DEFAULTS)
    try:
        user = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(user, dict):
            raise ValueError("config root must be an object")
    except (ValueError, OSError) as e:
        log.error("config: failed to read %s (%s); using defaults", path, e)
        return copy.deepcopy(DEFAULTS)
    return _deep_merge(DEFAULTS, user)


def save_config(cfg: dict, path: Path = CONFIG_PATH) -> None:
    Path(path).write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def get_api_key(cfg: dict, provider: str) -> str:
    key = cfg.get("providers", {}).get(provider, {}).get("api_key", "")
    if key:
        return key
    return os.environ.get(ENV_KEYS.get(provider, ""), "")
