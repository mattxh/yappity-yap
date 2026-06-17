"""Insert text into the focused app: clipboard + simulated Ctrl+V.

Clipboard is intentionally NOT restored — the transcript stays as backup.
Pasting (not typing) is required for Chinese text (IME-safe).
"""
import logging
import time

log = logging.getLogger(__name__)

MODIFIER_KEYS = ("ctrl", "alt", "left windows", "right windows")


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


_NO_SELECTION = "\x00\x00__voicetotext_no_selection__\x00\x00"


def capture_selection(settle_ms: int = 130) -> str:
    """Copy the current selection and return it (for command mode), or '' if
    nothing is selected. Waits for the trigger modifiers to release first so we
    don't send Win+Ctrl+C. Run this OFF the hotkey hook thread — it may block
    briefly, and in hold-to-talk the modifiers stay down until the user releases.

    A sentinel is placed on the clipboard before Ctrl+C: if nothing is selected
    the copy is a no-op and the sentinel survives, which is how we tell 'no
    selection' apart from a stale clipboard. The clipboard is restored in that
    case so we never leave the sentinel behind."""
    import keyboard
    import pyperclip

    _wait_modifiers_released()
    try:
        prev = pyperclip.paste() or ""
    except Exception:
        prev = ""
    try:
        pyperclip.copy(_NO_SELECTION)
    except Exception:
        pass
    try:
        keyboard.send("ctrl+c")
    except Exception:
        log.exception("copy failed")
        return ""
    time.sleep(settle_ms / 1000.0)
    try:
        got = pyperclip.paste() or ""
    except Exception:
        got = ""
    if got == _NO_SELECTION:          # Ctrl+C copied nothing -> no selection
        try:
            pyperclip.copy(prev)      # restore; don't leave the sentinel behind
        except Exception:
            pass
        return ""
    return got
