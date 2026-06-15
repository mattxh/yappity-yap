# Feature Expansion + Hardening — Design

**Date:** 2026-06-16
**Status:** Approved by user (scope chosen; pending spec review)
**Extends:** the built app (base + cleanup + providers + overlay).

## Scope (user-selected)

1. **Hardening** — fix the thread-race and robustness bugs found in review.
2. **App-aware output** — adapt cleanup tone/format to the focused app.
3. **Command mode + snippets** — voice-edit selected text; spoken macro expansion; spoken formatting.
4. **Tray controls + history search + stats + silence guard.**
5. **Auto-learning dictionary** — learn corrected terms from the user's manual edits to
   inserted text (best-effort, opt-in).

Explicitly **out of scope** (deferred): local/offline transcription, real-time streaming,
whisper-mode.

Built in four phases, each its own plan + TDD + verify + commit, in the order above
(hardening first because it also creates structure the features build on).

---

## Phase 1 — Hardening

### Bugs (from review)
- `retry_last` / `_auto_stop` enqueue jobs without blocking a concurrent new recording.
- `_timer` touched by hook/timer/tray threads with no lock; stop can double-fire.
- `Recorder._close` swaps `_stream` outside `_lock`.
- `run_check` doesn't catch `TranscriptionError` (ugly traceback).
- Paste has no success/failure feedback; `done_notify` i18n string unused.
- `startup.py` PowerShell shortcut breaks on a path containing `'`.

### Design
- Add a **`PipelineController`** (new `app/pipeline.py`) owning: the job queue, the
  worker thread, a single `threading.Lock`, a `_busy` flag, the auto-stop `Timer`, and
  the `ChordMachine.pipeline_done()` call. It exposes:
  - `submit(wav, lang, *, on_done=None)` — under the lock, ignore if `_busy`; else set
    busy, enqueue. Returns bool (accepted).
  - `begin_recording_timer(seconds, on_timeout)` / `cancel_timer()` — lock-guarded.
  - the worker loop runs transcribe→cleanup→inject→history and clears `_busy` in
    `finally`.
  `App` delegates to it; this removes the god-object thread tangle and makes retry/
  auto-stop/hotkey-stop all funnel through one guarded `submit`.
- `Recorder._close`: take `_lock` around the `_stream` swap+stop; make idempotent
  (return b"" if already closed).
- `run_check`: wrap `provider.transcribe` in try/except `TranscriptionError` → print
  `ERROR: <msg>`, return 1.
- After a successful paste, `notifier.toast(t("done_notify", chars=len(text)))` —
  **only** when `cfg["notify_on_insert"]` (new, default `false`, so it's opt-in and not
  noisy); always log it. (Wires up the dead string without spamming by default.)
- `startup.py`: escape `'`→`''` in interpolated paths.

### Tests
- `PipelineController`: submit accepted once, rejected while busy, accepted again after
  worker finishes (inject a fake transcribe); timer set/cancel idempotent; on_done fired.
- `Recorder._close` idempotent (call twice → no error, second returns b"").
- `run_check` returns 1 and prints ERROR on a stubbed failing provider (capsys).
- `startup` path quoting: a path with `'` produces a script with `''`.

---

## Phase 2 — App-aware output

### Design
- New `app/appcontext.py`: `foreground_app() -> tuple[str, str]` returning
  `(process_name_lower, window_title)` via ctypes:
  `GetForegroundWindow` → `GetWindowTextW` (title) and `GetWindowThreadProcessId` +
  `OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION)` + `QueryFullProcessImageNameW`
  (exe basename). All wrapped in try/except → `("", "")` on failure. No new deps.
- `app/cleanup.py`: `build_messages` gains an optional `app_hint: str` → adds a system
  line: `"The user is typing into {app_hint}. {style_rule}"` where `style_rule` comes
  from matching the app against a style map.
- Config `cleanup.app_styles`: ordered list of `{ "match": "<substr>", "style":
  "<instruction>" }`, matched (case-insensitive substring) against `"{proc} {title}"`.
  Built-in defaults merged under user entries:
  - `slack`/`discord`/`whatsapp`/`telegram` → "Casual, conversational tone; lowercase is fine."
  - `gmail`/`outlook`/`mail` → "Polished email tone; greeting and sign-off only if dictated."
  - `code`/`devenv`/`pycharm`/`idea`/`cursor`/`sublime` → "This is a code editor; keep code identifiers, paths, and symbols verbatim; minimal prose."
  - `word`/`notion`/`docs` → "Clean prose with paragraph breaks."
  - default (no match) → balanced (no extra style line).
- `App` passes the resolved `app_hint` + style into the cleanup call (captured at stop
  time, on the worker via `appcontext.foreground_app()` — but the foreground at paste
  time may be the same target; capture once when transcription starts).
