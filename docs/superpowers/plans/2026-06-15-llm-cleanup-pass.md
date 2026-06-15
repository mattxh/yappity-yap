# LLM Cleanup Pass + Custom Vocabulary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a second-stage LLM cleanup pass (and a custom-vocabulary dictionary) to the VoiceToText pipeline so dictated text comes out polished — punctuation, filler removal, self-corrections, light formatting — while preserving the user's wording and English/Traditional-Chinese mix.

**Architecture:** A new `app/cleanup.py` calls the active provider's OpenAI-compatible `/chat/completions` endpoint to rewrite the raw transcript. It slots into the worker pipeline between transcription and the OpenCC Traditional-Chinese guarantee. Cleanup is pure enhancement: on any failure the raw transcript is used. A tray toggle and config block control it; the dictionary also biases the transcription prompt.

**Tech Stack:** Python 3.14, `requests` (already a dep), existing `config`/`i18n`/`postprocess`/`providers` modules, `pytest`.

**Spec:** `docs/superpowers/specs/2026-06-15-llm-cleanup-pass-design.md`

**Working directory for all commands:** project root (`VoiceToText/`). Tests: `python -m pytest`.

---

### Task 1: Cleanup module (`app/cleanup.py`)

**Files:**
- Create: `app/cleanup.py`
- Test: `tests/test_cleanup.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_cleanup.py
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_cleanup.py -q`
Expected: collection error / FAIL (module `app.cleanup` missing)

- [ ] **Step 3: Implement `app/cleanup.py`**

```python
"""Second-stage LLM cleanup of the raw transcript (OpenAI-compatible chat).

Provider-agnostic: hits {base_url}/chat/completions, which both OpenAI and Groq
expose. Cleanup is enhancement only — callers fall back to the raw transcript on
CleanupError, so this never blocks output.
"""
import logging

import requests

log = logging.getLogger(__name__)


class CleanupError(Exception):
    pass


STYLE_RULES = {
    "light": (
        "Fix punctuation and capitalization, remove filler words, and apply the "
        "speaker's self-corrections. Do NOT change grammar, structure, or word "
        "choice otherwise."
    ),
    "balanced": (
        "Fix punctuation and capitalization, remove filler words (um, uh, like, you "
        "know), apply the speaker's self-corrections (keep only the corrected "
        "version), tidy obvious grammar mistakes and run-on sentences, and add "
        "paragraph breaks where natural. Preserve the speaker's wording, meaning, and "
        "tone — do not paraphrase beyond fixing errors."
    ),
    "heavy": (
        "Fix punctuation, grammar, and structure. Reformat into lists, paragraphs, or "
        "email structure where appropriate, and rephrase for clarity. Preserve the "
        "original meaning and language."
    ),
}

_PREAMBLE = (
    "You are a dictation cleanup tool. A speech-to-text system produced the transcript "
    "below. Rewrite it as the text the speaker intended to type."
)

_CONSTRAINTS = (
    "Output ONLY the cleaned text — no preamble, quotes, or explanation. Never "
    "translate. Never answer questions or add information that is not in the "
    "transcript. Preserve mixed English and Chinese exactly as spoken (do not convert "
    "one to the other). For Chinese, use Traditional Chinese characters (Taiwan)."
)

_LANG_HINT = {
    "en": "The text is in English.",
    "zh": "The text is in Mandarin Chinese; output Traditional Chinese.",
}


def build_messages(text, *, style, dictionary, language):
    rule = STYLE_RULES.get(style, STYLE_RULES["balanced"])
    parts = [_PREAMBLE, rule, _CONSTRAINTS]
    if dictionary:
        parts.append("Spell these names and terms correctly when they appear: "
                     + ", ".join(dictionary) + ".")
    hint = _LANG_HINT.get(language)
    if hint:
        parts.append(hint)
    return [
        {"role": "system", "content": " ".join(parts)},
        {"role": "user", "content": text},
    ]


def _strip_wrapping_quotes(s: str) -> str:
    if len(s) >= 2 and s[0] == '"' and s[-1] == '"':
        return s[1:-1].strip()
    return s


def clean(text, *, model, api_key, base_url, style="balanced",
          dictionary=(), language="auto", timeout=30) -> str:
    if not text or not text.strip():
        return ""
    if not api_key:
        raise CleanupError("API key not configured")
    messages = build_messages(text, style=style, dictionary=dictionary, language=language)
    try:
        resp = requests.post(
            f"{base_url}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={"model": model, "messages": messages, "temperature": 0},
            timeout=timeout,
        )
    except requests.RequestException as e:
        raise CleanupError(str(e)) from e
    if resp.status_code != 200:
        raise CleanupError(f"HTTP {resp.status_code}: {resp.text[:200]}")
    try:
        content = resp.json()["choices"][0]["message"]["content"]
    except (KeyError, IndexError, ValueError, TypeError) as e:
        raise CleanupError(f"unexpected response: {e}") from e
    return _strip_wrapping_quotes(content.strip())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_cleanup.py -q`
