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

## Starting & quitting

- **Start:** double-click the **VoiceToText** icon on your Desktop (runs in the
  background, no console window — a mic icon appears in the system tray). Create or
  remove this icon any time from the tray → **Desktop shortcut**.
- **Quit:** right-click the tray mic → **Quit**.
- **Auto-start:** tray → **Start with Windows** so it's always running after you log in.

(You can also double-click `run.bat`, or run `python -m app` from a terminal for
debugging.)

## Using it

| Action | Result |
|---|---|
| **Hold Win+Ctrl**, speak, release | Push-to-talk: text appears at your cursor |
| **Tap Win+Ctrl** (quick press) | Recording stays on; tap again to finish |
| **Esc** while recording | Cancel (note: the Esc also reaches the active app) |
| Win+Ctrl+←/→ etc. | Cancels recording and works normally (passes through) |

Your clipboard is left untouched — the app copies the text, pastes it, then restores
whatever was on your clipboard before. Every dictation is saved to `history.jsonl`
(tray → Open history).

- Recording auto-stops after 5 minutes (configurable `max_recording_s`).
- Recordings shorter than 0.3 s are ignored.

## Command mode — voice-edit selected text

Select some text, then **hold Win+Alt** and speak an instruction ("make this formal",
"summarize", "turn into bullet points", "translate to English") — release and the
selection is replaced with the result. Like dictation, you can also **tap Win+Alt** to
start hands-free and tap again to finish. The overlay shows a purple waveform while it
listens, then "Applying: …" with your instruction while it works. Change or disable the
key with `command_hotkey` in config.json (set it to `""` to disable).

**Add a word to the dictionary by voice:** select the word (or short term) anywhere, hold
Win+Alt, and say **"add to dictionary"**. The selected text is added immediately, with an
Undo notice. You must have some text **selected** when you speak, and it must be a short
term (a word or phrase, not a whole sentence). The tray → **Add words…** dialog is the
no-voice alternative.

## Snippets & spoken formatting

- **Snippets:** add `"trigger phrase": "expansion"` pairs to `snippets` in config.json.
  Dictating *only* that phrase pastes the expansion verbatim, e.g.:
  ```json
  "snippets": { "my email": "matt@example.com", "sign off": "Best,\nMatt" }
  ```
- **Spoken formatting:** dictating just "new line" or "new paragraph" inserts the break
  (toggle with `spoken_formatting`). Both match only when they're the whole utterance,
  so they won't fire mid-sentence.

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

The easy way: tray → **Add words…**, type one or more words (names, jargon, product
names) — one per line or separated by commas — and they're added to your dictionary
**immediately**, no restart. To delete one, tray → **Remove word** lists your dictionary
(auto-added words are marked `(auto)`) — click one to remove it. Or edit `config.json` →
`cleanup.dictionary` directly and restart.
Dictionary words guide the cleanup pass toward spelling them right. (They are not sent as
a transcription hint — a non-English vocabulary list there biased the model into
translating, so spelling is fixed during cleanup instead.)

### Auto-learning the dictionary (opt-in)

Set `learn.enabled` to `true` and the app will watch for corrections you make to dictated
text and add the fixed names/terms to `cleanup.dictionary` automatically. It reads the
focused field via Windows UI Automation, so it works in many apps (Word, most native
fields, many Electron apps) but not all (terminals and some custom editors don't expose
their text — there it simply does nothing). It learns conservatively (close
single-word fixes only, skipping common words) so it won't fill your dictionary with
junk, and learning happens the next time you dictate in the same field.

A word is only promoted into the dictionary after you've made the **same rewrite more
than twice** (the 3rd time) — set the threshold with `learn.promote_after`. Words seen
once or twice show up under **Pending corrections** in the dashboard. When a word is
auto-added, a notice appears after that dictation — "Added 'X' automatically" — with an
**Undo** button and an **✕** to dismiss (it also auto-dismisses after a few seconds).

## Dashboard

Tray → **Dashboard** opens an offline HTML page in your browser showing:

- your **dictionary**, split into **Saved** (you added) and **Auto-added** (learned);
- **cost & usage by day** (estimated cost, dictations, words — last 14 days);
- **trends** — language split (English/Mandarin/mixed), average words per dictation,
  busiest day, total time saved;
- **pending corrections** — words you've rewritten once/twice that are close to being
  learned.

