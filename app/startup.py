"""Create/remove the Startup-folder shortcut (start with Windows)."""
import os
import subprocess
import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent
STARTUP_DIR = (Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows"
               / "Start Menu" / "Programs" / "Startup")
SHORTCUT = STARTUP_DIR / "VoiceToText.lnk"


def is_installed() -> bool:
    return SHORTCUT.exists()


def pythonw_path() -> str:
    exe = Path(sys.executable)
    w = exe.with_name("pythonw.exe")
    return str(w if w.exists() else exe)


def install() -> None:
    ps = (
        "$ws = New-Object -ComObject WScript.Shell; "
        f"$s = $ws.CreateShortcut('{SHORTCUT}'); "
        f"$s.TargetPath = '{pythonw_path()}'; "
        "$s.Arguments = '-m app'; "
        f"$s.WorkingDirectory = '{APP_DIR}'; "
        "$s.Save()"
    )
    subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                   check=True, capture_output=True, timeout=30)


def uninstall() -> None:
    SHORTCUT.unlink(missing_ok=True)
