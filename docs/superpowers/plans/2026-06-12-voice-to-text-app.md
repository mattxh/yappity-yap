# Voice-to-Text Dictation App Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Background Windows tray app: hold/tap Win+Ctrl to record mic, transcribe via OpenAI (swappable to Groq), paste result into the active app, with guaranteed Traditional Chinese output and bilingual EN/繁中 UI.

**Architecture:** Single Python process. A low-level keyboard hook feeds a pure chord state machine (hold = push-to-talk, tap = toggle). A worker thread runs the record → transcribe → post-process → paste pipeline. pystray owns the main thread; a tkinter overlay runs on its own thread. Providers are a tiny protocol over `requests` multipart POSTs.

**Tech Stack:** Python 3.14, `keyboard`, `sounddevice` (RawInputStream — no numpy), `pystray`+`Pillow`, `pyperclip`, `opencc-python-reimplemented`, `requests`, `pytest`.

**Spec:** `docs/superpowers/specs/2026-06-12-voice-to-text-app-design.md`

**Working directory for all commands:** project root (`VoiceToText/`). Python is `python` (3.14). Run tests with `python -m pytest`.

---

### Task 1: Scaffolding, dependencies, sanity check

**Files:**
- Create: `requirements.txt`, `requirements-dev.txt`, `app/__init__.py`, `app/providers/__init__.py` (empty for now), `tests/__init__.py`, `config.example.json`, `run.bat`

- [ ] **Step 1: Create package skeleton**

Create empty files `app/__init__.py`, `tests/__init__.py`, and `app/providers/__init__.py` (empty placeholder; factory code comes in Task 5).

- [ ] **Step 2: Write requirements.txt**

```
requests>=2.32
sounddevice>=0.5
keyboard>=0.13.5
pystray>=0.19
Pillow>=10.0
pyperclip>=1.9
opencc-python-reimplemented>=0.1.7
```

And `requirements-dev.txt`:

```
-r requirements.txt
pytest>=8.0
```

- [ ] **Step 3: Install and verify imports on Python 3.14 (spec risk check)**

Run: `python -m pip install -r requirements-dev.txt`
Then: `python -c "import requests, sounddevice, keyboard, pystray, PIL, pyperclip, opencc, tkinter, winsound; print('all imports OK')"`
Expected: `all imports OK`. If a wheel fails to install on 3.14, STOP and report (spec lists fallback: python.org 3.12).

- [ ] **Step 4: Write config.example.json**

```json
{
  "provider": "openai",
  "providers": {
    "openai": { "api_key": "", "model": "gpt-4o-mini-transcribe" },
    "groq":   { "api_key": "", "model": "whisper-large-v3-turbo" }
  },
  "hotkey": "ctrl+windows",
  "tap_threshold_ms": 400,
  "max_recording_s": 300,
  "language": "auto",
  "ui_language": "en",
  "input_device": null,
  "beeps": true,
  "show_overlay": true,
  "append_space": true
}
```

- [ ] **Step 5: Write run.bat**

```bat
@echo off
cd /d "%~dp0"
start "" pythonw -m app
```

- [ ] **Step 6: Sanity-run pytest**

Run: `python -m pytest`
Expected: `no tests ran` (exit code 5 is fine at this stage).

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "chore: scaffold project, deps, example config"
```

---

### Task 2: Config loading (`app/config.py`)

**Files:**
- Create: `app/config.py`
- Test: `tests/test_config.py`

Behavior: deep-merge user file over defaults; missing file → pure defaults; env-var fallback for API keys (`OPENAI_API_KEY`, `GROQ_API_KEY`); `save_config` writes JSON (used by tray to persist language toggles).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_config.py
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_config.py -v`
Expected: FAIL / ERROR with `cannot import name 'config'` or `module 'app.config' has no attribute ...`

- [ ] **Step 3: Implement `app/config.py`**

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_config.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add app/config.py tests/test_config.py
git commit -m "feat: config loading with defaults, deep merge, env key fallback"
```

---

### Task 3: Bilingual strings (`app/i18n.py`)

**Files:**
- Create: `app/i18n.py`
- Test: `tests/test_i18n.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_i18n.py
from app import i18n


def test_translate_both_languages():
    assert i18n.tr("quit", "en") == "Quit"
    assert i18n.tr("quit", "zh-TW") == "結束"


def test_unknown_language_falls_back_to_english():
    assert i18n.tr("quit", "fr") == "Quit"


def test_missing_key_returns_key():
    assert i18n.tr("no_such_key_xyz", "en") == "no_such_key_xyz"


def test_string_tables_have_identical_keys():
    assert set(i18n.STRINGS["en"].keys()) == set(i18n.STRINGS["zh-TW"].keys())


def test_format_args():
    assert "3" in i18n.tr("auto_stopped", "en", minutes=3)
    assert "3" in i18n.tr("auto_stopped", "zh-TW", minutes=3)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_i18n.py -v`
Expected: FAIL (module missing)

- [ ] **Step 3: Implement `app/i18n.py`**

```python
"""EN / Traditional Chinese string tables for tray, overlay, notifications."""

STRINGS = {
    "en": {
        "app_name": "VoiceToText",
        "recording": "● Recording — Esc to cancel",
        "transcribing": "✍ Transcribing…",
        "ready": "Ready — hold or tap Win+Ctrl to dictate",
        "quit": "Quit",
        "language": "Language",
        "lang_auto": "Auto-detect",
        "lang_en": "English",
        "lang_zh": "中文 (Mandarin)",
        "ui_language": "UI language",
        "retry_last": "Retry last recording",
        "open_history": "Open history",
        "open_config": "Open config",
        "start_with_windows": "Start with Windows",
        "already_running": "VoiceToText is already running.",
        "err_no_key": "No API key set. Open config and add your key, then restart.",
        "err_mic": "Microphone error: {error}",
        "err_api": "Transcription failed: {error}\nAudio saved — use 'Retry last recording'.",
        "err_empty": "Nothing transcribed (no speech detected).",
        "auto_stopped": "Recording auto-stopped after {minutes} min and was transcribed.",
        "retry_none": "No saved recording to retry.",
        "done_notify": "Inserted {chars} characters.",
        "startup_on": "Will start with Windows.",
        "startup_off": "Removed from Windows startup.",
    },
    "zh-TW": {
        "app_name": "VoiceToText 語音輸入",
        "recording": "● 錄音中 — 按 Esc 取消",
        "transcribing": "✍ 轉錄中…",
        "ready": "就緒 — 按住或輕按 Win+Ctrl 開始聽寫",
        "quit": "結束",
        "language": "辨識語言",
        "lang_auto": "自動偵測",
        "lang_en": "英文",
        "lang_zh": "中文（國語）",
        "ui_language": "介面語言",
        "retry_last": "重試上次錄音",
        "open_history": "開啟歷史紀錄",
        "open_config": "開啟設定檔",
        "start_with_windows": "開機時自動啟動",
        "already_running": "VoiceToText 已在執行中。",
        "err_no_key": "尚未設定 API 金鑰。請開啟設定檔填入金鑰後重新啟動。",
        "err_mic": "麥克風錯誤：{error}",
        "err_api": "轉錄失敗：{error}\n音檔已保留 — 可用「重試上次錄音」。",
        "err_empty": "沒有辨識到語音內容。",
        "auto_stopped": "錄音已於 {minutes} 分鐘後自動停止並完成轉錄。",
        "retry_none": "沒有可重試的錄音。",
        "done_notify": "已輸入 {chars} 個字元。",
        "startup_on": "已設定開機自動啟動。",
        "startup_off": "已取消開機自動啟動。",
    },
}


