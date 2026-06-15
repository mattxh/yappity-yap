"""Insert text into the focused app: clipboard + simulated Ctrl+V.

Clipboard is intentionally NOT restored — the transcript stays as backup.
Pasting (not typing) is required for Chinese text (IME-safe).
"""
import logging
import time

log = logging.getLogger(__name__)

MODIFIER_KEYS = ("ctrl", "left windows", "right windows")


def _wait_modifiers_released(timeout_s: float = 1.0):
    """If the user still physically holds Ctrl/Win from the chord, Ctrl+V
    would become Win+Ctrl+V. Wait briefly for release."""
    import keyboard

    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            if not any(keyboard.is_pressed(k) for k in MODIFIER_KEYS):
                return
        except Exception:
            return
        time.sleep(0.02)


def insert_text(text: str, settle_ms: int = 150):
    import keyboard
    import pyperclip

    pyperclip.copy(text)
    _wait_modifiers_released()
    time.sleep(settle_ms / 1000.0)
    try:
        keyboard.send("ctrl+v")
    except Exception:
        log.exception("paste failed (text remains on clipboard)")
