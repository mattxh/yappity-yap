"""Insert text into the focused app: clipboard + simulated Ctrl+V.

Pasting (not typing) is required for Chinese text (IME-safe).

Optional clipboard preservation (restore_clipboard): the previous clipboard is put back
AFTER the paste is observed to have landed in the focused field (so the app has already
read our text), or after a timeout for apps that don't expose their text. Restoring on a
fixed timer instead raced with the paste and could paste the OLD clipboard, so we confirm
first. The wait runs on a daemon thread so it never blocks the pipeline.
"""
import logging
import threading
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


def _restore_clipboard_when_pasted(prior, baseline, read_focused, set_clip,
                                   timeout_ms=2500, poll_ms=60,
                                   clock=time.monotonic, sleep=time.sleep):
    """Put `prior` back on the clipboard once the paste is seen to have landed (the
    focused field changed from `baseline`), or after `timeout_ms` as a fallback. Waiting
    for the change means the app has already read our text, so the restore can't race."""
    deadline = clock() + timeout_ms / 1000.0
    while clock() < deadline:
        sleep(poll_ms / 1000.0)
        try:
            cur = read_focused()
        except Exception:
            cur = None
        if cur is not None and cur != baseline:
            break   # paste landed -> the app has consumed our clipboard text
    try:
        set_clip(prior)
    except Exception:
        log.debug("clipboard restore failed", exc_info=True)


def insert_text(text: str, settle_ms: int = 150, restore_clipboard: bool = False):
    """Paste text into the focused app via the clipboard + Ctrl+V (IME-safe).

    With restore_clipboard, the previous clipboard is restored after the paste is
    confirmed (see _restore_clipboard_when_pasted); otherwise the pasted text is left
    on the clipboard."""
    import keyboard
    import pyperclip
    from . import uia

    prior = baseline = None
    if restore_clipboard:
        try:
            prior = pyperclip.paste()
        except Exception:
            prior = None
        try:
            baseline = uia.read_focused_text()
        except Exception:
            baseline = None
    pyperclip.copy(text)
    _wait_modifiers_released()
    time.sleep(settle_ms / 1000.0)
    try:
        keyboard.send("ctrl+v")
    except Exception:
        log.exception("paste failed (text remains on clipboard)")
        return
    if restore_clipboard and prior is not None and prior != text:
        threading.Thread(
            target=_restore_clipboard_when_pasted,
            args=(prior, baseline, uia.read_focused_text, set_clipboard),
            daemon=True, name="clip-restore").start()


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
    # Poll the clipboard rather than waiting a single fixed delay: some apps update
    # it slowly, so a one-shot read often saw the sentinel and reported 'no selection'.
    got = _NO_SELECTION
    deadline = time.monotonic() + max(settle_ms, 700) / 1000.0
    while time.monotonic() < deadline:
        time.sleep(0.04)
        try:
            got = pyperclip.paste() or ""
        except Exception:
            got = ""
        if got != _NO_SELECTION:
            break
    # Always restore the user's clipboard — reading the selection must not clobber it.
    try:
        pyperclip.copy(prev)
    except Exception:
        pass
    return "" if got == _NO_SELECTION else got