def tr(key: str, ui_language: str, **fmt) -> str:
    table = STRINGS.get(ui_language) or STRINGS["en"]
    text = table.get(key) or STRINGS["en"].get(key) or key
    return text.format(**fmt) if fmt else text
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_i18n.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add app/i18n.py tests/test_i18n.py
git commit -m "feat: bilingual EN/zh-TW string tables"
```

---

### Task 4: Post-processing — Traditional Chinese + spacing (`app/postprocess.py`)

**Files:**
- Create: `app/postprocess.py`
- Test: `tests/test_postprocess.py`

Behavior: if text contains Han characters → OpenCC `s2twp` (Simplified→Traditional, Taiwan phrasing; idempotent on Traditional). Trailing space appended only when the final character is non-CJK and not CJK punctuation.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_postprocess.py
from app import postprocess as pp


def test_simplified_converted_to_traditional():
    assert pp.process("简体中文测试", append_space=True) == "簡體中文測試"


def test_traditional_unchanged():
    assert pp.process("繁體中文測試", append_space=True) == "繁體中文測試"


def test_english_gets_trailing_space():
    assert pp.process("Hello world", append_space=True) == "Hello world "


def test_english_sentence_punctuation_gets_trailing_space():
    assert pp.process("Hello world.", append_space=True) == "Hello world. "


def test_no_trailing_space_when_disabled():
    assert pp.process("Hello world", append_space=False) == "Hello world"


def test_no_trailing_space_after_cjk_punctuation():
    assert pp.process("你好。", append_space=True) == "你好。"


def test_mixed_text_converted_and_no_space_after_han():
    out = pp.process("请 email 我", append_space=True)
    assert out == "請 email 我 "  # ends with latin word -> space; 请->請 converted


def test_whitespace_stripped_and_empty_safe():
    assert pp.process("  hi  ", append_space=True) == "hi "
    assert pp.process("   ", append_space=True) == ""
    assert pp.process("", append_space=True) == ""
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_postprocess.py -v`
Expected: FAIL (module missing)

- [ ] **Step 3: Implement `app/postprocess.py`**

```python
"""Guarantee Traditional Chinese output and apply trailing-space rule."""
import re

from opencc import OpenCC

_cc = OpenCC("s2twp")  # Simplified -> Traditional with Taiwan phrasing

# CJK Unified Ideographs (+ExtA, compat) — presence triggers conversion.
_HAN_RE = re.compile(r"[㐀-䶿一-鿿豈-﫿]")
# Characters after which a trailing space makes no sense.
_NO_SPACE_AFTER = "。，、；：？！「」『』（）…—"


def to_traditional(text: str) -> str:
    if _HAN_RE.search(text):
        return _cc.convert(text)
    return text


def apply_spacing(text: str, append_space: bool) -> str:
    text = text.strip()
    if not text or not append_space:
        return text
    last = text[-1]
    if _HAN_RE.match(last) or last in _NO_SPACE_AFTER:
        return text
    return text + " "


def process(text: str, append_space: bool) -> str:
    return apply_spacing(to_traditional(text), append_space)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_postprocess.py -v`
Expected: 8 passed. (If `請 email 我` phrasing differs because s2twp rewrites a word, print actual output, adjust the *expected string in the test* to the actual correct Traditional form — the invariant is: Han converted to Traditional, ends with `我 `.)

- [ ] **Step 5: Commit**

```bash
git add app/postprocess.py tests/test_postprocess.py
git commit -m "feat: OpenCC s2twp post-processing and spacing rule"
```

---

### Task 5: Transcription providers (`app/providers/`)

**Files:**
- Create: `app/providers/base.py`, `app/providers/openai_provider.py`, `app/providers/groq_provider.py`
- Modify: `app/providers/__init__.py` (factory)
- Test: `tests/test_providers.py`

Both providers speak the same wire format (multipart POST to `<base>/audio/transcriptions`); Groq is OpenAI with a different base URL/model. HTTP is mocked in tests via monkeypatching `requests.post`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_providers.py
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_providers.py -v`
Expected: FAIL (imports missing)

- [ ] **Step 3: Implement `app/providers/base.py`**

```python
"""Provider protocol and error type."""
from typing import Protocol


class TranscriptionError(Exception):
    def __init__(self, message: str, retryable: bool = False):
        super().__init__(message)
        self.retryable = retryable


class TranscriptionProvider(Protocol):
    name: str

    def transcribe(self, wav_bytes: bytes, language: str | None, prompt: str | None) -> str:
        """Return transcript text. Raise TranscriptionError on failure."""
        ...
```

- [ ] **Step 4: Implement `app/providers/openai_provider.py`**

```python
"""OpenAI-compatible /audio/transcriptions client (plain requests)."""
import requests

from .base import TranscriptionError


class OpenAIProvider:
    name = "openai"
    base_url = "https://api.openai.com/v1"

    def __init__(self, api_key: str, model: str = "gpt-4o-mini-transcribe"):
        self.api_key = api_key
        self.model = model

    def transcribe(self, wav_bytes: bytes, language: str | None, prompt: str | None) -> str:
        if not self.api_key:
            raise TranscriptionError("API key not configured", retryable=False)
        data = {"model": self.model, "response_format": "json"}
        if language:
            data["language"] = language
        if prompt:
            data["prompt"] = prompt
        try:
            resp = requests.post(
                f"{self.base_url}/audio/transcriptions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                data=data,
                files={"file": ("audio.wav", wav_bytes, "audio/wav")},
                timeout=60,
            )
        except requests.RequestException as e:
            raise TranscriptionError(str(e), retryable=True) from e
        if resp.status_code == 429 or resp.status_code >= 500:
            raise TranscriptionError(f"HTTP {resp.status_code}: {resp.text[:200]}", retryable=True)
        if resp.status_code != 200:
            raise TranscriptionError(f"HTTP {resp.status_code}: {resp.text[:200]}", retryable=False)
        return resp.json().get("text", "").strip()
```

- [ ] **Step 5: Implement `app/providers/groq_provider.py`**

```python
"""Groq: same wire format as OpenAI, different host/model."""
from .openai_provider import OpenAIProvider


class GroqProvider(OpenAIProvider):
    name = "groq"
    base_url = "https://api.groq.com/openai/v1"

    def __init__(self, api_key: str, model: str = "whisper-large-v3-turbo"):
        super().__init__(api_key=api_key, model=model)
```

- [ ] **Step 6: Implement factory in `app/providers/__init__.py`**

```python
"""Provider factory."""
from ..config import get_api_key
from .groq_provider import GroqProvider
from .openai_provider import OpenAIProvider

_PROVIDERS = {"openai": OpenAIProvider, "groq": GroqProvider}


def create_provider(cfg: dict):
    name = cfg.get("provider", "openai")
    cls = _PROVIDERS.get(name)
    if cls is None:
        raise ValueError(f"Unknown provider {name!r}. Available: {sorted(_PROVIDERS)}. "
                         "'local' is a future slot — see README.")
    pcfg = cfg.get("providers", {}).get(name, {})
    return cls(api_key=get_api_key(cfg, name), model=pcfg.get("model") or cls(api_key="").model)
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `python -m pytest tests/test_providers.py -v`
Expected: 8 passed

- [ ] **Step 8: Commit**

```bash
git add app/providers tests/test_providers.py
git commit -m "feat: OpenAI and Groq transcription providers with factory"
```

---

### Task 6: Chord state machine (`app/hotkey.py`) — pure logic + hook adapter

**Files:**
- Create: `app/hotkey.py`
- Test: `tests/test_hotkey.py`

The machine consumes normalized events `(etype, key)` with `etype ∈ {"down","up"}` and `key ∈ {"ctrl","win","esc","other"}`. It fires `on_start` / `on_stop` / `on_cancel` callbacks. `handle()` returns True when the event happened "inside" a chord interaction (the adapter uses this to inject a dummy VK on Win-up so the Start menu never opens).