- Config `cleanup.app_aware` (bool, default `true`) to disable.

### Tests
- `appcontext.match_style(app_styles, proc, title)` (pure) → returns the right style for
  slack/gmail/code/unknown; user entries override defaults; first match wins.
- `cleanup.build_messages(..., app_hint="slack.exe Slack", style="...")` includes the
  app line and style; omitted when `app_hint` empty.

---

## Phase 3 — Command mode + snippets

### Command mode (voice-edit selected text)
- New configurable hotkey `command_hotkey` (default `"alt+windows"`). A second
  `KeyboardHookAdapter`-style trigger (or a `keyboard.add_hotkey` for non-chord configs)
  feeding a separate `ChordMachine` instance dedicated to command mode.
- Flow (on the worker, serialized through the same `PipelineController` busy-guard):
  1. Capture current selection: save clipboard, send Ctrl+C, read clipboard (the
     selected text). If empty after a short wait → toast "select text first", abort.
  2. Record the spoken instruction (reuse `Recorder`), transcribe it.
  3. `command.transform(selection, instruction, ...)` → chat-completions call with a
     prompt: "Apply the user's spoken instruction to the selected text. Output only the
     transformed text." (Uses the cleanup endpoint/model.)
  4. Replace selection: set clipboard to result, send Ctrl+V (the selection is still
     active → paste overwrites it).
- Overlay shows a distinct state `command` (purple dot + "Command…").

### Snippets (dictation mode)
- Config `snippets`: `{ "<trigger phrase>": "<expansion>" }`.
- After transcription in **dictation** mode, before cleanup: normalize the transcript
  (lowercase, strip surrounding punctuation/whitespace); if it exactly equals a snippet
  trigger, replace the whole text with the expansion and **skip cleanup** (paste verbatim).
- `snippet_match(text, snippets) -> str | None` (pure, tested).

### Spoken formatting (dictation mode)
- `apply_spoken_formatting(text)` (pure): map standalone tokens to characters/newlines:
  "new line"→`\n`, "new paragraph"→`\n\n`. Applied after cleanup, conservatively
  (only when the token stands alone as its own utterance segment). Config
  `spoken_formatting` (bool, default `true`).

### Tests
- `command.build_messages(selection, instruction)` includes both and the "output only"
  constraint.
- `command.transform` success / HTTP error (mocked) → returns text / raises.
- `snippet_match`: exact trigger (case/punct-insensitive) hits; non-match → None.
- `apply_spoken_formatting`: "new line"/"new paragraph" mapping; leaves normal text alone.
- command-mode `ChordMachine` reuses the existing (already-tested) state machine.

---

## Phase 4 — Tray controls + history search + stats + silence guard

### Tray controls
- Tray submenus (radio items, persist to config, re-init provider where needed):
  - **Provider ▸** openai / elevenlabs / groq → updates `cfg["provider"]`, saves,
    `app.provider = create_provider(cfg)`.
  - **Cleanup style ▸** light / balanced / heavy.
  - (Language and Cleanup toggle already exist.)
- New i18n keys for these labels (both languages; parity test stays green).

### History: Recent submenu + HTML viewer
- **Recent ▸** submenu: last 8 dictations (timestamp + ~40-char preview); clicking an
  item re-inserts it via `inject.insert_text`. Reads the tail of `history.jsonl`.
- **Open history** now writes a self-contained **`history.html`** (data embedded as JSON,
  a search box + list rendered by a tiny inline script; each row has a "Copy" button
  using `navigator.clipboard`) and opens it with `os.startfile`. Searchable; copy-to-
  clipboard (re-insert into arbitrary apps isn't possible from a browser, so copy +
  manual paste — the Recent submenu covers one-click re-insert).
- `history.tail(path, n)` and `history.render_html(entries) -> str` (pure, tested).

### Usage stats
- `history.stats(entries) -> dict` (pure): total dictations, total words (split on
  whitespace for latin; count CJK chars individually), total audio seconds, and an
  estimate of time saved = words / 40 wpm typing − audio time. Tray **Stats** shows a
  toast summary; the HTML viewer shows a stats header.

### Silence guard
- `recorder.Recorder` tracks `_peak` (max `compute_level` seen during the take).
- `Recorder.stop()` returns `None` not only when too short but also when
  `_peak < cfg silence_threshold` (new config `silence_threshold`, default `0.06`) →
  pipeline treats as no-speech (toast `err_empty`), skips the API call (no billing).
- `peak` resets each `start()`.

