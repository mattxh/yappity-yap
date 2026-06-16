"""A simple native text-input box (Windows InputBox via PowerShell).

Avoids tkinter (single-thread/focus pitfalls) — runs as a subprocess that shows a
modal InputBox and returns the typed text on stdout (UTF-8, so Chinese works).
"""
import logging
import subprocess

log = logging.getLogger(__name__)


def _q(value) -> str:
    return str(value).replace("'", "''")


def ask_text(message: str, title: str = "VoiceToText", default: str = "") -> str:
    """Show an input box and return the entered text ('' if cancelled/blank)."""
    ps = (
        "Add-Type -AssemblyName Microsoft.VisualBasic; "
        "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; "
        f"[Microsoft.VisualBasic.Interaction]::InputBox('{_q(message)}', "
        f"'{_q(title)}', '{_q(default)}')"
    )
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                             capture_output=True, timeout=180)
        return out.stdout.decode("utf-8", "replace").strip()
    except Exception:
        log.exception("input box failed")
        return ""