States: `idle` → chord-complete starts recording (`held`); releasing the chord before `tap_threshold_ms` flips to `toggled` (recording continues); after the threshold it's push-to-talk → `stop`. In `toggled`, completing the chord again stops. Esc cancels in both recording states. Any other key during `held` cancels and passes through (Win+Ctrl+arrow still works). `busy` ignores chords until `pipeline_done()`. `drain` waits for full release after a cancel.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_hotkey.py
import pytest

from app.hotkey import ChordMachine


class FakeClock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t

    def advance(self, s):
        self.t += s


class Spy:
    def __init__(self):
        self.calls = []

    def start(self):
        self.calls.append("start")

    def stop(self):
        self.calls.append("stop")

    def cancel(self):
        self.calls.append("cancel")


@pytest.fixture()
def rig():
    clock = FakeClock()
    spy = Spy()
    m = ChordMachine(on_start=spy.start, on_stop=spy.stop, on_cancel=spy.cancel,
                     tap_threshold_ms=400, clock=clock)
    return m, spy, clock


def test_hold_flow_push_to_talk(rig):
    m, spy, clock = rig
    m.handle("down", "ctrl")
    m.handle("down", "win")
    assert spy.calls == ["start"]
    clock.advance(0.6)
    m.handle("up", "win")
    assert spy.calls == ["start", "stop"]
    m.handle("up", "ctrl")
    assert spy.calls == ["start", "stop"]  # no double fire


def test_reverse_order_also_starts(rig):
    m, spy, _ = rig
    m.handle("down", "win")
    m.handle("down", "ctrl")
    assert spy.calls == ["start"]


def test_tap_toggles_then_second_tap_stops(rig):
    m, spy, clock = rig
    m.handle("down", "ctrl")
    m.handle("down", "win")
    clock.advance(0.1)
    m.handle("up", "win")
    m.handle("up", "ctrl")
    assert spy.calls == ["start"]  # still recording (toggled)
    clock.advance(2.0)
    m.handle("down", "ctrl")
    m.handle("down", "win")  # chord completes again -> stop
    assert spy.calls == ["start", "stop"]
    m.handle("up", "win")
    m.handle("up", "ctrl")
    assert spy.calls == ["start", "stop"]


def test_esc_cancels_while_held(rig):
    m, spy, _ = rig
    m.handle("down", "ctrl")
    m.handle("down", "win")
    m.handle("down", "esc")
    assert spy.calls == ["start", "cancel"]
    m.handle("up", "esc")
    m.handle("up", "win")
    m.handle("up", "ctrl")
    # after full release a new chord works again
    m.pipeline_done()  # no-op safety
    m.handle("down", "ctrl")
    m.handle("down", "win")
    assert spy.calls == ["start", "cancel", "start"]


def test_esc_cancels_while_toggled(rig):
    m, spy, clock = rig
    m.handle("down", "ctrl")
    m.handle("down", "win")
    clock.advance(0.1)
    m.handle("up", "win")
    m.handle("up", "ctrl")
    m.handle("down", "esc")
    assert spy.calls == ["start", "cancel"]


def test_other_key_during_hold_cancels_passthrough(rig):
    m, spy, _ = rig
    m.handle("down", "ctrl")
    m.handle("down", "win")
    m.handle("down", "other")  # e.g. Win+Ctrl+Left
    assert spy.calls == ["start", "cancel"]
    m.handle("up", "other")
    m.handle("up", "win")
    m.handle("up", "ctrl")
    m.handle("down", "ctrl")
    m.handle("down", "win")
    assert spy.calls == ["start", "cancel", "start"]


def test_chord_ignored_when_other_key_already_held(rig):
    m, spy, _ = rig
    m.handle("down", "other")
    m.handle("down", "ctrl")
    m.handle("down", "win")
    assert spy.calls == []
    m.handle("up", "other")
    m.handle("up", "ctrl")
    m.handle("up", "win")


def test_busy_blocks_new_chord_until_pipeline_done(rig):
    m, spy, clock = rig
    m.handle("down", "ctrl")
    m.handle("down", "win")
    clock.advance(0.6)
    m.handle("up", "win")
    m.handle("up", "ctrl")
    assert spy.calls == ["start", "stop"]
    m.handle("down", "ctrl")
    m.handle("down", "win")  # ignored: busy
    assert spy.calls == ["start", "stop"]
    m.handle("up", "win")
    m.handle("up", "ctrl")
    m.pipeline_done()
    m.handle("down", "ctrl")
    m.handle("down", "win")
    assert spy.calls == ["start", "stop", "start"]


def test_external_stop_in_toggled(rig):
    m, spy, clock = rig
    m.handle("down", "ctrl")
    m.handle("down", "win")
    clock.advance(0.1)
    m.handle("up", "win")
    m.handle("up", "ctrl")
    assert m.external_stop() is True  # auto-stop fires
    assert spy.calls == ["start"]  # external_stop does NOT call on_stop; caller owns pipeline
    m.handle("down", "ctrl")
    m.handle("down", "win")  # busy -> ignored
    assert spy.calls == ["start"]
    m.pipeline_done()


def test_external_stop_noop_when_idle(rig):
    m, spy, _ = rig
    assert m.external_stop() is False


def test_in_chord_hint_for_start_menu_suppression(rig):
    m, _, clock = rig
    assert m.handle("down", "ctrl") is False  # nothing yet
    assert m.handle("down", "win") is True    # chord began
    clock.advance(0.6)
    assert m.handle("up", "win") is True      # inside interaction
    assert m.handle("up", "ctrl") is True     # still draining busy chord keys
    m.pipeline_done()
    assert m.handle("down", "other") is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_hotkey.py -v`
Expected: FAIL (module missing)

- [ ] **Step 3: Implement `app/hotkey.py`**

```python
"""Win+Ctrl chord detection: pure state machine + keyboard-library adapter."""
import logging
import time

log = logging.getLogger(__name__)

IDLE = "idle"          # waiting for chord
HELD = "held"          # recording; tap/hold not yet classified
TOGGLED = "toggled"    # recording hands-free after a tap
DRAIN = "drain"        # cancelled; wait for full release
BUSY = "busy"          # pipeline running; ignore chords


class ChordMachine:
    def __init__(self, on_start, on_stop, on_cancel,
                 tap_threshold_ms=400, clock=time.monotonic):
        self.on_start = on_start
        self.on_stop = on_stop
        self.on_cancel = on_cancel
        self.tap_threshold = tap_threshold_ms / 1000.0
        self.clock = clock
        self.state = IDLE
        self.ctrl = False
        self.win = False
        self.other_held = 0
        self.t0 = 0.0

    # -- public API ---------------------------------------------------------

    def handle(self, etype: str, key: str) -> bool:
        """Feed one normalized event. Returns True if the event is part of a
        chord interaction (adapter uses this to suppress the Start menu)."""
        in_chord_before = self.state != IDLE

        if key == "ctrl":
            self.ctrl = etype == "down"
        elif key == "win":
            self.win = etype == "down"
        elif key == "other":
            if etype == "down":
                self.other_held += 1
            else:
                self.other_held = max(0, self.other_held - 1)

        chord_complete = (
            etype == "down" and key in ("ctrl", "win") and self.ctrl and self.win
        )

        if self.state == IDLE:
            if chord_complete and self.other_held == 0:
                self.state = HELD
                self.t0 = self.clock()
                self._safe(self.on_start)
                return True
            return False

        if self.state == HELD:
            if key in ("esc", "other") and etype == "down":
                self.state = DRAIN
                self._safe(self.on_cancel)
            elif etype == "up" and key in ("ctrl", "win"):
                elapsed = self.clock() - self.t0
                if elapsed < self.tap_threshold:
                    self.state = TOGGLED
                else:
                    self.state = BUSY
                    self._safe(self.on_stop)
            return True

        if self.state == TOGGLED:
            if key == "esc" and etype == "down":
                self.state = IDLE
                self._safe(self.on_cancel)
            elif chord_complete:
                self.state = BUSY
                self._safe(self.on_stop)
            return True

        if self.state == DRAIN:
            if not self.ctrl and not self.win and self.other_held == 0:
                self.state = IDLE
            return True

        if self.state == BUSY:
            return key in ("ctrl", "win")

        return in_chord_before

    def external_stop(self) -> bool:
        """Force-stop (max-duration timer). Caller runs the pipeline itself;
        no on_stop callback is fired. Returns True if we were recording."""
        if self.state in (HELD, TOGGLED):
            self.state = BUSY
            return True
        return False

    def pipeline_done(self):
        if self.state == BUSY:
            self.state = IDLE

    def is_recording(self) -> bool:
        return self.state in (HELD, TOGGLED)

    # -- internals ----------------------------------------------------------

    def _safe(self, cb):
        try:
            cb()
        except Exception:
            log.exception("hotkey callback failed")


