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
