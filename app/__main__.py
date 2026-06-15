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
from . import cleanup, history, inject, postprocess
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
        prompt = self._build_transcription_prompt(lang)
        text = self._transcribe_with_retry(wav, language, prompt)
        if text is None:
            return  # already notified
        text = self._maybe_cleanup(text, lang)
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
                api_key=config_mod.get_cleanup_api_key(self.cfg),
                base_url=cu.get("base_url", "https://api.openai.com/v1"),
                style=cu.get("style", "balanced"),
                dictionary=cu.get("dictionary", []),
                language=lang,
            )
        except cleanup.CleanupError as e:
            log.warning("cleanup failed, using raw transcript: %s", e)
            return text

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

    def toggle_cleanup(self):
        cu = self.cfg.setdefault("cleanup", {})
        cu["enabled"] = not cu.get("enabled", True)
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