Expected: 10 passed

- [ ] **Step 5: Commit**

```bash
git add app/cleanup.py tests/test_cleanup.py
git commit -m "feat: LLM cleanup pass (chat-completions transcript rewrite)"
```

---

### Task 2: Config defaults + example + i18n string

**Files:**
- Modify: `app/config.py` (add `cleanup` to `DEFAULTS`)
- Modify: `config.example.json`
- Modify: `app/i18n.py` (add `cleanup_toggle` to both tables)
- Test: `tests/test_config.py` (add a cleanup-defaults test)

- [ ] **Step 1: Write the failing test (append to `tests/test_config.py`)**

```python
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
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python -m pytest tests/test_config.py::test_cleanup_defaults_and_merge -q`
Expected: FAIL with `KeyError: 'cleanup'`

- [ ] **Step 3: Add `cleanup` block to `DEFAULTS` in `app/config.py`**

Insert into the `DEFAULTS` dict (after the `"append_space": True,` line, before the closing brace):

```python
    "append_space": True,
    "cleanup": {
        "enabled": True,
        "model": "gpt-4o-mini",
        "style": "balanced",   # light | balanced | heavy
        "dictionary": [],
    },
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest tests/test_config.py -q`
Expected: all config tests pass (6)

- [ ] **Step 5: Update `config.example.json`** (add the `cleanup` block before the final `}`)

```json
  "append_space": true,
  "cleanup": {
    "enabled": true,
    "model": "gpt-4o-mini",
    "style": "balanced",
    "dictionary": []
  }
}
```

(Make sure the line before `"cleanup"` ends with a comma.)

- [ ] **Step 6: Add `cleanup_toggle` to both i18n tables in `app/i18n.py`**

In the `"en"` table add: `"cleanup_toggle": "Clean up text",`
In the `"zh-TW"` table add: `"cleanup_toggle": "智慧潤稿",`

- [ ] **Step 7: Run i18n + config tests**

Run: `python -m pytest tests/test_i18n.py tests/test_config.py -q`
Expected: all pass (parity test confirms both tables still match)

- [ ] **Step 8: Commit**

```bash
git add app/config.py config.example.json app/i18n.py tests/test_config.py
git commit -m "feat: cleanup config defaults, example, and tray string"
```

---

### Task 3: Wire cleanup into the pipeline + tray toggle (`app/__main__.py`, `app/tray.py`)

**Files:**
- Modify: `app/__main__.py` (import `cleanup`; add `_build_transcription_prompt`, `_maybe_cleanup`, `toggle_cleanup`; call them in `_transcribe_and_insert`)
- Modify: `app/tray.py` (add the Cleanup checkable menu item)
- Test: `tests/test_app_pipeline.py`

