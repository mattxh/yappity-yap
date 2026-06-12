# Voice-to-Text Dictation App — Design

**Date:** 2026-06-12
**Status:** Approved by user
**Platform:** Windows 11, Python 3.14 (user has Windows Store Python 3.14.5)

## Goal

A Wispr-Flow-style dictation tool for personal use. Runs in the background with a tray
icon. Press **Win+Ctrl** to record the microphone; on stop, the audio is transcribed
(OpenAI by default, swappable providers) and the text is pasted into whatever app has
focus. Works for spoken **English and Mandarin**, with Chinese output guaranteed to be
**Traditional Chinese**. App UI (tray menus, notifications) is bilingual EN / 繁體中文.

## User decisions (locked)

| Decision | Choice |
|---|---|
| Hotkey behavior | Dual mode: hold Win+Ctrl = push-to-talk; quick tap = toggle on/off |
| Output | Paste at cursor in active app + transcript stays on clipboard |
| Spoken Chinese | Mandarin (output always Traditional characters) |
| Provider | OpenAI default (user has API key); architecture supports swapping |
| Stack | Python tray app |

## Non-goals (v1)

- No local/offline transcription (documented as a future provider slot only)
- No GUI settings window (config file + tray menu only)
- No streaming/real-time partial transcripts; transcription happens after recording stops
- No audio device picker UI (config option + `--list-devices` CLI flag)
- No packaging to .exe (possible later via PyInstaller; v1 runs via pythonw)

## Architecture

Single Python process. Threads:

1. **Main thread** — pystray tray icon event loop.
2. **Keyboard hook thread** — `keyboard` library low-level hook; runs the chord state
   machine and emits events (start/stop/cancel) onto an internal queue/callbacks.
3. **Worker thread** — executes the record → transcribe → post-process → inject
   pipeline so the hook thread never blocks.
4. **Overlay thread** — tkinter mainloop for the status pill; receives commands via a
   thread-safe queue (all tk calls stay on this thread).

Audio capture itself runs on sounddevice's internal callback thread into a buffer owned
by the recorder.

### Pipeline per dictation

```
chord down ──► recorder.start()
release/tap-stop ──► recorder.stop() → WAV bytes (16 kHz mono int16)
              ──► provider.transcribe(wav, language, prompt) → raw text
              ──► postprocess (OpenCC s2twp on Han text, spacing rule) → final text
              ──► inject (set clipboard → simulate Ctrl+V)
              ──► history.append(...)
```

## Module breakdown

```
VoiceToText/
  app/
    __main__.py          # entry point: config load, single-instance lock, wiring, CLI flags
    hotkey.py            # ChordStateMachine (pure logic) + KeyboardHookAdapter (keyboard lib)
    recorder.py          # sounddevice capture → WAV bytes; min/max length enforcement
    providers/
      base.py            # TranscriptionProvider protocol: transcribe(wav_bytes, language, prompt) -> str
      openai_provider.py # multipart POST https://api.openai.com/v1/audio/transcriptions
      groq_provider.py   # same wire format, base_url https://api.groq.com/openai/v1, whisper-large-v3
    postprocess.py       # OpenCC s2twp conversion when Han chars present; trailing-space rule
    inject.py            # clipboard set (unicode) + simulated Ctrl+V
    overlay.py           # tkinter pill, WS_EX_NOACTIVATE | WS_EX_TRANSPARENT via ctypes
    tray.py              # pystray icon, states + menu
    notify.py            # Windows toast/balloon notifications (via pystray notify)
    config.py            # load/validate config.json, env-var fallback for keys, defaults
    history.py           # append-only history.jsonl
    i18n.py              # EN / zh-TW string tables for tray + notifications
    startup.py           # create/remove shortcut in shell:startup
  tests/                 # pytest: state machine, postprocess, config, provider parsing
  config.example.json
  requirements.txt
  README.md              # setup, API key, autostart, troubleshooting (UIPI/admin note, hotkey conflicts)
  run.bat                # pythonw -m app  (no console window)
```