class KeyboardHookAdapter:
    """Bridges the `keyboard` library to ChordMachine. Listen-only hook
    (no global suppression — safer). Injects a dummy VK on Win-up inside a
    chord so Windows never opens the Start menu."""

    def __init__(self, machine: ChordMachine):
        self.machine = machine
        self._hook = None

    @staticmethod
    def normalize(name: str) -> str:
        n = (name or "").lower()
        if "ctrl" in n:
            return "ctrl"
        if "windows" in n or n in ("win", "left win", "right win", "cmd"):
            return "win"
        if n in ("esc", "escape"):
            return "esc"
        return "other"

    def start(self):
        import keyboard  # imported here so logic tests never need the hook

        def callback(event):
            etype = "down" if event.event_type == "down" else "up"
            key = self.normalize(event.name)
            in_chord = self.machine.handle(etype, key)
            # Also fire when Ctrl is still physically down (user held the chord
            # through the whole pipeline; machine may already be back to idle).
            if key == "win" and etype == "up" and (in_chord or self.machine.ctrl):
                self._send_dummy_vk()

        self._hook = keyboard.hook(callback)

    def stop(self):
        if self._hook is not None:
            import keyboard

            keyboard.unhook(self._hook)
            self._hook = None

    @staticmethod
    def _send_dummy_vk():
        """Send unassigned VK 0xE8 so the OS sees 'another key' before Win-up
        and does not open the Start menu (classic AutoHotkey trick)."""
        import ctypes

        ctypes.windll.user32.keybd_event(0xE8, 0, 0, 0)
        ctypes.windll.user32.keybd_event(0xE8, 0, 2, 0)  # KEYEVENTF_KEYUP
```

Note for the implementer: the dummy VK must be sent *when Win goes up*, which is what the callback does — `handle()` has already processed the event, and `in_chord` is True for chord interactions (see `test_in_chord_hint_for_start_menu_suppression`).

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_hotkey.py -v`
Expected: 11 passed

- [ ] **Step 5: Run the whole suite**

Run: `python -m pytest`
Expected: all tests pass (config + i18n + postprocess + providers + hotkey)

- [ ] **Step 6: Commit**

```bash
git add app/hotkey.py tests/test_hotkey.py
git commit -m "feat: chord state machine (hold/tap/esc/passthrough) + hook adapter"
```

---

### Task 7: Recorder (`app/recorder.py`) + audio cues (`app/notify.py`)

**Files:**
- Create: `app/recorder.py`, `app/notify.py`
- Test: `tests/test_recorder.py`

`Recorder` uses `sounddevice.RawInputStream` (bytes; **no numpy**). The WAV encoding is a pure function we unit-test; live capture is exercised later via `--check`. `notify.py` holds beep cues + toast wrapper (toasts via pystray are wired in Task 10).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_recorder.py
import io
import wave

from app.recorder import raw_to_wav, MIN_DURATION_S, duration_of


def test_raw_to_wav_header_and_payload():
    raw = b"\x00\x01" * 16000  # 1 second of 16 kHz mono int16
    wav_bytes = raw_to_wav(raw, samplerate=16000)
    with wave.open(io.BytesIO(wav_bytes)) as w:
        assert w.getnchannels() == 1
        assert w.getsampwidth() == 2
        assert w.getframerate() == 16000
        assert w.getnframes() == 16000
        assert w.readframes(2) == b"\x00\x01\x00\x01"


def test_duration_of():
    assert duration_of(b"\x00" * 32000, 16000) == 1.0


def test_min_duration_constant():
    assert MIN_DURATION_S == 0.3
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_recorder.py -v`
Expected: FAIL (module missing)

- [ ] **Step 3: Implement `app/recorder.py`**

```python
"""Microphone capture at 16 kHz mono int16 via sounddevice (no numpy)."""
import io
import logging
import threading
import wave

log = logging.getLogger(__name__)

SAMPLERATE = 16000
MIN_DURATION_S = 0.3


def raw_to_wav(raw: bytes, samplerate: int = SAMPLERATE) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(samplerate)
        w.writeframes(raw)
    return buf.getvalue()


def duration_of(raw: bytes, samplerate: int = SAMPLERATE) -> float:
    return len(raw) / (samplerate * 2)


class MicError(Exception):
    pass


class Recorder:
    def __init__(self, device=None):
        self.device = device
        self._stream = None
        self._buf = bytearray()
        self._lock = threading.Lock()

    def start(self):
        import sounddevice as sd

        with self._lock:
            self._buf = bytearray()

        def callback(indata, frames, time_info, status):
            if status:
                log.warning("audio status: %s", status)
            with self._lock:
                self._buf.extend(bytes(indata))

        try:
            self._stream = sd.RawInputStream(
                samplerate=SAMPLERATE, channels=1, dtype="int16",
                device=self.device, callback=callback,
            )
            self._stream.start()
        except Exception as e:
            self._stream = None
            raise MicError(str(e)) from e

    def stop(self) -> bytes | None:
        """Stop and return WAV bytes, or None if too short to be speech."""
        raw = self._close()
        if duration_of(raw) < MIN_DURATION_S:
            return None
        return raw_to_wav(raw)

    def cancel(self):
        self._close()

    def is_active(self) -> bool:
        return self._stream is not None

    def _close(self) -> bytes:
        stream, self._stream = self._stream, None
        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except Exception:
                log.exception("closing stream")
        with self._lock:
            raw, self._buf = bytes(self._buf), bytearray()
        return raw


def list_devices() -> str:
    import sounddevice as sd

    return str(sd.query_devices())
```

- [ ] **Step 4: Implement `app/notify.py`**

```python
"""Beep cues and toast notifications (toast sink is injected by tray)."""
import logging
import threading

log = logging.getLogger(__name__)

_BEEPS = {"start": (880, 90), "stop": (660, 90), "cancel": (440, 130), "error": (330, 200)}


def beep(kind: str, enabled: bool = True):
    if not enabled:
        return

    def _play():
        try:
            import winsound

            freq, ms = _BEEPS.get(kind, (500, 100))
            winsound.Beep(freq, ms)
        except Exception:
            log.debug("beep failed", exc_info=True)

    threading.Thread(target=_play, daemon=True).start()