### Tests
- `history.tail` returns last n in order; handles missing/short file.
- `history.render_html` embeds entries and is valid-ish HTML (contains the search input
  id and the entries' text, HTML-escaped).
- `history.stats`: words (latin + CJK), totals, time-saved sign/magnitude on a sample.
- silence guard: `Recorder` with injected low peak → `stop()` returns None; high peak →
  returns wav. (Refactor `stop` to consult a `_peak` attribute settable in tests.)

---

---

## Phase 5 — Auto-learning dictionary (from user corrections)

### Goal
After dictated text is inserted, detect manual corrections the user makes to it and add
the corrected terms to `cleanup.dictionary`, so future transcription + cleanup spell them
right without manual upkeep.

### Feasibility (honest)
Reliable correction detection requires reading the focused control's text, which on
Windows means **UI Automation (UIA)**. UIA exposes editable text in many native and some
Electron/browser apps, but not all (terminals, some custom editors don't). So this
feature is **best-effort and opt-in (default off)** and **degrades gracefully**: if UIA
or the control text isn't available, it silently does nothing — no errors, no harm.

### Design
- New `app/uia.py`: `read_focused_text() -> str | None` reading the focused control's
  text value via UIA. Import-guarded (uses `comtypes`/`uiautomation`); if the library is
  missing or fails on this Python, the function returns `None` and the feature disables
  itself (logged once). Feasibility verified at build time; the app is unaffected if UIA
  is unavailable.
- New `app/learn.py` (pure core + thin glue):
  - After a successful paste, the pipeline records `pending = (inserted_text,
    snapshot_after, ts)` where `snapshot_after = uia.read_focused_text()`.
  - On the next dictation start (or a debounce idle timer), read the control again;
    `extract_corrections(inserted_text, snapshot_after, current_text)` finds token
    substitutions inside the inserted region.
  - A substitution `(old → new)` is learnable iff `_is_learnable(old, new, known)`:
    `new` length ≥ 3 and alphabetic-ish; Levenshtein ratio(old,new) ≥ `min_ratio`
    (a correction, not a different word); `new` not already in the dictionary; `new`
    not in a small common-word stoplist (bias toward names/jargon).
  - Accepted terms are appended to `cleanup.dictionary` (dedup, cap `max_terms`), config
    saved, optional toast "Learned: <term>".
- **Pure, tested core:** `extract_corrections(...)`, `_is_learnable(...)`,
  `_levenshtein_ratio(...)`. The UIA reads are the thin untested shim.
- Config `learn`: `{ "enabled": false, "min_ratio": 0.6, "max_terms": 200, "notify": true }`.

### Tests
- `_levenshtein_ratio`: identical → 1.0; disjoint → low; near-miss ~high.
- `_is_learnable`: "aditya"→"adithya" near-miss → True; "cat"→"dog" → False; common word
  → False; already-in-dict (passed set) → False; len < 3 → False.
- `extract_corrections`: inserted "call aditya now" / current "call Adithya now" →
  `["Adithya"]`; no change → `[]`; full unrelated rewrite → `[]` (ratios too low).

### Risks
| Risk | Mitigation |
|---|---|
| UIA unavailable in many apps | Best-effort + opt-in; silently no-ops when text can't be read. |
| Dictionary pollution (false positives) | Conservative gates (ratio, length, stoplist, dedup, cap); opt-in; user can edit config. |
| UIA lib incompatible with Python 3.14 | Import-guarded; feature disables, app unaffected. Verified at build time. |
| Reads slow/block | Reads run on the worker/learn thread, never the hook thread; short timeouts. |

## Cross-cutting

- **Config additions** (all with defaults; deep-merge already preserves nested user
  values): `command_hotkey`, `snippets`, `spoken_formatting`, `notify_on_insert`,
  `silence_threshold`, `cleanup.app_aware`, `cleanup.app_styles`, `learn`.
- **config.example.json** + **README** updated each phase.
- **i18n** new keys: `command`, `done_notify` (exists), `provider`, `cleanup_style`,
  `recent`, `stats`, `select_text_first`, provider/style sublabels — added to both tables.
- **Security note:** the live OpenAI + ElevenLabs keys are in plaintext `config.json`
  (gitignored) and were shared in chat; recommend rotating them.

## Risks
| Risk | Mitigation |
|---|---|
| tkinter multi-window from non-main thread crashes | Avoid entirely — history/stats via tray submenu + browser HTML, not new tk windows. |
| Command mode clobbers clipboard/selection | Save & restore clipboard around the Ctrl+C capture; only paste back on success. |
| App detection fails / odd titles | `foreground_app()` returns ("","") on any error → cleanup just omits the app line. |
| Snippet/formatting false positives | Snippets require an exact normalized match; spoken formatting only maps standalone tokens; both toggleable. |
| Second hotkey conflicts (Win+Alt) | Configurable; documented; reuses the tested chord machine. |
