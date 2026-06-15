from pathlib import Path

from app import startup


def test_shortcut_path_is_in_startup_folder():
    assert startup.SHORTCUT.name == "VoiceToText.lnk"
    assert "Startup" in str(startup.SHORTCUT)


def test_pythonw_path_points_to_exe():
    p = startup.pythonw_path()
    assert p.lower().endswith(".exe")
    assert Path(p).exists()


def test_is_installed_returns_bool():
    assert isinstance(startup.is_installed(), bool)