class Notifier:
    """Toast notifications; falls back to log if tray isn't up yet."""

    def __init__(self):
        self._sink = None  # set by tray: callable(message, title)

    def set_sink(self, sink):
        self._sink = sink

    def toast(self, message: str, title: str = "VoiceToText"):
        log.info("notify: %s", message)
        if self._sink is not None:
            try:
                self._sink(message, title)
            except Exception:
                log.debug("toast failed", exc_info=True)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_recorder.py -v`
Expected: 3 passed

- [ ] **Step 6: Commit**

```bash
git add app/recorder.py app/notify.py tests/test_recorder.py
git commit -m "feat: mic recorder (16k mono WAV) and beep/toast helpers"
```

---

### Task 8: History (`app/history.py`) + text injection (`app/inject.py`)

**Files:**
- Create: `app/history.py`, `app/inject.py`
- Test: `tests/test_history.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_history.py
import json

from app.history import append_entry


def test_append_creates_file_and_appends(tmp_path):
    p = tmp_path / "history.jsonl"
    append_entry(p, lang="auto", duration_s=2.5, text="hello world")
    append_entry(p, lang="zh", duration_s=1.0, text="你好")
    lines = p.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    first = json.loads(lines[0])
    assert first["text"] == "hello world"
    assert first["chars"] == 11
    assert first["duration_s"] == 2.5
    assert "ts" in first
    second = json.loads(lines[1])
    assert second["text"] == "你好"  # unicode preserved, not \u escaped
    assert "你好" in lines[1]


def test_append_never_raises(tmp_path):
    # unwritable target (a directory) must not crash the pipeline
    append_entry(tmp_path, lang="en", duration_s=1.0, text="x")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_history.py -v`
Expected: FAIL (module missing)

- [ ] **Step 3: Implement `app/history.py`**

```python
"""Append-only dictation history (history.jsonl)."""
import datetime
import json
import logging
from pathlib import Path

log = logging.getLogger(__name__)

HISTORY_PATH = Path(__file__).resolve().parent.parent / "history.jsonl"


def append_entry(path: Path, lang: str, duration_s: float, text: str) -> None:
    entry = {
        "ts": datetime.datetime.now().isoformat(timespec="seconds"),
        "lang": lang,
        "duration_s": round(duration_s, 2),
        "chars": len(text),
        "text": text,
    }
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        log.exception("history append failed")
```

- [ ] **Step 4: Implement `app/inject.py`** (thin OS shim — verified live in Task 12; no unit test)

```python
"""Insert text into the focused app: clipboard + simulated Ctrl+V.

Clipboard is intentionally NOT restored — the transcript stays as backup.
Pasting (not typing) is required for Chinese text (IME-safe).
"""
import logging
import time

log = logging.getLogger(__name__)

MODIFIER_KEYS = ("ctrl", "left windows", "right windows")


def _wait_modifiers_released(timeout_s: float = 1.0):
    """If the user still physically holds Ctrl/Win from the chord, Ctrl+V
    would become Win+Ctrl+V. Wait briefly for release."""
    import keyboard

    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            if not any(keyboard.is_pressed(k) for k in MODIFIER_KEYS):
                return
        except Exception:
            return
        time.sleep(0.02)


def insert_text(text: str, settle_ms: int = 150):
    import keyboard
    import pyperclip

    pyperclip.copy(text)
    _wait_modifiers_released()
    time.sleep(settle_ms / 1000.0)
    try:
        keyboard.send("ctrl+v")
    except Exception:
        log.exception("paste failed (text remains on clipboard)")
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_history.py -v`
Expected: 2 passed

- [ ] **Step 6: Commit**

```bash
git add app/history.py app/inject.py tests/test_history.py
git commit -m "feat: history log and clipboard-paste injection"
```

---

### Task 9: Status overlay (`app/overlay.py`)

**Files:**
- Create: `app/overlay.py`

Thin UI shim — no unit tests; verified live in Task 12 (overlay must appear without stealing focus). All tkinter calls stay on one dedicated thread; other threads talk to it via a queue. Click-through + no-activate via Win32 ex-styles is **critical** (focus theft would redirect the paste).

- [ ] **Step 1: Implement `app/overlay.py`**

```python
"""Always-on-top status pill (tkinter on its own thread, queue-driven).

WS_EX_NOACTIVATE | WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW make it click-through
and focus-neutral so the paste target keeps focus.
"""
import logging
import queue
import threading

log = logging.getLogger(__name__)

GWL_EXSTYLE = -20
WS_EX_NOACTIVATE = 0x08000000
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOOLWINDOW = 0x00000080

COLORS = {"recording": "#e74c3c", "transcribing": "#e67e22"}


class Overlay:
    def __init__(self, enabled: bool = True):
        self.enabled = enabled
        self._q: queue.Queue = queue.Queue()
        if enabled:
            threading.Thread(target=self._run, daemon=True, name="overlay").start()

    def show(self, text: str, mode: str):
        if self.enabled:
            self._q.put(("show", text, COLORS.get(mode, "#888888")))

    def hide(self):
        if self.enabled:
            self._q.put(("hide", None, None))

    def close(self):
        if self.enabled:
            self._q.put(("close", None, None))

    # -- overlay thread -------------------------------------------------------

    def _run(self):
        try:
            import tkinter as tk

            root = tk.Tk()
            root.overrideredirect(True)
            root.attributes("-topmost", True)
            root.attributes("-alpha", 0.92)
            root.configure(bg="#1e1e1e")
            label = tk.Label(root, text="", font=("Segoe UI", 11), fg="white",
                             bg="#1e1e1e", padx=18, pady=8)
            label.pack()
            root.withdraw()
            self._apply_exstyles(root)

            def poll():
                try:
                    while True:
                        cmd, text, color = self._q.get_nowait()
                        if cmd == "show":
                            label.config(text=text, fg=color)
                            root.update_idletasks()
                            w = root.winfo_reqwidth()
                            x = (root.winfo_screenwidth() - w) // 2
                            y = root.winfo_screenheight() - 140
                            root.geometry(f"+{x}+{y}")
                            root.deiconify()
                            root.attributes("-topmost", True)
                            self._apply_exstyles(root)
                        elif cmd == "hide":
                            root.withdraw()
                        elif cmd == "close":
                            root.destroy()
                            return
                except queue.Empty:
                    pass
                root.after(50, poll)

            root.after(50, poll)
            root.mainloop()
        except Exception:
            log.exception("overlay thread died (app continues without overlay)")

    @staticmethod
    def _apply_exstyles(root):
        try:
            import ctypes

            hwnd = ctypes.windll.user32.GetParent(root.winfo_id()) or root.winfo_id()
            style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            style |= WS_EX_NOACTIVATE | WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW
            ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)
        except Exception:
            log.debug("exstyle apply failed", exc_info=True)


class NullOverlay:
    """Used when show_overlay is false or tkinter is unavailable."""

    def show(self, text, mode):
        pass

    def hide(self):
        pass

    def close(self):
        pass
```

- [ ] **Step 2: Import smoke check**

Run: `python -c "from app.overlay import Overlay, NullOverlay; print('ok')"`
Expected: `ok`

- [ ] **Step 3: Run full suite (no regressions)**

Run: `python -m pytest`
Expected: all pass

- [ ] **Step 4: Commit**

```bash
git add app/overlay.py
git commit -m "feat: click-through always-on-top status overlay"
```

---

### Task 10: Windows startup shortcut (`app/startup.py`) + tray (`app/tray.py`)

**Files:**
- Create: `app/startup.py`, `app/tray.py`
- Test: `tests/test_startup.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_startup.py
from pathlib import Path

from app import startup


def test_shortcut_path_is_in_startup_folder():
    assert startup.SHORTCUT.name == "VoiceToText.lnk"
    assert "Startup" in str(startup.SHORTCUT)


def test_pythonw_path_points_to_exe():
    p = startup.pythonw_path()
    assert p.lower().endswith(".exe")
    assert Path(p).exists()