Cost is an *estimate* (audio minutes × the model's per-minute rate), not your real
invoice.

### Cleanup style

`config.json` → `cleanup.style`: `light` (punctuation + fillers only, nearly verbatim),
`balanced` (default — also tidies grammar and adds paragraphs), or `heavy` (also
reformats into lists/emails and rephrases for clarity).

### App-aware output

When `cleanup.app_aware` is on (default), the app detects which program you're dictating
into and adapts the cleanup tone/formatting: casual in Slack/Discord, polished in
email, code-verbatim in editors (VS Code, PyCharm…), clean prose in docs. Override or
extend the built-in rules via `cleanup.app_styles`, e.g.:

```json
"app_styles": [
  { "match": "obsidian", "style": "Markdown notes; use bullet points." },
  { "match": "acme-crm", "style": "Formal, third-person." }
]
```

Each rule's `match` is a case-insensitive substring tested against the focused app's
process name + window title; your entries are checked before the built-ins, first match
wins.

### Cleanup endpoint (advanced)

Cleanup runs on its **own** OpenAI-compatible chat endpoint, separate from
transcription — so you can transcribe with any provider (including ElevenLabs, which has
no chat endpoint) and still clean up with OpenAI. By default it uses OpenAI
(`cleanup.base_url` = `https://api.openai.com/v1`; `cleanup.api_key` falls back to your
OpenAI key / `OPENAI_API_KEY`). To clean up with Groq's Llama models instead, set
`cleanup.base_url` to `https://api.groq.com/openai/v1`, `cleanup.api_key` to your Groq
key, and `cleanup.model` to e.g. `llama-3.3-70b-versatile`.

## Tray menu

Right-click the tray icon for: **Clean up text** toggle · **Cleanup style** (light/
balanced/heavy) · **Language** · **Provider** (OpenAI/ElevenLabs/Groq — switches live) ·
**UI language** · **Recent** (last 8 dictations — click to copy to clipboard) · **Add words…** ·
**Remove word** (click a word to delete it) · **Dashboard** (dictionary, cost/usage,
trends) · **Usage stats** · **Retry last recording** · **Open history** (searchable) ·
**Open config** · **Help** (everything the app does) · **Start with Windows** ·
**Desktop shortcut** · **Quit**.

Near-silent recordings are skipped before hitting the API (no wasted cost) — tune the
sensitivity with `silence_threshold` in config.json (`0` disables it).

## Switching providers / models

Set `"provider"` in `config.json` to `openai`, `elevenlabs`, or `groq`, and put the
matching key under `providers.<name>.api_key` (or its env var):

- **openai** (default): `gpt-4o-transcribe` (best English, ~US$0.006/min),
  `gpt-4o-mini-transcribe` (cheaper, ~US$0.003/min), or `whisper-1`.
  Key: `OPENAI_API_KEY`.
- **elevenlabs**: ElevenLabs Scribe — best published Mandarin accuracy (~US$0.004–0.008
  /min). Model `scribe_v1` (default) or `scribe_v2` (newer/more accurate if your account
  has it). Key: `ELEVENLABS_API_KEY` (get one at elevenlabs.io). Note: Scribe ignores the
  vocabulary hint at transcription time, but your dictionary still applies in cleanup.
- **groq** (free tier): `whisper-large-v3-turbo`, fast and cheap. Key: `GROQ_API_KEY`.
- A local/offline provider (e.g. Qwen3-ASR / Whisper) is a planned future option
  (`app/providers/` is designed for drop-in additions).

### A/B testing transcription quality

To compare on your own voice, switch `"provider"` between `openai` and `elevenlabs`
(fill in both keys), restart, and dictate the same English and Mandarin phrases. The
cleanup pass and the Traditional-Chinese guarantee apply identically to both, so you're
comparing raw transcription quality. Keep whichever wins. ElevenLabs tends to lead on
Mandarin; OpenAI on English — your accent and mic decide the real winner.

## Custom hotkey

`"hotkey"` in config.json. The default `"ctrl+windows"` gets the full hold/tap
behavior. Any other value (e.g. `"f8"`) uses simple toggle mode (Esc cancel not
available there).

## Troubleshooting

- **Cursor isn't in a text box** — if you dictate while focus is on something that
  can't accept text (a button, the desktop, etc.), the app detects it and shows the
  transcript in a small overlay with a **Copy** button (and an **✕** to dismiss) for a
  few seconds, instead of pasting into nowhere. It's also saved to history.
- **Nothing pastes into an admin window** — Windows blocks simulated input into
  elevated apps. The transcript is saved in history (tray → **Recent** / **Open
  history**); or run this app as admin too.
- **No tray icon / import errors** — re-run `python -m pip install -r requirements.txt`;
  if a package fails on Python 3.14 (Store version), install Python 3.12 from
  python.org and use that.
- **Hotkey doesn't fire in some game/app** — apps running elevated also swallow
  hooks; run this app as admin.
- **API errors** — check `app.log`; failed audio is kept as `last_recording.wav`,
  tray → Retry last recording.
- Logs: `app.log` (rotates at 1 MB). Verbose console: `python -m app --verbose`.

## Privacy & cost

Audio is sent to your configured transcription provider (OpenAI, ElevenLabs, or Groq),
and — when cleanup is on — the transcript text is sent to your cleanup provider (OpenAI
by default). Nothing else leaves your machine; history/audio stay in this folder.
Transcription ≈ US$0.003–0.008 per minute; cleanup ≈ US$0.0001 per dictation.
