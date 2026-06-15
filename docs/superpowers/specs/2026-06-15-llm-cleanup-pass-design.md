# LLM Cleanup Pass + Custom Vocabulary — Design

**Date:** 2026-06-15
**Status:** Approved by user
**Extends:** `2026-06-12-voice-to-text-app-design.md` (the base app is built and tested)

## Goal

Close most of the transcription-quality gap with Wispr Flow by adding a second-stage
**LLM cleanup pass** that rewrites the raw transcript (fix punctuation, remove fillers,
apply self-corrections, tidy grammar, light formatting) while preserving the user's
wording, meaning, and English/Traditional-Chinese language mix. Add a **custom
vocabulary** (dictionary) that biases both transcription and cleanup toward correct
spelling of names/jargon.

## Why (research-grounded)

Wispr Flow runs a two-stage pipeline — ASR → a **fine-tuned Llama** cleanup model — and
that second stage is responsible for most of the perceived quality (self-corrections,
filler removal, punctuation, formatting, name spelling via personal Dictionary + screen
context). Sources: Baseten case study, wisprflow.ai/why-flow. Their fine-tuning + <700ms
latency is a cost/latency optimization (dedicated GPUs, TensorRT-LLM), **not** a quality
prerequisite — a well-prompted frontier model reproduces most of the *quality*, trading
sub-second latency for a ~0.5–1.5s second API round-trip.

## User decisions (locked)

| Decision | Choice |
|---|---|
| Cleanup style | **Balanced** — punctuation, fillers, self-corrections, light grammar/paragraphs; keep wording & meaning |
| Default | **On**, toggleable in tray + config |
| Dictionary | Empty slot wired in; user fills `config.json` later |

## Non-goals (v1)