def test_is_installed_returns_bool():
    assert isinstance(startup.is_installed(), bool)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_startup.py -v`
Expected: FAIL (module missing)

- [ ] **Step 3: Implement `app/startup.py`**

```python
"""Create/remove the Startup-folder shortcut (start with Windows)."""
import os
import subprocess
import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent
STARTUP_DIR = (Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows"
               / "Start Menu" / "Programs" / "Startup")
SHORTCUT = STARTUP_DIR / "VoiceToText.lnk"


def is_installed() -> bool:
    return SHORTCUT.exists()


def pythonw_path() -> str:
    exe = Path(sys.executable)
    w = exe.with_name("pythonw.exe")
    return str(w if w.exists() else exe)


def install() -> None:
    ps = (
        "$ws = New-Object -ComObject WScript.Shell; "
        f"$s = $ws.CreateShortcut('{SHORTCUT}'); "
        f"$s.TargetPath = '{pythonw_path()}'; "
        "$s.Arguments = '-m app'; "
        f"$s.WorkingDirectory = '{APP_DIR}'; "
        "$s.Save()"
    )
    subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                   check=True, capture_output=True, timeout=30)


def uninstall() -> None:
    SHORTCUT.unlink(missing_ok=True)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_startup.py -v`
Expected: 3 passed

- [ ] **Step 5: Implement `app/tray.py`** (UI shim — verified live in Task 12)

```python
"""System tray icon and menu (pystray). Runs on the main thread."""
import logging

import pystray
from PIL import Image, ImageDraw
from pystray import Menu
from pystray import MenuItem as Item

from . import startup
from .i18n import tr

log = logging.getLogger(__name__)

COLORS = {"idle": "#9e9e9e", "recording": "#e74c3c", "transcribing": "#e67e22"}


def make_icon_image(state: str) -> Image.Image:
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    color = COLORS.get(state, COLORS["idle"])
    d.rounded_rectangle([22, 8, 42, 38], radius=10, fill=color)      # mic capsule
    d.arc([14, 22, 50, 50], start=0, end=180, fill=color, width=4)   # cradle
    d.line([32, 50, 32, 58], fill=color, width=4)                    # stem
    d.line([22, 58, 42, 58], fill=color, width=4)                    # base
    return img


def run_tray(app, on_ready=None):
    """Blocks on the pystray loop until Quit. `app` is __main__.App."""

    def t(key):
        return tr(key, app.cfg.get("ui_language", "en"))

    icon = pystray.Icon("VoiceToText", make_icon_image("idle"), title="VoiceToText")

    def set_state(state):
        icon.icon = make_icon_image(state)

    def lang_item(label_key, value):
        return Item(
            lambda item: t(label_key),
            lambda: (app.set_language(value), icon.update_menu()),
            checked=lambda item: app.cfg["language"] == value,
            radio=True,
        )

    def ui_lang_item(label, value):
        return Item(
            label,
            lambda: (app.set_ui_language(value), rebuild()),
            checked=lambda item: app.cfg["ui_language"] == value,
            radio=True,
        )

    def toggle_startup():
        try:
            if startup.is_installed():
                startup.uninstall()
                app.notifier.toast(t("startup_off"))
            else:
                startup.install()
                app.notifier.toast(t("startup_on"))
        except Exception as e:
            log.exception("startup toggle failed")
            app.notifier.toast(str(e))
        icon.update_menu()

    def build_menu():
        return Menu(
            Item(lambda item: t("ready"), None, enabled=False),
            Menu.SEPARATOR,
            Item(lambda item: t("language"), Menu(
                lang_item("lang_auto", "auto"),
                lang_item("lang_en", "en"),
                lang_item("lang_zh", "zh"),
            )),
            Item(lambda item: t("ui_language"), Menu(
                ui_lang_item("English", "en"),
                ui_lang_item("繁體中文", "zh-TW"),
            )),
            Menu.SEPARATOR,
            Item(lambda item: t("retry_last"), lambda: app.retry_last()),
            Item(lambda item: t("open_history"), lambda: app.open_history()),
            Item(lambda item: t("open_config"), lambda: app.open_config()),
            Item(lambda item: t("start_with_windows"), toggle_startup,
                 checked=lambda item: startup.is_installed()),
            Menu.SEPARATOR,
            Item(lambda item: t("quit"), lambda: (app.shutdown(), icon.stop())),
        )

    def rebuild():
        icon.menu = build_menu()
        icon.update_menu()

    def setup(icon_obj):
        icon_obj.visible = True
        if on_ready is not None:
            try:
                on_ready()
            except Exception:
                log.exception("on_ready failed")

    icon.menu = build_menu()
    app.set_tray_state = set_state
    app.notifier.set_sink(lambda msg, title: icon.notify(msg, title))
    icon.run(setup=setup)
```

- [ ] **Step 6: Import smoke check + full suite**

Run: `python -c "from app.tray import make_icon_image; make_icon_image('idle'); print('ok')"`
Expected: `ok`
Run: `python -m pytest`
Expected: all pass

- [ ] **Step 7: Commit**

```bash
git add app/startup.py app/tray.py tests/test_startup.py
git commit -m "feat: tray icon/menu and start-with-Windows shortcut"
```

---

### Task 11: App controller and entry point (`app/__main__.py`) + `force_start`

**Files:**
- Modify: `app/hotkey.py` (add `force_start`), `tests/test_hotkey.py` (add test)
- Create: `app/__main__.py`

`force_start()` lets a custom non-chord hotkey (e.g. `"f8"`) drive the same machine in toggle-only mode.

- [ ] **Step 1: Add the failing test to `tests/test_hotkey.py`**

```python
def test_force_start_only_from_idle(rig):
    m, spy, _ = rig
    assert m.force_start() is True
    assert m.is_recording() is True
    assert m.force_start() is False   # already recording
    assert spy.calls == []            # caller owns UI/recorder side effects
    assert m.external_stop() is True
    m.pipeline_done()
    assert m.force_start() is True
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python -m pytest tests/test_hotkey.py::test_force_start_only_from_idle -v`
Expected: FAIL (`force_start` missing)

- [ ] **Step 3: Add `force_start` to `ChordMachine` in `app/hotkey.py`** (below `external_stop`)

```python
    def force_start(self) -> bool:
        """Used by custom non-chord hotkeys (toggle mode). Caller invokes the
        recorder/UI itself, mirroring external_stop's contract."""
        if self.state == IDLE:
            self.state = TOGGLED
            self.t0 = self.clock()
            return True
        return False
```

- [ ] **Step 4: Run hotkey tests**

Run: `python -m pytest tests/test_hotkey.py -v`
Expected: 12 passed

- [ ] **Step 5: Implement `app/__main__.py`**

```python
"""VoiceToText entry point: wiring, pipeline worker, CLI flags."""
import argparse
import ctypes
import logging
import logging.handlers
import os
import queue
import socket
import sys
import threading
import time
from pathlib import Path

from . import config as config_mod
from . import history, inject, postprocess
from .config import get_api_key
from .hotkey import ChordMachine, KeyboardHookAdapter
from .i18n import tr
from .notify import Notifier, beep
from .overlay import NullOverlay, Overlay
from .providers import create_provider
from .providers.base import TranscriptionError
from .recorder import MicError, Recorder, list_devices

log = logging.getLogger("app")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LAST_RECORDING = PROJECT_ROOT / "last_recording.wav"
LOG_PATH = PROJECT_ROOT / "app.log"
SINGLE_INSTANCE_PORT = 50517
ZH_PROMPT = "請用繁體中文輸出。"
WAV_HEADER_BYTES = 44
BYTES_PER_SECOND = 32000  # 16 kHz * 2 bytes