`_maybe_cleanup` is written so it can be unit-tested with a lightweight stand-in for
`self` (no full `App` construction, which would spawn threads). Tests call the unbound
method `App._maybe_cleanup(fake_self, ...)`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_app_pipeline.py
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
```

- [ ] **Step 2: Run them to verify they fail**

Run: `python -m pytest tests/test_app_pipeline.py -q`
Expected: FAIL (`_maybe_cleanup` / `_build_transcription_prompt` not defined)

- [ ] **Step 3: Edit `app/__main__.py` imports**

Change the existing line:

```python
from . import config as config_mod
from . import history, inject, postprocess
```

to add `cleanup` (note: import the *module* so tests can monkeypatch `app.cleanup.clean`):

```python
from . import config as config_mod
from . import cleanup, history, inject, postprocess
```

- [ ] **Step 4: Replace the prompt line and add the cleanup call in `_transcribe_and_insert`**

Current body:

```python
        lang = self.cfg.get("language", "auto")
        language = None if lang == "auto" else lang
        prompt = ZH_PROMPT if lang == "zh" else None
        text = self._transcribe_with_retry(wav, language, prompt)
        if text is None:
            return  # already notified
        text = postprocess.process(text, self.cfg.get("append_space", True))
```

Replace with:

```python
        lang = self.cfg.get("language", "auto")
        language = None if lang == "auto" else lang
        prompt = self._build_transcription_prompt(lang)
        text = self._transcribe_with_retry(wav, language, prompt)
        if text is None:
            return  # already notified
        text = self._maybe_cleanup(text, lang)
        text = postprocess.process(text, self.cfg.get("append_space", True))
```

- [ ] **Step 5: Add the three helper methods to `App`** (place after `_transcribe_with_retry`)

```python
    def _build_transcription_prompt(self, lang):
        parts = []
        if lang == "zh":
            parts.append(ZH_PROMPT)
        terms = self.cfg.get("cleanup", {}).get("dictionary", [])
        if terms:
            parts.append("Vocabulary: " + ", ".join(terms) + ".")
        return " ".join(parts) if parts else None

    def _maybe_cleanup(self, text, lang):
        cu = self.cfg.get("cleanup", {})
        if not cu.get("enabled") or not text.strip():
            return text
        try:
            return cleanup.clean(
                text,
                model=cu.get("model", "gpt-4o-mini"),
                api_key=self.provider.api_key,
                base_url=self.provider.base_url,
                style=cu.get("style", "balanced"),
                dictionary=cu.get("dictionary", []),
                language=lang,
            )
        except cleanup.CleanupError as e:
            log.warning("cleanup failed, using raw transcript: %s", e)
            return text
```

- [ ] **Step 6: Add `toggle_cleanup` to `App`** (place after `set_ui_language`)

```python
    def toggle_cleanup(self):
        cu = self.cfg.setdefault("cleanup", {})
        cu["enabled"] = not cu.get("enabled", True)
        config_mod.save_config(self.cfg, self.cfg_path)
