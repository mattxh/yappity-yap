"""Insert text into the focused app: clipboard + simulated Ctrl+V.

Pasting (not typing) is required for Chinese text (IME-safe). The user's clipboard
is preserved: we copy the text, paste, then restore whatever was there before, so
dictation/command output never clobbers the clipboard.
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


def insert_text(text: str, settle_ms: int = 150, restore_clipboard: bool = True,
                restore_delay_ms: int = 400):
    import keyboard
    import pyperclip

    prior = None
    if restore_clipboard:
        try:
            prior = pyperclip.paste()
        except Exception:
            prior = None
    pyperclip.copy(text)
    _wait_modifiers_released()
    time.sleep(settle_ms / 1000.0)
    try:
        keyboard.send("ctrl+v")
    except Exception:
        log.exception("paste failed (text remains on clipboard)")
        return
    if restore_clipboard and prior is not None:
        # let the target app consume the paste before we put the old clipboard back
        time.sleep(restore_delay_ms / 1000.0)
        try:
            pyperclip.copy(prior)
        except Exception:
            log.debug("clipboard restore failed", exc_info=True)


_NO_SELECTION = "\x00\x00__voicetotext_no_selection__\x00\x00"


def set_clipboard(text: str) -> bool:
    """Put text on the clipboard (used by the 'Copy' fallback). Returns success."""
    import pyperclip

    try:
        pyperclip.copy(text)
        return True
    except Exception:
        log.exception("clipboard copy failed")
        return False


def capture_selection(settle_ms: int = 130) -> str:
    """Copy the current selection and return it (for command mode), or '' if
    nothing is selected. Waits for the trigger modifiers to release first so we
    don't send Win+Ctrl+C. Run this OFF the hotkey hook thread — it may block
    briefly, and in hold-to-talk the modifiers stay down until the user releases.

    A sentinel is placed on the clipboard before Ctrl+C: if nothing is selected
    the copy is a no-op and the sentinel survives, which is how we tell 'no
    selection' apart from a stale clipboard. The user's clipboard is always restored
    afterwards, so reading the selection never clobbers it."""
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
    # Always restore the user's clipboard — reading the selection must not clobber it.
    try:
        pyperclip.copy(prev)
    except Exception:
        pass
    return "" if got == _NO_SELECTION else got