def wav_duration(wav: bytes) -> float:
    return max(0.0, (len(wav) - WAV_HEADER_BYTES) / BYTES_PER_SECOND)


class App:
    def __init__(self, cfg: dict, cfg_path):
        self.cfg = cfg
        self.cfg_path = cfg_path
        self.provider = create_provider(cfg)
        self.recorder = Recorder(device=cfg.get("input_device"))
        self.overlay = Overlay(True) if cfg.get("show_overlay", True) else NullOverlay()
        self.notifier = Notifier()
        self.machine = ChordMachine(
            on_start=self._on_start, on_stop=self._on_stop, on_cancel=self._on_cancel,
            tap_threshold_ms=cfg.get("tap_threshold_ms", 400),
        )
        self.adapter = KeyboardHookAdapter(self.machine)
        self.jobs: queue.Queue = queue.Queue()
        self.set_tray_state = lambda state: None  # replaced by tray.run_tray
        self._timer = None
        threading.Thread(target=self._worker, daemon=True, name="pipeline").start()

    def t(self, key, **fmt):
        return tr(key, self.cfg.get("ui_language", "en"), **fmt)

    # -- hotkey callbacks (keyboard hook thread) -----------------------------

    def _on_start(self):
        try:
            self.recorder.start()
        except MicError as e:
            beep("error", self.cfg["beeps"])
            self.notifier.toast(self.t("err_mic", error=str(e)))
            return
        beep("start", self.cfg["beeps"])
        self.overlay.show(self.t("recording"), "recording")
        self.set_tray_state("recording")
        self._timer = threading.Timer(self.cfg["max_recording_s"], self._auto_stop)
        self._timer.daemon = True
        self._timer.start()

    def _on_stop(self):
        self._cancel_timer()
        self._stop_and_enqueue()

    def _on_cancel(self):
        self._cancel_timer()
        self.recorder.cancel()
        beep("cancel", self.cfg["beeps"])
        self._finish_ui()

    def _auto_stop(self):
        if self.machine.external_stop():
            self._stop_and_enqueue()
            self.notifier.toast(
                self.t("auto_stopped", minutes=round(self.cfg["max_recording_s"] / 60)))

    def toggle_simple(self):
        """Custom non-chord hotkey: toggle recording on/off."""
        if self.machine.is_recording():
            if self.machine.external_stop():
                self._cancel_timer()
                self._stop_and_enqueue()
        elif self.machine.force_start():
            self._on_start()

    def _stop_and_enqueue(self):
        wav = self.recorder.stop()
        beep("stop", self.cfg["beeps"])
        if not wav:
            self._finish_ui()
            self.machine.pipeline_done()
            return
        self.overlay.show(self.t("transcribing"), "transcribing")
        self.set_tray_state("transcribing")
        self.jobs.put(("transcribe", wav))

    # -- pipeline worker thread ----------------------------------------------

    def _worker(self):
        while True:
            job = self.jobs.get()
            if job[0] == "quit":
                return
            try:
                self._transcribe_and_insert(job[1])
            except Exception:
                log.exception("pipeline crashed")
                self.notifier.toast(self.t("err_api", error="internal error — see app.log"))
            finally:
                self._finish_ui()
                self.machine.pipeline_done()

    def _transcribe_and_insert(self, wav: bytes):
        try:
            LAST_RECORDING.write_bytes(wav)
        except OSError:
            log.warning("could not save last_recording.wav")
        lang = self.cfg.get("language", "auto")
        language = None if lang == "auto" else lang
        prompt = ZH_PROMPT if lang == "zh" else None
        text = self._transcribe_with_retry(wav, language, prompt)
        if text is None:
            return  # already notified
        text = postprocess.process(text, self.cfg.get("append_space", True))
        if not text.strip():
            self.notifier.toast(self.t("err_empty"))
            return
        inject.insert_text(text)
        history.append_entry(history.HISTORY_PATH, lang=lang,
                             duration_s=wav_duration(wav), text=text)

    def _transcribe_with_retry(self, wav, language, prompt):
        for attempt in (1, 2):
            try:
                return self.provider.transcribe(wav, language, prompt)
            except TranscriptionError as e:
                if e.retryable and attempt == 1:
                    log.warning("transcription failed, retrying: %s", e)
                    time.sleep(2)
                    continue
                log.error("transcription failed: %s", e)
                beep("error", self.cfg["beeps"])
                self.notifier.toast(self.t("err_api", error=str(e)))
                return None

    # -- tray actions (tray thread) --------------------------------------------

    def retry_last(self):
        if not LAST_RECORDING.exists():
            self.notifier.toast(self.t("retry_none"))
            return
        wav = LAST_RECORDING.read_bytes()
        self.overlay.show(self.t("transcribing"), "transcribing")
        self.set_tray_state("transcribing")
        self.jobs.put(("transcribe", wav))

    def open_history(self):
        history.HISTORY_PATH.touch(exist_ok=True)
        os.startfile(history.HISTORY_PATH)

    def open_config(self):
        if not Path(self.cfg_path).exists():
            config_mod.save_config(self.cfg, self.cfg_path)
        os.startfile(self.cfg_path)

    def set_language(self, lang: str):
        self.cfg["language"] = lang
        config_mod.save_config(self.cfg, self.cfg_path)

    def set_ui_language(self, ui: str):
        self.cfg["ui_language"] = ui
        config_mod.save_config(self.cfg, self.cfg_path)

    def shutdown(self):
        try:
            self.adapter.stop()
        except Exception:
            log.debug("unhook failed", exc_info=True)
        self._cancel_timer()
        self.recorder.cancel()
        self.jobs.put(("quit",))
        self.overlay.close()

    # -- helpers ----------------------------------------------------------------

    def _finish_ui(self):
        self.overlay.hide()
        self.set_tray_state("idle")

    def _cancel_timer(self):
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None


def acquire_single_instance():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", SINGLE_INSTANCE_PORT))
        s.listen(1)
        return s
    except OSError:
        return None


def run_check(cfg) -> int:
    print(f"Provider: {cfg['provider']}  model: "
          f"{cfg['providers'][cfg['provider']]['model']}")
    if not get_api_key(cfg, cfg["provider"]):
        print("ERROR: no API key (config.json providers.*.api_key or env var).")
        return 1
    rec = Recorder(device=cfg.get("input_device"))
    print("Recording 2 seconds — speak now…")
    rec.start()
    time.sleep(2.2)
    wav = rec.stop()
    if not wav:
        print("ERROR: no audio captured (check microphone).")
        return 1
    provider = create_provider(cfg)
    text = provider.transcribe(wav, None, None)
    print("Transcript:", postprocess.process(text, cfg.get("append_space", True)))
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="voicetotext")
    parser.add_argument("--check", action="store_true", help="2s mic + API end-to-end test")
    parser.add_argument("--list-devices", action="store_true", help="list audio input devices")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)

    handlers = [logging.handlers.RotatingFileHandler(
        LOG_PATH, maxBytes=1_000_000, backupCount=3, encoding="utf-8")]
    if args.verbose or args.check or args.list_devices:
        handlers.append(logging.StreamHandler())
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s", handlers=handlers)

    if args.list_devices:
        print(list_devices())
        return 0

    cfg = config_mod.load_config()

    if args.check:
        return run_check(cfg)

    lock = acquire_single_instance()
    if lock is None:
        ctypes.windll.user32.MessageBoxW(
            0, tr("already_running", cfg.get("ui_language", "en")), "VoiceToText", 0x40)
        return 0

    app = App(cfg, config_mod.CONFIG_PATH)

    hotkey_cfg = cfg.get("hotkey", "ctrl+windows")
    if hotkey_cfg == "ctrl+windows":
        app.adapter.start()
    else:
        import keyboard

        keyboard.add_hotkey(hotkey_cfg, app.toggle_simple)
        log.info("custom hotkey %r (toggle mode)", hotkey_cfg)

    on_ready = None
    if not get_api_key(cfg, cfg["provider"]):
        on_ready = lambda: app.notifier.toast(app.t("err_no_key"))

    from .tray import run_tray

    run_tray(app, on_ready=on_ready)  # blocks until Quit
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 6: Smoke checks (no live hotkey yet)**