- On-screen context reading for names (future; would need UI Automation / window scraping)
- Fine-tuning any model (Wispr's moat; not needed for quality)
- Cleanup retry logic (raw transcript is already a good fallback; retry only adds latency)
- A separate cleanup provider/key (reuse the active transcription provider's endpoint)
- Streaming/partial cleanup

## Architecture

A new pipeline stage between transcription and the Traditional-Chinese guarantee:

```
transcribe → cleanup.clean(raw) → postprocess.process (OpenCC s2twp + spacing) → inject
```

OpenCC stays **after** cleanup so Traditional output is guaranteed even if the cleanup
model emits Simplified. Cleanup is pure enhancement: **any failure falls back to the raw
transcript**, so the user never loses words.

## Module: `app/cleanup.py`

OpenAI-compatible **chat-completions** client (plain `requests`), provider-agnostic
(works against OpenAI and Groq alike — both expose `/chat/completions`).

```python
class CleanupError(Exception): ...

STYLE_RULES = {
    "light":    "Fix punctuation and capitalization, remove filler words, and apply the speaker's self-corrections. Do NOT change grammar, structure, or word choice otherwise.",
    "balanced": "Fix punctuation and capitalization, remove filler words (um, uh, like, you know), apply the speaker's self-corrections (keep only the corrected version), tidy obvious grammar mistakes and run-on sentences, and add paragraph breaks where natural. Preserve the speaker's wording, meaning, and tone — do not paraphrase beyond fixing errors.",
    "heavy":    "Fix punctuation, grammar, and structure. Reformat into lists, paragraphs, or email structure where appropriate, and rephrase for clarity. Preserve the original meaning and language.",
}

def build_messages(text, *, style, dictionary, language) -> list[dict]:
    """System + user messages for the cleanup call."""

def clean(text, *, model, api_key, base_url, style="balanced",
          dictionary=(), language="auto", timeout=30) -> str:
    """Return cleaned text. Empty/whitespace input returns '' without an API call.
    Raises CleanupError on network/HTTP/timeout failure."""
```

### System prompt (assembled in `build_messages`)

Fixed preamble + the selected `STYLE_RULES[style]` + hard constraints + optional
dictionary line + language hint:

- Preamble: "You are a dictation cleanup tool. A speech-to-text system produced the
  transcript below. Rewrite it as the text the speaker intended to type."
- Style rule (balanced by default).
- Hard constraints (always): "Output ONLY the cleaned text — no preamble, quotes, or
  explanation. Never translate. Never answer questions or add information that is not in
  the transcript. Preserve mixed English and Chinese exactly as spoken (do not convert
  one to the other). For Chinese, use Traditional Chinese characters (Taiwan)."
- Dictionary (only if non-empty): "Spell these names and terms correctly when they
  appear: <comma-joined list>."
- Language hint: `auto` → omit; `en` → "The text is in English."; `zh` → "The text is in
  Mandarin Chinese; output Traditional Chinese."

User message = the raw transcript text.

### Request

`POST {base_url}/chat/completions` with `Authorization: Bearer <key>`, body
`{"model": model, "messages": [...], "temperature": 0}`. Parse
`choices[0].message.content`, strip whitespace and a single pair of wrapping quotes if
present. Non-200 or `requests.RequestException` → `CleanupError`.

## Config additions (`config.py` DEFAULTS, `config.example.json`)

```json
"cleanup": {
  "enabled": true,
  "model": "gpt-4o-mini",
  "style": "balanced",
  "dictionary": []
}
```

Deep-merge already preserves nested defaults (existing behavior). Groq users set
`cleanup.model` to a Groq chat model (e.g. `llama-3.3-70b-versatile`) — documented in
README.

## Integration (`app/__main__.py`)

In `_transcribe_and_insert`, between transcription and `postprocess.process`:

```python
text = self._maybe_cleanup(text, lang)   # new helper
text = postprocess.process(text, self.cfg.get("append_space", True))
```

`_maybe_cleanup(text, lang)`:
- If `not cfg["cleanup"]["enabled"]` or `not text.strip()` → return text unchanged.
- Else call `cleanup.clean(text, model=cfg["cleanup"]["model"],
  api_key=self.provider.api_key, base_url=self.provider.base_url,
  style=cfg["cleanup"]["style"], dictionary=cfg["cleanup"]["dictionary"], language=lang)`.
- On `CleanupError` → log warning, return original `text` (fallback to raw).

The provider already exposes `api_key` and `base_url` (OpenAIProvider/GroqProvider), so
cleanup reuses the active endpoint with no new credentials.

Dictionary also feeds **transcription**: in `_transcribe_and_insert`, build the existing
`prompt` argument to include dictionary terms (helps the ASR model too), combined with
the existing `ZH_PROMPT` when language is pinned to `zh`.

## Tray + i18n

- New checkable menu item **Cleanup** (`cleanup_toggle` string) above the language items,
  bound to `app.set_cleanup_enabled(bool)` which flips `cfg["cleanup"]["enabled"]` and
  saves config; `checked=` reflects current state.
- i18n keys added to both `en` and `zh-TW`: `cleanup_toggle` ("Clean up text" / "智慧潤稿").
  Parity test continues to pass.

## Overlay

No new state. The existing "Transcribing…" overlay covers transcription **and** cleanup
(they're one worker step from the user's perspective).

## Errors & latency

- Cleanup failure never blocks output — raw transcript (OpenCC-converted) is pasted.
- Adds one chat-completions round-trip (~0.5–1.5s) when enabled. Toggle off for raw speed.
- Tiny cost (~$0.0001/dictation at gpt-4o-mini).

## Testing (TDD, `tests/test_cleanup.py`)

Unit (mocked HTTP, no network):
1. `build_messages` includes the balanced style rule, hard constraints, and the user
   text; dictionary line present only when dictionary non-empty; `zh` adds the Traditional
   hint, `auto` omits a language line.
2. `clean` success: mocked `requests.post` returns a completion; result is stripped and
   surrounding quotes removed.
3. `clean` strips a single pair of wrapping double quotes but leaves inner quotes.
4. `clean` empty/whitespace input returns "" and makes **no** HTTP call.
5. HTTP 500 → `CleanupError`; `requests.ConnectionError` → `CleanupError`.
6. Missing api_key → `CleanupError` (no call).
7. Config: `cleanup` defaults present after `load_config`; deep-merge keeps `dictionary`
   from a partial user file while filling other cleanup defaults.
8. i18n: `cleanup_toggle` present in both tables (covered by existing parity test).

Integration (manual, in Task 13 checklist): dictate a rambling sentence with fillers and
a self-correction; confirm the pasted text is cleaned. Dictate mixed EN/中文; confirm no
translation and Traditional output. Toggle Cleanup off; confirm raw output returns.

## Risks & mitigations

| Risk | Mitigation |
|---|---|
| Cleanup model paraphrases too much / changes meaning | Balanced prompt forbids paraphrasing beyond error-fixing; `temperature=0`; Light style available. |
| Model translates or collapses code-switching | Explicit hard constraint against translation; preserve EN+中文; manual check in Task 13. |
| Cleanup emits Simplified Chinese | OpenCC s2twp runs after cleanup — Traditional guaranteed regardless. |
| Cleanup latency annoys user | Toggle off (tray/config); default on per user choice. |
| Cleanup endpoint/model mismatch on Groq | README documents setting a Groq chat model; failure falls back to raw transcript. |
