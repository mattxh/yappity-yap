"""Yappity Yapp entry point: wiring, pipeline worker, CLI flags."""
import argparse
import ctypes
import logging
import logging.handlers
import os
import queue
import re
import socket
import sys
import threading
import time
from pathlib import Path

from . import appcontext, config as config_mod
from . import (cleanup, command, costs, dashboard, helppage, history, inject, learn,
               postprocess, prompt, textcmds, uia)
from .config import get_api_key
from .hotkey import ChordMachine, KeyboardHookAdapter, chord_mods, single_key
from .i18n import tr
from .notify import Notifier, beep
from .overlay import NullOverlay, Overlay
from .pipeline import JobGate
from .providers import create_provider
from .providers.base import TranscriptionError
from .recorder import MicError, Recorder, list_devices

log = logging.getLogger("app")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = config_mod.data_dir()   # source tree in dev; a per-user folder when frozen
LAST_RECORDING = DATA_DIR / "last_recording.wav"
CORRECTIONS_PATH = DATA_DIR / "corrections.json"
LOG_PATH = DATA_DIR / "app.log"
CRASH_PATH = DATA_DIR / "crash.log"   # faulthandler dumps native-crash stacks here
_crash_fp = None   # kept open for the process lifetime so faulthandler can write to it
SINGLE_INSTANCE_PORT = 50517
WAV_HEADER_BYTES = 44
BYTES_PER_SECOND = 32000  # 16 kHz * 2 bytes
WATCHDOG_INTERVAL_S = 1   # check often so a stranded chord clears before the next tap


def wav_duration(wav: bytes) -> float:
    return max(0.0, (len(wav) - WAV_HEADER_BYTES) / BYTES_PER_SECOND)


def _shorten(text: str, n: int = 42) -> str:
    """Collapse whitespace and trim to n chars for the overlay label."""
    text = " ".join((text or "").split())
    return text if len(text) <= n else text[:n - 1] + "…"


# Split the add-words dialog text into entries: one per line, comma, semicolon, or a
# CJK comma — but NOT on spaces, so multi-word terms like "git diff" stay intact.
_WORDS_SPLIT = re.compile(r"[,\n\r;，、]+")


def _parse_words(text: str) -> list:
    seen, out = set(), []
    for part in _WORDS_SPLIT.split(text or ""):
        word = part.strip()
        if word and word.lower() not in seen:
            seen.add(word.lower())
            out.append(word)
    return out


def _looks_like_term(text: str) -> bool:
    """A dictionary entry should be a short term (a name/word/phrase), not a sentence."""
    text = text.strip()
    return bool(text) and len(text) <= 40 and len(text.split()) <= 4 and \
        any(c.isalpha() for c in text)