Run: `python -m pytest`
Expected: all pass (12 hotkey tests now)
Run: `python -m app --list-devices`
Expected: a table of audio devices prints; exit 0.
Run: `python -c "import app.__main__ as m; print('import ok')"`
Expected: `import ok`

- [ ] **Step 7: Commit**

```bash
git add app/hotkey.py tests/test_hotkey.py app/__main__.py
git commit -m "feat: app controller, pipeline worker, CLI entry point"
```

---

### Task 12: README and user config

**Files:**
- Create: `README.md`
- Create: `config.json` (copy of example — user pastes their API key; file is gitignored)

- [ ] **Step 1: Write `README.md`**

```markdown
# VoiceToText 語音輸入

Wispr-Flow-style dictation for Windows. Hold or tap **Win+Ctrl**, speak English or
Mandarin, and the text is typed into whatever app you're using. Chinese always comes
out as Traditional characters (繁體中文).

## Setup (once)

1. `python -m pip install -r requirements.txt`
2. Copy `config.example.json` to `config.json` and paste your OpenAI API key into
   `providers.openai.api_key` (or set the `OPENAI_API_KEY` environment variable).
3. Test everything: `python -m app --check` → speak for 2 seconds → your words print.
4. Start the app: double-click `run.bat` (or `python -m app --verbose` to debug).
   A gray microphone appears in the system tray.
5. Optional: tray menu → **Start with Windows**.

## Using it

| Action | Result |
|---|---|
| **Hold Win+Ctrl**, speak, release | Push-to-talk: text appears at your cursor |
| **Tap Win+Ctrl** (quick press) | Recording stays on; tap again to finish |
| **Esc** while recording | Cancel (note: the Esc also reaches the active app) |
| Win+Ctrl+←/→ etc. | Cancels recording and works normally (passes through) |

The transcript is also left on your clipboard (Ctrl+V re-pastes it), and every
dictation is saved to `history.jsonl` (tray → Open history).

- Recording auto-stops after 5 minutes (configurable `max_recording_s`).
- Recordings shorter than 0.3 s are ignored.

## Languages

- **Auto-detect** (default): speak English or Mandarin per recording.
- Tray → 辨識語言/Language pins English or 中文 if auto-detect guesses wrong.
- All Chinese output is converted to Traditional (OpenCC s2twp), no matter what
  the model returns.
- Tray → UI language switches the menus/notifications between English and 繁體中文.

## Switching providers / models

Edit `config.json`:

- OpenAI models: `gpt-4o-mini-transcribe` (default, ~US$0.003/min),
  `gpt-4o-transcribe` (more accurate), `whisper-1`.
- Groq (free tier): `"provider": "groq"` and put your Groq key in
  `providers.groq.api_key` (or `GROQ_API_KEY` env var).
- A local/offline Whisper provider is a planned future option
  (`app/providers/` is designed for drop-in additions).

## Custom hotkey

`"hotkey"` in config.json. The default `"ctrl+windows"` gets the full hold/tap
behavior. Any other value (e.g. `"f8"`) uses simple toggle mode (Esc cancel not
available there).

## Troubleshooting

- **Nothing pastes into an admin window** — Windows blocks simulated input into
  elevated apps. The text is still on the clipboard; or run this app as admin too.
- **No tray icon / import errors** — re-run `python -m pip install -r requirements.txt`;
  if a package fails on Python 3.14 (Store version), install Python 3.12 from
  python.org and use that.
- **Hotkey doesn't fire in some game/app** — apps running elevated also swallow
  hooks; run this app as admin.
- **API errors** — check `app.log`; failed audio is kept as `last_recording.wav`,
  tray → Retry last recording.
- Logs: `app.log` (rotates at 1 MB). Verbose console: `python -m app --verbose`.

## Privacy & cost

Audio is sent only to your configured provider (OpenAI/Groq) for transcription —
nothing else leaves your machine. History/audio stay in this folder. OpenAI cost
≈ US$0.003–0.006 per minute of speech.
```

- [ ] **Step 2: Create the user's real config**

Run: `Copy-Item config.example.json config.json` (PowerShell)
Do **not** put a key in it — the user pastes their own. Confirm `git status` does NOT list `config.json` (it's gitignored).

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: README with setup, usage, troubleshooting"
```

---

### Task 13: End-to-end verification (live, with the user)

**Files:** none (verification only)

This task needs the user at the keyboard — the agent cannot press Win+Ctrl or speak.

- [ ] **Step 1: Full test suite**

Run: `python -m pytest -v`
Expected: ~46 tests, all pass.

- [ ] **Step 2: Ask the user to put their OpenAI API key in `config.json`**, then run:

Run: `python -m app --check`
Expected: prints provider + model, records 2 s while the user speaks, prints the transcript. If HTTP 401 → key is wrong. If mic error → run `python -m app --list-devices` and set `input_device`.

- [ ] **Step 3: Launch the app**

Run: `python -m app --verbose` (console visible for debugging)
Expected: gray mic in tray, no errors in console.

- [ ] **Step 4: Hand the user this manual checklist** (each line must pass)

1. Open Notepad. **Hold Win+Ctrl**, say "hello this is a test", release → text appears in Notepad with a trailing space; clipboard holds the same text.
2. **Tap Win+Ctrl** quickly → overlay shows ● Recording; speak a longer sentence; tap again → text appears.
3. Start a recording, press **Esc** → cancels, nothing pasted.
4. Speak Mandarin (e.g. 「今天天氣很好」) → Traditional Chinese appears (今天天氣很好 — no Simplified 气).
5. **Win+Ctrl+Right** → virtual desktop switches normally; no recording left running; no paste.
6. Press and release **Win alone** → Start menu opens normally (we didn't break it). Then hold Win+Ctrl and dictate → Start menu does NOT open afterward.
7. Tray → Language → 中文; dictate Mandarin again (accuracy should be equal or better). Set back to Auto.
8. Tray → UI language → 繁體中文 → menus switch language.
9. Tray → Open history → entries present with text.
10. Quit from tray → process exits (check no `python` left in Task Manager).

- [ ] **Step 5: Fix anything that fails, re-test, then final commit**

```bash
git add -A
git commit -m "chore: post-verification fixes"
```

---

## Plan self-review notes

- **Spec coverage:** config/env keys (T2), bilingual UI (T3), OpenCC + spacing (T4), OpenAI+Groq+factory (T5), chord machine incl. tap/hold/Esc/passthrough/Start-menu hint (T6), recorder 16k mono + min/max duration + beeps (T7), history + clipboard-paste injection + modifier-release wait (T8), click-through overlay (T9), tray + startup shortcut (T10), wiring/worker/retry/auto-stop/single-instance/--check/--list-devices/custom-hotkey-fallback (T11), README incl. UIPI + cost + privacy (T12), live checklist incl. Start-menu suppression & desktop-shortcut passthrough (T13). `local` provider = documented future slot (factory error message + README), per spec non-goals.
- **Known judgment calls baked in:** Esc passes through to the focused app while cancelling (listen-only hook is safer than global suppression); custom hotkeys are toggle-only; clipboard intentionally not restored.
- **Type consistency:** `process(text, append_space)`, `transcribe(wav_bytes, language, prompt)`, `handle(etype, key) -> bool`, `external_stop()/force_start()/pipeline_done()` used consistently across tasks.