## Hotkey state machine (`hotkey.py`)

States: `IDLE`, `CHORD_HELD` (recording, hold pending classification), `TOGGLED`
(recording hands-free), `BUSY` (transcribing; new chords ignored until done).

- Chord = both Ctrl (either side) and Win (either side) down, in any order, with no
  other key in between.
- On chord complete → start recording immediately, note timestamp.
- Chord released `< tap_threshold_ms` (default 400) → enter `TOGGLED` (keep recording).
- Chord released `>= tap_threshold_ms` → stop → transcribe (push-to-talk).
- In `TOGGLED`: next chord tap OR Esc → stop → transcribe.
- Esc while recording (either state) → cancel, discard audio, brief cue.
- Any *other* key pressed while chord held (e.g. Win+Ctrl+Left) → cancel recording,
  pass keys through — Windows virtual-desktop shortcuts keep working.
- **Start-menu suppression:** after a chord interaction, inject a benign keypress
  (e.g. VK 0xFF) before Win keyup propagates, so the Start menu does not open.
- Auto-stop: recording force-stops at `max_recording_s` (default 300) with notification.
- Hotkey chord configurable (`hotkey: "ctrl+windows"` default). Non-chord fallbacks
  like `f8` also accepted (plain `keyboard.add_hotkey` path).
- The state machine is a pure class fed synthetic key events in tests; the
  `keyboard`-library adapter around it is a thin shim.

## Recording (`recorder.py`)

- 16 kHz, mono, int16 (optimal for speech models; ~1.9 MB/min, well under API limits).
- Device: Windows default input; `input_device` config override; `--list-devices` flag.
- Recordings shorter than 0.3 s are discarded silently (accidental taps).
- Start/stop/cancel beep cues via `winsound` (config `beeps: true`).
- On stop, produces in-memory WAV bytes; also written to `last_recording.wav` until
  transcription succeeds (crash/network safety).

## Providers

Protocol: `transcribe(wav_bytes: bytes, language: str | None, prompt: str | None) -> str`.
Plain `requests` multipart POST (no OpenAI SDK dependency; keeps both providers symmetric).

- **openai** (default): model from config — default `gpt-4o-mini-transcribe`
  (~US$0.003/min); alternatives `gpt-4o-transcribe`, `whisper-1`. Key from
  `providers.openai.api_key` or `OPENAI_API_KEY` env var.
- **groq**: `whisper-large-v3-turbo` at `https://api.groq.com/openai/v1` — same wire
  format; proves provider swap works; generous free tier. Key via config or `GROQ_API_KEY`.
- **local** (future): documented stub raising "not implemented; see README".

Timeout 60 s. One automatic retry on network error / 5xx / 429 (2 s backoff).

## Language & Traditional Chinese (`postprocess.py`, provider params)

- `language: "auto" | "en" | "zh"` (config + tray override). Auto = omit language param;
  model detects per utterance (handles mixed EN/中文 sentences).
- When pinned `zh`: send `language=zh` plus a short **Traditional-Chinese prompt** to
  bias the decoder toward Traditional script.
- **Guarantee:** post-transcription, if the text contains any Han characters
  (`一-鿿` and extensions), run OpenCC **`s2twp`** (Simplified → Traditional,
  Taiwan phrasing). Idempotent on already-Traditional text.
- Spacing rule: a trailing space is appended to the pasted text itself when it ends
  with a non-CJK word character (chains English dictation nicely); no trailing space
  after CJK. Config `append_space: true`.

## Output injection (`inject.py`)

- Set Unicode clipboard text, then simulate **Ctrl+V** (`keyboard.send`). Clipboard is
  *not* restored — transcript intentionally remains as backup (user decision).