def _set_dpi_awareness():
    """Make the process per-monitor DPI-aware so the overlay renders at native
    pixels instead of being bitmap-stretched (blurry) on scaled displays."""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PER_MONITOR_DPI_AWARE
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def _force_utf8_console():
    """Windows consoles on zh-TW default to cp950, which cannot encode many
    transcript characters (or even '®' in device names). Force UTF-8 so
    --check / --list-devices / --verbose never crash on output."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass


class App:
    def __init__(self, cfg: dict, cfg_path):
        self.cfg = cfg
        self.cfg_path = cfg_path
        self.provider = create_provider(cfg)
        self.recorder = Recorder(device=cfg.get("input_device"),
                                 silence_threshold=cfg.get("silence_threshold", 0.0))
        self.overlay = (Overlay(True, level_source=self.recorder.level)
                        if cfg.get("show_overlay", True) else NullOverlay())
        self.notifier = Notifier()
        hk = cfg.get("hotkey", "f9")
        sk = single_key(hk)
        dict_mods = (sk,) if sk else ("ctrl", "win")   # single key -> tap or hold on that key
        self.machine = ChordMachine(
            on_start=self._on_start, on_stop=self._on_stop, on_cancel=self._on_cancel,
            mods=dict_mods, tap_threshold_ms=cfg.get("tap_threshold_ms", 400),
        )
        self.adapter = KeyboardHookAdapter(self.machine)
        self.cmd_machine = None    # command-mode chord (built if the hotkey is a chord)
        self.cmd_adapter = None
        self.jobs: queue.Queue = queue.Queue()
        self.set_tray_state = lambda state: None  # replaced by tray.run_tray
        self.on_history_changed = lambda: None    # replaced by tray (refresh Recent)
        self._pending_learn = None   # (inserted_text, field_snapshot) for auto-learn
        self._just_learned = None    # terms promoted this run -> flagged after the pipeline
        self._gate = JobGate()   # serializes jobs + owns the auto-stop timer
        self._cmd_recording = False
        self._stopping = False
        threading.Thread(target=self._worker, daemon=True, name="pipeline").start()
        threading.Thread(target=self._watchdog, daemon=True, name="watchdog").start()

    def t(self, key, **fmt):
        return tr(key, self.cfg.get("ui_language", "en"), **fmt)

    # -- hotkey callbacks (keyboard hook thread) -----------------------------

    def _on_start(self):
        log.info("recording started")
        try:
            self.recorder.start()
        except MicError as e:
            beep("error", self.cfg["beeps"])
            self.notifier.toast(self.t("err_mic", error=str(e)))
            return
        beep("start", self.cfg["beeps"])
        self.overlay.show(self.t("recording"), "recording")
        self.set_tray_state("recording")
        self._gate.start_timer(self.cfg["max_recording_s"], self._auto_stop)

    def _on_stop(self):
        self._gate.cancel_timer()
        self._stop_and_enqueue()

    def _on_cancel(self):
        log.info("recording cancelled")
        self._gate.cancel_timer()
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
                self._gate.cancel_timer()
                self._stop_and_enqueue()
        elif self.machine.force_start():
            self._on_start()

    # -- command mode (voice-edit selected text) -----------------------------

    def start_command_chord(self, mods):
        """Give the command hotkey full hold/tap behavior via its own chord
        machine + hook (mirrors dictation), so 'hold Win+Alt, speak, release'
        works instead of only tap-to-start/tap-to-stop."""
        self.cmd_machine = ChordMachine(
            on_start=self._on_cmd_start, on_stop=self._cmd_chord_stop,
            on_cancel=self._cmd_chord_cancel, mods=mods,
            tap_threshold_ms=self.cfg.get("tap_threshold_ms", 400),
        )
        self.cmd_adapter = KeyboardHookAdapter(self.cmd_machine)
        self.cmd_adapter.start()

    def _bind_key_edges(self, key, machine, suppress):
        """Feed a single key's real press/release edges into a ChordMachine whose
        mods=(key,), giving tap-to-toggle AND press-and-hold on a plain key. Auto-repeat
        key-downs during a hold are harmless — the machine only acts on the release."""
        import keyboard

        keyboard.on_press_key(key, lambda e: machine.handle("down", key), suppress=suppress)
        keyboard.on_release_key(key, lambda e: machine.handle("up", key), suppress=suppress)

    def bind_dictation_key(self, key):
        """Dictation on a single key: tap to start/stop, or hold to push-to-talk."""
        self._bind_key_edges(key, self.machine, suppress=False)

    def start_command_key(self, key, suppress=True):
        """Command mode on a single key, with the same tap-or-hold behavior."""
        self.cmd_machine = ChordMachine(
            on_start=self._on_cmd_start, on_stop=self._cmd_chord_stop,
            on_cancel=self._cmd_chord_cancel, mods=(key,),
            tap_threshold_ms=self.cfg.get("tap_threshold_ms", 400),
        )
        self._bind_key_edges(key, self.cmd_machine, suppress=suppress)

    def command_toggle(self):
        """Custom (non-chord) hotkey: tap to start (capture selection + record
        instruction), tap again to stop and transform."""
        if self._cmd_recording:
            self._cmd_recording = False
            self._stop_and_transform()
        elif not self.machine.is_recording() and not self._gate.is_active():
            self._on_cmd_start()

    def _on_cmd_start(self):
        # Fired eagerly by the chord on chord-complete, so guard against starting
        # while dictation or another job is in flight (the recorder is shared).
        if self.machine.is_recording() or self._gate.is_active() or self._cmd_recording:
            return
        # NB: the selection is captured later, on the worker thread, AFTER the
        # user releases the chord — sending Ctrl+C here would block the hook
        # thread and (in hold-to-talk) fire while Win+Alt are still down.
        try:
            self.recorder.start()
        except MicError as e:
            beep("error", self.cfg["beeps"])
            self.notifier.toast(self.t("err_mic", error=str(e)))
            return
        self._cmd_recording = True
        beep("start", self.cfg["beeps"])
        self.overlay.show(self.t("command"), "command")
        self.set_tray_state("recording")
        self._gate.start_timer(self.cfg["max_recording_s"], self._cmd_auto_stop)

    def _cmd_chord_stop(self):
        """Chord released (hold) or toggled off (second tap)."""
        if self._cmd_recording:
            self._cmd_recording = False
            self._stop_and_transform()
        elif self.cmd_machine is not None:
            self.cmd_machine.pipeline_done()   # start was guarded out; free the chord

    def _cmd_chord_cancel(self):
        """Esc / other key while the command chord is held."""
        self._gate.cancel_timer()
        if self._cmd_recording:
            self._cmd_recording = False
            self.recorder.cancel()
            beep("cancel", self.cfg["beeps"])
        self._finish_ui()

    def _cmd_auto_stop(self):
        if self._cmd_recording:
            if self.cmd_machine is not None:
                self.cmd_machine.external_stop()   # release fires no second stop
            self._cmd_recording = False
            self._stop_and_transform()

    def _stop_and_transform(self):
        self._gate.cancel_timer()
        wav = self.recorder.stop()
        beep("stop", self.cfg["beeps"])
        if not wav or not self._gate.try_begin():
            self._finish_ui()
            if self.cmd_machine is not None:
                self.cmd_machine.pipeline_done()
            return
        self.overlay.show(self.t("cmd_working"), "transcribing")
        self.set_tray_state("transcribing")
        self.jobs.put(("command", wav))

    def _run_command(self, wav: bytes):
        # Capture the selection here (worker thread) — by now the user has released
        # the chord, so Ctrl+C isn't mangled by held modifiers. Fall back to a
        # keystroke-free UIA read if the clipboard copy comes back empty.
        selection = inject.capture_selection() or (uia.read_selected_text() or "")
        log.info("command: selection=%d chars", len(selection.strip()))
        if not selection.strip():
            beep("error", self.cfg["beeps"])
            self.notifier.toast(self.t("select_text_first"))
            return
        instruction = self._transcribe_with_retry(wav, None, None)
        if not instruction or not instruction.strip():
            if instruction is not None:
                self.notifier.toast(self.t("err_empty"))
            return
        log.info("command instruction: %r", instruction.strip()[:60])
        if textcmds.is_learn_command(instruction):
            self._learn_from_selection(selection)
            return
        # Now we know the instruction — say what it's doing instead of "transcribing".
        self.overlay.show(self.t("cmd_applying", cmd=_shorten(instruction)), "transcribing")
        cu = self.cfg.get("cleanup", {})
        try:
            result = command.transform(
                selection, instruction,
                model=cu.get("model", "gpt-4o-mini"),
                api_key=config_mod.get_cleanup_api_key(self.cfg),
                base_url=cu.get("base_url", "https://api.openai.com/v1"),
            )
        except command.CommandError as e:
            beep("error", self.cfg["beeps"])
            self.notifier.toast(self.t("err_api", error=str(e)))
            return
        result = postprocess.to_traditional(result)
        if not result.strip():
            return
        inject.insert_text(result, restore_clipboard=self.cfg.get("preserve_clipboard", True))
        if self.cfg.get("notify_on_insert"):
            self.notifier.toast(self.t("done_notify", chars=len(result)))
        dur = wav_duration(wav)
        history.append_entry(history.HISTORY_PATH, lang="cmd", duration_s=dur, text=result,
                             cost=self._estimate_cost(dur), model=self._transcription_model())
        self.on_history_changed()

    def _learn_from_selection(self, selection: str):
        """'add to dictionary' command: add the selected term to the dictionary."""
        corrected = (selection or "").strip()
        cu = self.cfg.setdefault("cleanup", {})
        auto = cu.setdefault("auto_learned", [])
        added = []
        if _looks_like_term(corrected):
            if config_mod.add_word(self.cfg, corrected):
                if corrected not in auto:
                    auto.append(corrected)
                added.append(corrected)
        log.info("add word from selection: added=%s", added)
        if added:
            config_mod.save_config(self.cfg, self.cfg_path)
            self._just_learned = added       # flagged after the pipeline (notice + undo)
        else:
            self.notifier.toast(self.t("add_select_term"))

    def _stop_and_enqueue(self):
        self._gate.cancel_timer()
        wav = self.recorder.stop()
        beep("stop", self.cfg["beeps"])
        if not wav or not self._gate.try_begin():
            self._finish_ui()
            self.machine.pipeline_done()
            return
        self.jobs.put(("transcribe", wav))   # queue first: never lose a dictation to a UI error
        self.overlay.show(self.t("transcribing"), "transcribing")
        self.set_tray_state("transcribing")

    # -- pipeline worker thread ----------------------------------------------

    def _worker(self):
        while True:
            job = self.jobs.get()
            kind = job[0]
            if kind == "quit":
                return
            try:
                if kind == "command":
                    self._run_command(job[1])
                else:
                    self._transcribe_and_insert(job[1])
            except Exception:
                log.exception("pipeline crashed")
                self.notifier.toast(self.t("err_api", error="internal error — see app.log"))
            finally:
                self._finish_ui()
                self.machine.pipeline_done()
                if self.cmd_machine is not None:
                    self.cmd_machine.pipeline_done()
                self._gate.end()
            if self._just_learned:                       # flag after the overlay clears
                terms, self._just_learned = self._just_learned, None
                self._flag_learned(terms)

    def _transcribe_and_insert(self, wav: bytes):
        self._consume_pending_learn()   # learn from edits made since the last paste
        try:
            LAST_RECORDING.write_bytes(wav)
        except OSError:
            log.warning("could not save last_recording.wav")
        lang = self.cfg.get("language", "auto")
        language = None if lang == "auto" else lang
        # NB: no transcription prompt. Passing the (Chinese) dictionary as the prompt
        # biased Whisper-derived models to transcribe English speech as Chinese. The
        # dictionary still applies during cleanup. Pinning language also stays honored.
        text = self._transcribe_with_retry(wav, language, None)
        if text is None:
            return  # already notified
        # Auto-detect sometimes mis-fires to Korean/Japanese/etc. The app is English +
        # Mandarin only, so re-transcribe pinned to English (pin a language in the tray
        # to avoid this entirely if you mostly speak one).
        if language is None and cleanup.contains_unsupported_script(text):
            log.warning("transcript not English/Chinese (%r); retrying pinned to English",
                        text[:40])
            retry = self._transcribe_with_retry(wav, "en", None)
            if retry and retry.strip():
                text = retry
        log.info("raw transcript (%d chars): %r", len(text), text[:300])
        snippet = textcmds.snippet_match(text, self.cfg.get("snippets", {}))
        fmt = (textcmds.apply_spoken_formatting(text)
               if self.cfg.get("spoken_formatting", True) else None)
        if snippet is not None:
            final = snippet
        elif fmt is not None:
            final = fmt
        else:
            final = postprocess.process(self._maybe_cleanup(text, lang),
                                        self.cfg.get("append_space", True))
            if not final.strip():
                self.notifier.toast(self.t("err_empty"))
                return
        editable = uia.focused_is_text_input()
        log.info("final text (%d chars): %r | editable=%s", len(final), final[:300], editable)
        if editable is False:
            # Cursor is clearly on a non-text control (a button, menu, …) — Ctrl+V would
            # go nowhere. Offer the transcript so the user can copy it instead.
            self._offer_transcript(final)
        else:
            inject.insert_text(final, restore_clipboard=self.cfg.get("preserve_clipboard", True))
            if self.cfg.get("notify_on_insert"):
                self.notifier.toast(self.t("done_notify", chars=len(final)))
            self._set_pending_learn(final)
        dur = wav_duration(wav)
        history.append_entry(history.HISTORY_PATH, lang=lang, duration_s=dur, text=final,
                             cost=self._estimate_cost(dur), model=self._transcription_model())
        self.on_history_changed()

    def _offer_transcript(self, text: str):
        """Show the transcript with a Copy button (and ✕) when it couldn't be pasted.
        The clipboard is left untouched unless the user clicks Copy."""
        if self.cfg.get("show_overlay", True):
            self.overlay.transcript(_shorten(text, 48), self.t("copy"),
                                    lambda: inject.set_clipboard(text))
        else:
            inject.set_clipboard(text)
            self.notifier.toast(self.t("paste_failed_copied"))

    # -- auto-learning dictionary (UIA reads stay on this worker thread) -------

    def _set_pending_learn(self, inserted: str):
        lc = self.cfg.get("learn", {})
        if not lc.get("enabled"):
            self._pending_learn = None
            return
        snapshot = uia.read_focused_text()
        self._pending_learn = (inserted, snapshot) if snapshot else None

    def _consume_pending_learn(self):
        pending, self._pending_learn = self._pending_learn, None
        lc = self.cfg.get("learn", {})
        if not pending or not lc.get("enabled"):
            return
        current = uia.read_focused_text()
        if not current:
            return
        inserted, snapshot = pending
        cu = self.cfg.setdefault("cleanup", {})
        dic = cu.setdefault("dictionary", [])
        pairs = learn.extract_corrections(inserted, snapshot, current, known=set(dic),
                                          min_ratio=lc.get("min_ratio", 0.6))
        if not pairs:
            return
        # Count each rewrite; only promote a word once it's been rewritten enough times.
        store = learn.load_corrections(CORRECTIONS_PATH)
        learn.bump_corrections(store, pairs)
        promoted = learn.due_for_promotion(store, lc.get("promote_after", 2))
        learn.save_corrections(store, CORRECTIONS_PATH)
        if not promoted:
            return
        auto = cu.setdefault("auto_learned", [])
        for term in promoted:
            if term not in dic:
                dic.append(term)
            if term not in auto:
                auto.append(term)
        max_terms = lc.get("max_terms", 200)
        if len(dic) > max_terms:
            del dic[:len(dic) - max_terms]
        config_mod.save_config(self.cfg, self.cfg_path)
        log.info("promoted to dictionary after repeated rewrites: %s", promoted)
        if lc.get("notify", True):
            self._just_learned = promoted   # flagged after the pipeline (notice + undo)

    def _flag_learned(self, terms):
        text = self.t("learned_notice", terms=", ".join(terms))
        if self.cfg.get("show_overlay", True):
            self.overlay.notice(text, self.t("undo"), lambda: self._undo_learned(terms))
        else:
            self.notifier.toast(text)

    def _undo_learned(self, terms):
        changed = any(config_mod.remove_word(self.cfg, t) for t in terms)
        if changed:
            config_mod.save_config(self.cfg, self.cfg_path)
            self.notifier.toast(self.t("learned_undone", terms=", ".join(terms)))

    def _attempt(self, provider, wav, language, prompt, retries):
        """Try one provider up to retries+1 times. Returns (text, None) on success or
        (None, error) on failure."""
        err = None
        for i in range(retries + 1):
            try:
                return provider.transcribe(wav, language, prompt), None
            except TranscriptionError as e:
                err = e
                if e.retryable and i < retries:
                    log.warning("transcription failed, retrying: %s", e)
                    time.sleep(2)
                    continue
                break
        return None, err

    def _fallback_provider(self):
        """A working alternative when the chosen provider is unreachable: OpenAI, if it
        isn't already the provider and its key is set. It reaches most networks and
        handles English + Mandarin well."""
        if self.cfg.get("provider") == "openai" or not get_api_key(self.cfg, "openai"):
            return None
        try:
            fb_cfg = dict(self.cfg)
            fb_cfg["provider"] = "openai"
            return create_provider(fb_cfg)
        except Exception:
            log.debug("could not build fallback provider", exc_info=True)
            return None

    def _friendly_error(self, err) -> str:
        s = str(err or "")
        low = s.lower()
        if any(k in low for k in ("getaddrinfo", "failed to resolve", "max retries",
                                  "nameresolution", "connection", "timed out", "timeout")):
            return self.t("err_offline")
        return s[:160]

    def _transcribe_with_retry(self, wav, language, prompt):
        fb = self._fallback_provider()
        # Don't burn the 2s retry on a dead host when a fallback is ready.
        text, err = self._attempt(self.provider, wav, language, prompt,
                                  retries=0 if fb is not None else 1)
        if text is not None:
            return text
        if fb is not None:
            log.warning("primary provider failed (%s); trying OpenAI fallback", err)
            ftext, ferr = self._attempt(fb, wav, language, prompt, retries=0)
            if ftext is not None:
                self.notifier.toast(self.t("provider_fallback"))
                return ftext
            err = ferr or err
        log.error("transcription failed: %s", err)
        beep("error", self.cfg["beeps"])
        self.notifier.toast(self.t("err_api", error=self._friendly_error(err)))
        return None

    def _transcription_model(self) -> str:
        provider = self.cfg.get("provider", "openai")
        return self.cfg.get("providers", {}).get(provider, {}).get("model", "")

    def _estimate_cost(self, duration_s: float) -> float:
        return costs.estimate_cost(duration_s, self._transcription_model(),
                                   self.cfg.get("cleanup", {}).get("enabled", True))

    def _maybe_cleanup(self, text, lang):
        cu = self.cfg.get("cleanup", {})
        if not cu.get("enabled") or not text.strip():
            return text
        app_hint, app_style = "", ""
        if cu.get("app_aware", True):
            proc, title = appcontext.foreground_app()
            if proc or title:
                app_hint = f"{proc} {title}".strip()
                styles = list(cu.get("app_styles", [])) + appcontext.DEFAULT_APP_STYLES
                app_style = appcontext.match_style(styles, proc, title)
        try:
            cleaned = cleanup.clean(
                text,
                model=cu.get("model", "gpt-4o-mini"),
                api_key=config_mod.get_cleanup_api_key(self.cfg),
                base_url=cu.get("base_url", "https://api.openai.com/v1"),
                style=cu.get("style", "balanced"),
                dictionary=cu.get("dictionary", []),
                language=lang,
                app_hint=app_hint,
                app_style=app_style,
            )
        except cleanup.CleanupError as e:
            log.warning("cleanup failed, using raw transcript: %s", e)
            return text
        if not cleaned.strip():
            return text
        if not cleanup.preserves_language(text, cleaned):
            log.warning("cleanup changed the language; keeping the raw transcript")
            return text
        if cleanup.added_content(text, cleaned):
            log.warning("cleanup added/continued content; keeping the raw transcript")
            return text
        if cleanup.answered_instead_of_cleaned(text, cleaned, cu.get("style", "balanced")):
            log.warning("cleanup answered instead of cleaning; keeping the raw transcript")
            return text
        if cleanup.contains_unsupported_script(cleaned) \
                and not cleanup.contains_unsupported_script(text):
            log.warning("cleanup produced a non-English/Chinese script; keeping raw")
            return text
        log.info("cleanup: %d -> %d chars", len(text), len(cleaned))
        return cleaned

    # -- tray actions (tray thread) --------------------------------------------

    def retry_last(self):
        if self.machine.is_recording() or not LAST_RECORDING.exists():
            self.notifier.toast(self.t("retry_none"))
            return
        if not self._gate.try_begin():
            return  # a job is already running
        wav = LAST_RECORDING.read_bytes()
        self.overlay.show(self.t("transcribing"), "transcribing")
        self.set_tray_state("transcribing")
        self.jobs.put(("transcribe", wav))

    def open_history(self):
        entries = history.read_entries(history.HISTORY_PATH)
        out = history.HISTORY_PATH.with_suffix(".html")
        try:
            out.write_text(history.render_html(entries), encoding="utf-8")
            os.startfile(out)
        except OSError:
            log.exception("could not open history")

    def open_dashboard(self):
        entries = history.read_entries(history.HISTORY_PATH)
        cu = self.cfg.get("cleanup", {})
        corrections = learn.load_corrections(CORRECTIONS_PATH)
        html = dashboard.render_dashboard(
            entries, cu.get("dictionary", []), cu.get("auto_learned", []), corrections,
            promote_after=self.cfg.get("learn", {}).get("promote_after", 2))
        out = history.HISTORY_PATH.with_name("dashboard.html")
        try:
            out.write_text(html, encoding="utf-8")
            os.startfile(out)
        except OSError:
            log.exception("could not open dashboard")

    def recent_entries(self, n: int = 8):
        return history.tail(history.HISTORY_PATH, n)

    def copy_recent(self, text: str):
        """Tray 'Recent' click: copy the past dictation to the clipboard."""
        if inject.set_clipboard(text):
            self.notifier.toast(self.t("copied_to_clipboard"))

    def show_stats(self):
        s = history.stats(history.read_entries(history.HISTORY_PATH))
        self.notifier.toast(self.t("stats_summary", n=s["dictations"],
                                   words=s["words"], saved=s["time_saved_min"]))

    def set_provider(self, name: str):
        self.cfg["provider"] = name
        config_mod.save_config(self.cfg, self.cfg_path)
        try:
            self.provider = create_provider(self.cfg)
        except Exception as e:
            log.exception("provider switch failed")
            self.notifier.toast(str(e))

    def set_cleanup_style(self, style: str):
        self.cfg.setdefault("cleanup", {})["style"] = style
        config_mod.save_config(self.cfg, self.cfg_path)

    def _add_words_and_report(self, words):
        """Add a parsed list of words to the dictionary and toast a summary."""
        added, skipped = config_mod.add_words(self.cfg, words)
        if added:
            config_mod.save_config(self.cfg, self.cfg_path)
        if added and skipped:
            self.notifier.toast(self.t("words_added_some", n=len(added), dup=len(skipped)))
        elif added:
            self.notifier.toast(self.t("words_added", n=len(added)))
        else:
            self.notifier.toast(self.t("words_none_new"))

    def add_words(self):
        """Tray 'Add words…': prompt for one or more words and add them live."""
        text = prompt.ask_words(self.t("add_words"), self.t("add_words_hint"),
                                ok_label=self.t("btn_add"),
                                cancel_label=self.t("btn_cancel"), title="Yappity Yapp")
        words = _parse_words(text)
        if words:
            self._add_words_and_report(words)

    def import_words(self):
        """Tray 'Import words from file…': bulk-add from a .txt (one per line or comma-
        separated)."""
        path = prompt.ask_open_file(self.t("import_words"), title="Yappity Yapp")
        if not path:
            return
        try:
            text = Path(path).read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            self.notifier.toast(self.t("import_failed", error=str(e)))
            return
        self._add_words_and_report(_parse_words(text))

    def remove_word(self, word: str):
        if config_mod.remove_word(self.cfg, word):
            config_mod.save_config(self.cfg, self.cfg_path)
            self.notifier.toast(self.t("word_removed", word=word))

    def dictionary_words(self):
        cu = self.cfg.get("cleanup", {})
        auto = {w.lower() for w in cu.get("auto_learned", [])}
        return [(w, w.lower() in auto) for w in cu.get("dictionary", [])]

    def open_help(self):
        html = helppage.render_help(self.cfg.get("hotkey", "ctrl+windows"),
                                    self.cfg.get("command_hotkey", "alt+windows"))
        out = history.HISTORY_PATH.with_name("help.html")
        try:
            out.write_text(html, encoding="utf-8")
            os.startfile(out)
        except OSError:
            log.exception("could not open help")

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

    def toggle_cleanup(self):
        cu = self.cfg.setdefault("cleanup", {})
        cu["enabled"] = not cu.get("enabled", True)
        config_mod.save_config(self.cfg, self.cfg_path)

    def shutdown(self):
        self._stopping = True
        for adapter in (self.adapter, self.cmd_adapter):
            if adapter is not None:
                try:
                    adapter.stop()
                except Exception:
                    log.debug("unhook failed", exc_info=True)
        self._gate.cancel_timer()
        self.recorder.cancel()
        self.jobs.put(("quit",))
        self.overlay.close()

    # -- helpers ----------------------------------------------------------------

    def _finish_ui(self):
        self.overlay.hide()
        self.set_tray_state("idle")

    def _mods_physically_up(self) -> bool:
        """True if Ctrl, Alt and both Win keys are physically released right now. Used to
        tell a genuinely-stranded chord (missed key-up) from one mid-press."""
        try:
            gk = ctypes.windll.user32.GetAsyncKeyState
            for vk in (0x11, 0x12, 0x5B, 0x5C):   # Ctrl, Alt, LWin, RWin
                if gk(vk) & 0x8000:
                    return False
            return True
        except Exception:
            return False

    def _watchdog(self):
        """Recover a chord machine that got stranded in a non-idle state when the global
        hook dropped a key event (common when Win+Ctrl collides with a Windows shortcut).
        A stranded machine swallows the next tap, so clear it fast: immediately if the
        modifier keys are physically up, else after it persists two checks."""
        stuck = {}
        while not self._stopping:
            time.sleep(WATCHDOG_INTERVAL_S)
            try:
                idle = (not self.recorder.is_active()
                        and not self._gate.is_active()
                        and not self._cmd_recording)
                keys_up = self._mods_physically_up()
                for name, m in (("dictation", self.machine),
                                ("command", self.cmd_machine)):
                    if m is None:
                        continue
                    wedged = idle and not m.is_idle()
                    if wedged and (keys_up or m.state == stuck.get(name)):
                        log.warning("hotkey watchdog: recovering stuck %s state %r "
                                    "(keys_up=%s)", name, m.state, keys_up)
                        m.reset()
                        self._finish_ui()
                        stuck[name] = None
                    else:
                        stuck[name] = m.state if wedged else None
            except Exception:
                log.debug("watchdog error", exc_info=True)


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
    try:
        text = provider.transcribe(wav, None, None)
    except TranscriptionError as e:
        print(f"ERROR: transcription failed: {e}")
        return 1
    print("Transcript:", postprocess.process(text, cfg.get("append_space", True)))
    return 0


def _ensure_api_key(cfg) -> bool:
    """First-run setup: if no transcription/cleanup key is configured, ask for an OpenAI
    key in a friendly dialog and save it. Returns False only if the user declined (so the
    app should exit). ElevenLabs/Groq keys stay optional — OpenAI alone runs everything."""
    if get_api_key(cfg, cfg.get("provider", "openai")) or config_mod.get_cleanup_api_key(cfg):
        return True
    entered = prompt.ask_words(
        "Welcome to Yappity Yapp",
        "Paste your OpenAI API key to get started — it's saved only on this PC. "
        "Get one at platform.openai.com/api-keys. (ElevenLabs is optional.)",
        ok_label="Save", cancel_label="Quit", title="Yappity Yapp setup")
    key = entered.split()[0] if entered and entered.split() else ""
    if not key:
        ctypes.windll.user32.MessageBoxW(
            0, "No API key entered. Re-open Yappity Yapp when you have your OpenAI key.",
            "Yappity Yapp", 0x40)
        return False
    cfg.setdefault("providers", {}).setdefault("openai", {})["api_key"] = key
    config_mod.save_config(cfg, config_mod.CONFIG_PATH)
    return True


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="voicetotext")
    parser.add_argument("--check", action="store_true", help="2s mic + API end-to-end test")
    parser.add_argument("--list-devices", action="store_true", help="list audio input devices")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)

    _force_utf8_console()

    handlers = [logging.handlers.RotatingFileHandler(
        LOG_PATH, maxBytes=1_000_000, backupCount=3, encoding="utf-8")]
    if args.verbose or args.check or args.list_devices:
        handlers.append(logging.StreamHandler())
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s", handlers=handlers)
    # Keep third-party debug spam out of app.log (README points users here).
    for noisy in ("PIL", "comtypes"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    # Catch NATIVE crashes (access violations in PortAudio / UI Automation / tray),
    # which bypass Python's exception machinery entirely. faulthandler installs a
    # Windows fatal-exception handler that dumps every thread's Python stack, so the
    # next hard crash names the code that was running. Keep the file open process-wide.
    try:
        import faulthandler

        global _crash_fp
        _crash_fp = open(CRASH_PATH, "a", buffering=1, encoding="utf-8")
        faulthandler.enable(file=_crash_fp, all_threads=True)
    except Exception:
        log.warning("could not enable faulthandler", exc_info=True)

    # This is a windowed (pythonw) app with no console, so an uncaught exception on
    # any thread would vanish silently and look like a random crash. Route them to
    # app.log instead so the next crash is diagnosable.
    def _log_uncaught(exc_type, exc, tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc, tb)
            return
        log.critical("uncaught exception", exc_info=(exc_type, exc, tb))

    sys.excepthook = _log_uncaught
    threading.excepthook = lambda a: _log_uncaught(
        a.exc_type, a.exc_value, a.exc_traceback)

    if args.list_devices:
        print(list_devices())
        return 0

    cfg = config_mod.load_config()

    if args.check:
        return run_check(cfg)

    lock = acquire_single_instance()
    if lock is None:
        ctypes.windll.user32.MessageBoxW(
            0, tr("already_running", cfg.get("ui_language", "en")), "Yappity Yapp", 0x40)
        return 0

    if not _ensure_api_key(cfg):
        return 0   # no key entered at first-run setup; nothing to do

    _set_dpi_awareness()  # before any GUI window (overlay thread starts in App)
    app = App(cfg, config_mod.CONFIG_PATH)

    hotkey_cfg = cfg.get("hotkey", "f9")
    if hotkey_cfg == "ctrl+windows":
        app.adapter.start()
    elif single_key(hotkey_cfg):
        app.bind_dictation_key(hotkey_cfg)     # single key: tap to toggle, or hold to talk
        log.info("dictation hotkey %r (tap or hold)", hotkey_cfg)
    else:
        import keyboard

        keyboard.add_hotkey(hotkey_cfg, app.toggle_simple)   # combo: tap-toggle only
        log.info("dictation hotkey %r (toggle mode)", hotkey_cfg)

    cmd_hotkey = cfg.get("command_hotkey", "f10")
    if cmd_hotkey:
        cmd_mods = chord_mods(cmd_hotkey)
        try:
            if cmd_mods:
                app.start_command_chord(cmd_mods)  # full hold/tap, like dictation
                log.info("command hotkey %r (chord: hold or tap)", cmd_hotkey)
            elif single_key(cmd_hotkey):
                # Suppress so a bare F10 can't open the app menu bar on each toggle.
                app.start_command_key(cmd_hotkey, suppress=True)
                log.info("command hotkey %r (tap or hold)", cmd_hotkey)
            else:
                import keyboard

                keyboard.add_hotkey(cmd_hotkey, app.command_toggle, suppress=True)
                log.info("command hotkey %r (toggle mode)", cmd_hotkey)
        except Exception:
            log.warning("could not register command hotkey %r", cmd_hotkey, exc_info=True)

    hotkey_label = hotkey_cfg.upper() if single_key(hotkey_cfg) else hotkey_cfg

    def on_ready():
        # Confirm to the user that the app started (it lives only in the tray otherwise).
        app.notifier.toast(app.t("running", hotkey=hotkey_label))
        if not get_api_key(cfg, cfg["provider"]):
            app.notifier.toast(app.t("err_no_key"))

    from .tray import run_tray

    run_tray(app, on_ready=on_ready)  # blocks until Quit
    return 0


if __name__ == "__main__":
    sys.exit(main())
