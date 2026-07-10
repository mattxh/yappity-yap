"""Create/remove Windows shortcuts (Startup-folder autostart + Desktop launcher)."""
import os
import subprocess
import sys
import winreg
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent
STARTUP_DIR = (Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows"
               / "Start Menu" / "Programs" / "Startup")
SHORTCUT = STARTUP_DIR / "Yappity Yapp.lnk"

_desktop = None


def is_installed() -> bool:
    return SHORTCUT.exists()


def pythonw_path() -> str:
    exe = Path(sys.executable)
    w = exe.with_name("pythonw.exe")
    return str(w if w.exists() else exe)


def _ps_quote(value) -> str:
    """Escape a value for a single-quoted PowerShell string ('' is a literal ')."""
    return str(value).replace("'", "''")


def make_icon_file() -> Path:
    """Render the duck icon to an .ico the shortcuts (and the .exe build) can use.
    Always re-rendered so a changed drawing takes effect."""
    from .tray import make_icon_image

    icon = APP_DIR / "icon.ico"
    make_icon_image("idle").save(
        icon, format="ICO", sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (256, 256)])
    return icon


def _save_shortcut(lnk_path: Path) -> None:
    """Write a .lnk launching `pythonw -m app` in this folder (no console)."""
    icon_line = ""
    try:
        icon_line = f"$s.IconLocation = '{_ps_quote(make_icon_file())}'; "
    except Exception:
        pass  # icon is cosmetic; shortcut still works without it
    ps = (
        "$ws = New-Object -ComObject WScript.Shell; "
        f"$s = $ws.CreateShortcut('{_ps_quote(lnk_path)}'); "
        f"$s.TargetPath = '{_ps_quote(pythonw_path())}'; "
        "$s.Arguments = '-m app'; "
        f"$s.WorkingDirectory = '{_ps_quote(APP_DIR)}'; "
        + icon_line +
        "$s.Save()"
    )
    subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                   check=True, capture_output=True, timeout=30)


def install() -> None:
    _save_shortcut(SHORTCUT)


def uninstall() -> None:
    SHORTCUT.unlink(missing_ok=True)


# -- Desktop launcher shortcut ------------------------------------------------

def desktop_dir() -> Path:
    """The user's real Desktop path (handles OneDrive redirection)."""
    global _desktop
    if _desktop is None:
        try:
            key = r"Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders"
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as k:
                val, _ = winreg.QueryValueEx(k, "Desktop")
            _desktop = Path(os.path.expandvars(val))
        except Exception:
            _desktop = Path.home() / "Desktop"
    return _desktop


def desktop_shortcut_path() -> Path:
    return desktop_dir() / "Yappity Yapp.lnk"


def desktop_shortcut_installed() -> bool:
    return desktop_shortcut_path().exists()


def install_desktop_shortcut() -> None:
    _save_shortcut(desktop_shortcut_path())


def uninstall_desktop_shortcut() -> None:
    desktop_shortcut_path().unlink(missing_ok=True)
