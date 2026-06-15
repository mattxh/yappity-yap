"""Detect the foreground app and map it to a cleanup style.

`foreground_app()` reads the focused window's process name + title via Win32
(ctypes, no extra deps); failures degrade to ("", ""). `match_style` is pure and
maps an app to a tone/formatting instruction for the cleanup pass.
"""
import logging

log = logging.getLogger(__name__)

# Ordered: first match wins. Matched (case-insensitive substring) against
# "<process> <title>". User entries from config are checked before these.
DEFAULT_APP_STYLES = [
    {"match": "slack", "style": "Casual, conversational tone; lowercase is fine."},
    {"match": "discord", "style": "Casual, conversational tone; lowercase is fine."},
    {"match": "whatsapp", "style": "Casual, conversational tone; lowercase is fine."},
    {"match": "telegram", "style": "Casual, conversational tone; lowercase is fine."},
    {"match": "teams", "style": "Friendly but professional chat tone."},
    {"match": "outlook", "style": "Polished email tone; greeting and sign-off only if dictated."},
    {"match": "gmail", "style": "Polished email tone; greeting and sign-off only if dictated."},
    {"match": "mail", "style": "Polished email tone; greeting and sign-off only if dictated."},
    {"match": "code", "style": "This is a code editor; keep code identifiers, paths, and symbols verbatim; minimal prose."},
    {"match": "cursor", "style": "This is a code editor; keep code identifiers, paths, and symbols verbatim; minimal prose."},
    {"match": "devenv", "style": "This is a code editor; keep code identifiers, paths, and symbols verbatim; minimal prose."},
    {"match": "pycharm", "style": "This is a code editor; keep code identifiers, paths, and symbols verbatim; minimal prose."},
    {"match": "idea", "style": "This is a code editor; keep code identifiers, paths, and symbols verbatim; minimal prose."},
    {"match": "sublime", "style": "This is a code editor; keep code identifiers, paths, and symbols verbatim; minimal prose."},
    {"match": "notion", "style": "Clean prose with paragraph breaks."},
    {"match": "word", "style": "Clean prose with paragraph breaks."},
    {"match": "docs", "style": "Clean prose with paragraph breaks."},
]


def match_style(app_styles, process: str, title: str) -> str:
    """Return the style instruction for the first matching app rule, or ''."""
    haystack = f"{process} {title}".lower()
    for rule in app_styles:
        needle = str(rule.get("match", "")).lower()
        if needle and needle in haystack:
            return rule.get("style", "")
    return ""


def foreground_app() -> tuple[str, str]:
    """Return (process_name_lower, window_title) for the focused window, or
    ('', '') on any failure (so callers can just omit the app hint)."""
    try:
        import ctypes
        from ctypes import wintypes

        u32 = ctypes.windll.user32
        hwnd = u32.GetForegroundWindow()
        if not hwnd:
            return "", ""

        length = u32.GetWindowTextLengthW(hwnd)
        title_buf = ctypes.create_unicode_buffer(length + 1)
        u32.GetWindowTextW(hwnd, title_buf, length + 1)
        title = title_buf.value

        pid = wintypes.DWORD()
        u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        proc = ""
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        handle = ctypes.windll.kernel32.OpenProcess(
            PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
        if handle:
            try:
                buf = ctypes.create_unicode_buffer(260)
                size = wintypes.DWORD(260)
                if ctypes.windll.kernel32.QueryFullProcessImageNameW(
                        handle, 0, buf, ctypes.byref(size)):
                    proc = buf.value.rsplit("\\", 1)[-1]
            finally:
                ctypes.windll.kernel32.CloseHandle(handle)
        return proc.lower(), title
    except Exception:
        log.debug("foreground_app failed", exc_info=True)
        return "", ""
