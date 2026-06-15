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

from . import appcontext, config as config_mod
from . import cleanup, command, history, inject, learn, postprocess, textcmds, uia
from .config import get_api_key
from .hotkey import ChordMachine, KeyboardHookAdapter
from .i18n import tr
from .notify import Notifier, beep
from .overlay import NullOverlay, Overlay
from .pipeline import JobGate
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
        self.machine = ChordMachine(
            on_start=self._on_start, on_stop=self._on_stop, on_cancel=self._on_cancel,
            tap_threshold_ms=cfg.get("tap_threshold_ms", 400),
        )
        self.adapter = KeyboardHookAdapter(self.machine)
        self.jobs: queue.Queue = queue.Queue()
        self.set_tray_state = lambda state: None  # replaced by tray.run_tray
        self.on_history_changed = lambda: None    # replaced by tray (refresh Recent)
        self._pending_learn = None   # (inserted_text, field_snapshot) for auto-learn
        self._gate = JobGate()   # serializes jobs + owns the auto-stop timer
        self._cmd_recording = False
        self._cmd_selection = ""
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
        self._gate.start_timer(self.cfg["max_recording_s"], self._auto_stop)

    def _on_stop(self):
        self._gate.cancel_timer()
        self._stop_and_enqueue()

    def _on_cancel(self):
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

    def command_toggle(self):
        """Custom hotkey: tap to start (capture selection + record instruction),
        tap again to stop and transform."""
        if self._cmd_recording:
            self._cmd_recording = False
            self._stop_and_transform()
        elif not self.machine.is_recording() and not self._gate.is_active():
            self._on_cmd_start()

    def _on_cmd_start(self):
        selection = inject.capture_selection()
        if not selection.strip():
            beep("error", self.cfg["beeps"])
            self.notifier.toast(self.t("select_text_first"))
            return
        try:
            self.recorder.start()
        except MicError as e:
            beep("error", self.cfg["beeps"])
            self.notifier.toast(self.t("err_mic", error=str(e)))
            return
        self._cmd_selection = selection
        self._cmd_recording = True
        beep("start", self.cfg["beeps"])
        self.overlay.show(self.t("command"), "command")
        self.set_tray_state("recording")
        self._gate.start_timer(self.cfg["max_recording_s"], self._cmd_auto_stop)

    def _cmd_auto_stop(self):
        if self._cmd_recording:
            self._cmd_recording = False
            self._stop_and_transform()

    def _stop_and_transform(self):
        self._gate.cancel_timer()
        wav = self.recorder.stop()
        beep("stop", self.cfg["beeps"])
        if not wav or not self._gate.try_begin():
            self._finish_ui()
            return
        self.overlay.show(self.t("transcribing"), "transcribing")
        self.set_tray_state("transcribing")
        self.jobs.put(("command", wav, self._cmd_selection))

    def _run_command(self, wav: bytes, selection: str):
        instruction = self._transcribe_with_retry(wav, None, None)
        if not instruction or not instruction.strip():
            if instruction is not None:
                self.notifier.toast(self.t("err_empty"))
            return
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
        inject.insert_text(result)
        if self.cfg.get("notify_on_insert"):
            self.notifier.toast(self.t("done_notify", chars=len(result)))
        history.append_entry(history.HISTORY_PATH, lang="cmd",
                             duration_s=wav_duration(wav), text=result)
        self.on_history_changed()

    def _stop_and_enqueue(self):
        self._gate.cancel_timer()
        wav = self.recorder.stop()
        beep("stop", self.cfg["beeps"])
        if not wav or not self._gate.try_begin():
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
            kind = job[0]
            if kind == "quit":
                return
            try:
                if kind == "command":
                    self._run_command(job[1], job[2])
                else:
                    self._transcribe_and_insert(job[1])
            except Exception:
                log.exception("pipeline crashed")
                self.notifier.toast(self.t("err_api", error="internal error — see app.log"))
            finally:
                self._finish_ui()
                self.machine.pipeline_done()
                self._gate.end()

    def _transcribe_and_insert(self, wav: bytes):
        self._consume_pending_learn()   # learn from edits made since the last paste
        try:
            LAST_RECORDING.write_bytes(wav)
        except OSError:
            log.warning("could not save last_recording.wav")
        lang = self.cfg.get("language", "auto")
        language = None if lang == "auto" else lang
        prompt = self._build_transcription_prompt(lang)
        text = self._transcribe_with_retry(wav, language, prompt)
        if text is None:
            return  # already notified
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
        inject.insert_text(final)
        if self.cfg.get("notify_on_insert"):
            self.notifier.toast(self.t("done_notify", chars=len(final)))
        history.append_entry(history.HISTORY_PATH, lang=lang,
                             duration_s=wav_duration(wav), text=final)
        self.on_history_changed()
        self._set_pending_learn(final)

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
        dic = self.cfg.setdefault("cleanup", {}).setdefault("dictionary", [])
        terms = learn.extract_corrections(inserted, snapshot, current,
                                          known=set(dic),
                                          min_ratio=lc.get("min_ratio", 0.6))
        if not terms:
            return
        for term in terms:
            if term not in dic:
                dic.append(term)
        max_terms = lc.get("max_terms", 200)
        if len(dic) > max_terms:
            del dic[:len(dic) - max_terms]
        config_mod.save_config(self.cfg, self.cfg_path)
        log.info("auto-learned dictionary terms: %s", terms)
        if lc.get("notify", True):
            self.notifier.toast(self.t("learned", terms=", ".join(terms)))

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
        app_hint, app_style = "", ""
        if cu.get("app_aware", True):
            proc, title = appcontext.foreground_app()
            if proc or title:
                app_hint = f"{proc} {title}".strip()
                styles = list(cu.get("app_styles", [])) + appcontext.DEFAULT_APP_STYLES
                app_style = appcontext.match_style(styles, proc, title)
        try:
            return cleanup.clean(
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

    def recent_entries(self, n: int = 8):
        return history.tail(history.HISTORY_PATH, n)

    def reinsert(self, text: str):
        inject.insert_text(text)

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
        try:
            self.adapter.stop()
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

    _set_dpi_awareness()  # before any GUI window (overlay thread starts in App)
    app = App(cfg, config_mod.CONFIG_PATH)

    hotkey_cfg = cfg.get("hotkey", "ctrl+windows")
    if hotkey_cfg == "ctrl+windows":
        app.adapter.start()
    else:
        import keyboard

        keyboard.add_hotkey(hotkey_cfg, app.toggle_simple)
        log.info("custom hotkey %r (toggle mode)", hotkey_cfg)

    cmd_hotkey = cfg.get("command_hotkey", "alt+windows")
    if cmd_hotkey:
        try:
            import keyboard

            keyboard.add_hotkey(cmd_hotkey, app.command_toggle)
            log.info("command hotkey %r", cmd_hotkey)
        except Exception:
            log.warning("could not register command hotkey %r", cmd_hotkey, exc_info=True)

    on_ready = None
    if not get_api_key(cfg, cfg["provider"]):
        on_ready = lambda: app.notifier.toast(app.t("err_no_key"))

    from .tray import run_tray

    run_tray(app, on_ready=on_ready)  # blocks until Quit
    return 0


if __name__ == "__main__":
    sys.exit(main())