```

- [ ] **Step 7: Add the Cleanup menu item in `app/tray.py`**

In `build_menu()`, add this item immediately after the first separator (before the
Language submenu):

```python
            Menu.SEPARATOR,
            Item(lambda item: t("cleanup_toggle"),
                 lambda: (app.toggle_cleanup(), icon.update_menu()),
                 checked=lambda item: app.cfg.get("cleanup", {}).get("enabled", True)),
            Item(lambda item: t("language"), Menu(
```

(The existing `Item(lambda item: t("language"), Menu(` line stays; you are inserting the
separator + Cleanup item directly above it. Remove the now-duplicate separator that was
previously right after the status line so there are not two separators in a row — there
should be exactly one separator between the status line and the Cleanup item.)

- [ ] **Step 8: Run the pipeline tests + full suite**

Run: `python -m pytest tests/test_app_pipeline.py -q`
Expected: 5 passed
Run: `python -m pytest -q`
Expected: all pass
Run: `python -c "from app.tray import run_tray; import app.__main__; print('import ok')"`
Expected: `import ok`

- [ ] **Step 9: Commit**

```bash
git add app/__main__.py app/tray.py tests/test_app_pipeline.py
git commit -m "feat: wire cleanup pass into pipeline, dictionary into prompt, tray toggle"
```

---

### Task 4: README + verification checklist

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Add a "Cleanup & accuracy" section to `README.md`** (after the "Languages" section)

```markdown
## Cleanup & accuracy (the Wispr-style polish)

After transcription, the raw text is rewritten by a second AI pass that fixes
punctuation, removes filler words ("um", "uh"), applies your self-corrections
("5pm, actually 6" → "6pm"), tidies grammar, and adds light formatting — while keeping
your wording and your English/中文 mix intact. This is the single biggest quality lever
and is **on by default**.

- Toggle it from the tray (**Clean up text**) or `config.json` → `cleanup.enabled`.
  Off = the raw transcript pastes instantly (faster, no extra cost).
- It adds ~0.5–1.5s and a tiny cost (~US$0.0001/dictation at `gpt-4o-mini`).
- If the cleanup call fails for any reason, the raw transcript is used — you never lose
  words.

### Custom vocabulary

Add names, jargon, product names, or colleagues' names to `config.json` →
`cleanup.dictionary` (e.g. `["Adithya", "Anthropic", "Kubernetes"]`). These bias both
the transcription and the cleanup pass toward spelling them correctly.

### Cleanup style

`config.json` → `cleanup.style`: `light` (punctuation + fillers only, nearly verbatim),
`balanced` (default — also tidies grammar and adds paragraphs), or `heavy` (also
reformats into lists/emails and rephrases for clarity).

### Using Groq for cleanup

If you switch `provider` to `groq`, also set `cleanup.model` to a Groq chat model such as
`llama-3.3-70b-versatile` (the default `gpt-4o-mini` is OpenAI-only). Cleanup uses the
same provider endpoint and key as transcription.
```

- [ ] **Step 2: Extend the manual verification checklist** (add to the live-test list in the project; these are run by the user in the end-to-end check)

Add these checks to the README troubleshooting/usage or keep as a note for Task 13:

```markdown
- Dictate a rambling sentence with "um" and a self-correction → pasted text is clean.
- Dictate mixed English + Mandarin → no translation, Chinese stays Traditional.
- Tray → uncheck "Clean up text" → next dictation pastes the raw transcript.
```

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: document cleanup pass, dictionary, style, and Groq cleanup model"
```

---

## Plan self-review notes

- **Spec coverage:** `app/cleanup.py` with `build_messages`/`clean`/`CleanupError` and
  STYLE_RULES (T1); config `cleanup` block + example + `cleanup_toggle` i18n (T2);
  pipeline integration with cleanup→OpenCC order, raw-fallback on `CleanupError`,
  dictionary into transcription prompt, tray toggle, `toggle_cleanup` (T3); README for
  cleanup/dictionary/style/Groq + manual checks (T4). Non-goals (screen context,
  fine-tuning, retry, separate key) intentionally excluded.
- **Order guarantee:** cleanup runs before `postprocess.process`, so OpenCC s2twp remains
  the final Traditional-Chinese guarantee even if cleanup emits Simplified.
- **Type/signature consistency:** `clean(text, *, model, api_key, base_url, style,
  dictionary, language, timeout)` and `build_messages(text, *, style, dictionary,
  language)` are used identically in tests, the module, and `_maybe_cleanup`. The module
  is imported as `from . import cleanup` and called `cleanup.clean(...)` so the
  monkeypatch in `tests/test_app_pipeline.py` (patching `app.cleanup.clean`) takes effect.
- **No full-App construction in tests:** `_maybe_cleanup` / `_build_transcription_prompt`
  are tested via unbound-method calls with `SimpleNamespace` stand-ins, avoiding the
  thread-spawning `App.__init__`.
