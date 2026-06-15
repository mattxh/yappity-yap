"""Beep cues and toast notifications (toast sink is injected by tray)."""
import logging
import threading

log = logging.getLogger(__name__)

_BEEPS = {"start": (880, 90), "stop": (660, 90), "cancel": (440, 130), "error": (330, 200)}


def beep(kind: str, enabled: bool = True):
    if not enabled:
        return

    def _play():
        try:
            import winsound

            freq, ms = _BEEPS.get(kind, (500, 100))
            winsound.Beep(freq, ms)
        except Exception:
            log.debug("beep failed", exc_info=True)

    threading.Thread(target=_play, daemon=True).start()


class Notifier:
    """Toast notifications; falls back to log if tray isn't up yet."""

    def __init__(self):
        self._sink = None  # set by tray: callable(message, title)

    def set_sink(self, sink):
        self._sink = sink

    def toast(self, message: str, title: str = "VoiceToText"):
        log.info("notify: %s", message)
        if self._sink is not None:
            try:
                self._sink(message, title)
            except Exception:
                log.debug("toast failed", exc_info=True)
