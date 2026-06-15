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