- 150 ms settle delay between clipboard set and paste (clipboard propagation).
- Known limitation documented in README: focused apps running elevated (as Admin)
  ignore simulated input from a non-elevated process (Windows UIPI). Text remains on
  clipboard; run the app elevated if dictating into admin windows.

## Overlay (`overlay.py`)

- Small dark pill, bottom-center: `● Recording — Esc to cancel` / `✍ Transcribing…`
  (localized). Disappears when done. Red/orange accent matches tray state.
- tkinter `overrideredirect` window; after creation, apply `WS_EX_NOACTIVATE |
  WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW` via ctypes so it is click-through and **never
  steals focus** (critical: focus loss would break the paste target).
- Lives on its own thread with a command queue. Config `show_overlay: true`.

## Tray (`tray.py`)

Icon states: idle (gray mic), recording (red), transcribing (orange). Generated with
Pillow at runtime (no asset files).

Menu: status line · Language ▸ (Auto / English / 中文) · Retry last ·
Open history · Open config · Start with Windows ✓ · UI language ▸ (English / 繁體中文) ·
Quit. Language/UI-language changes persist back to config.json.

## Config (`config.json`, gitignored; `config.example.json` committed)

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

Missing keys fall back to defaults; unknown keys warn. Missing API key at startup →
notification + tray still loads (so user can fix config and use "Open config").

## Errors, logging, lifecycle

- Pipeline failure → toast with reason (localized), audio kept at `last_recording.wav`,
  tray **Retry last** re-runs transcription of that file.
- Rotating log `app.log` (1 MB × 3). `--verbose` flag for console debug.
- **Single instance:** bind a localhost socket (fixed port) at startup; if taken, show
  "already running" notification and exit.
- `--check` flag: validates config, lists chosen device, records 2 s, sends to provider,
  prints transcript — end-to-end smoke test.
- Clean shutdown from tray Quit: unhook keyboard, stop streams, close overlay.

## History (`history.jsonl`)

One JSON object per dictation: `{ts, lang, duration_s, chars, text}`. Tray "Open
history" opens it in the default editor. Gitignored.

## Startup with Windows (`startup.py`)

Tray toggle creates/removes `VoiceToText.lnk` in `shell:startup` pointing to
`pythonw -m app` with the project working directory (via PowerShell WScript.Shell —
no extra dependency).

## Testing strategy

- **pytest units (no hardware):** chord state machine transitions (tap/hold/Esc/other-key
  cancel/auto-stop), postprocess (Simplified→Traditional, mixed text, spacing rule),
  config defaults/validation, provider request building + response parsing (mocked HTTP),
  history append, i18n completeness (every key in both languages).
- **Manual integration:** `--check` end-to-end; live hotkey behavior checklist in README
  (hold, tap-toggle, Esc, Win+Ctrl+arrow passthrough, Start-menu suppression).
- Hook/tray/audio/tk seams are thin adapters; logic stays import-safe on any machine.

## Dependencies

`requests`, `sounddevice`, `keyboard`, `pystray`, `Pillow`, `pyperclip`,
`opencc-python-reimplemented` (pure-Python OpenCC), `pytest` (dev).

## Risks & mitigations

| Risk | Mitigation |
|---|---|
| Python 3.14 wheels missing for a dep (sounddevice/Pillow/cffi) | All have 3.14 wheels as of 2026; verified at install time in Phase 1. Fallback: install python.org 3.12 alongside. |
| Windows Store Python + global keyboard hook quirks | Hooks are standard user-level; if Store Python misbehaves, README documents python.org install. |
| Win-up opens Start menu despite suppression | Dummy-key trick is the standard AutoHotkey-proven approach; fallback hotkey (e.g. F8) configurable. |
| Whisper emits Simplified Chinese | OpenCC s2twp post-pass guarantees Traditional regardless of model behavior. |
| Paste lands in wrong/no window | Transcript always on clipboard + in history.jsonl + notification on failure. |
