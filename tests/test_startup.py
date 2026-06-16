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


def test_desktop_shortcut_path_and_installed():
    assert startup.desktop_shortcut_path().name == "VoiceToText.lnk"
    assert isinstance(startup.desktop_shortcut_installed(), bool)


def test_install_escapes_single_quotes_in_paths(monkeypatch):
    monkeypatch.setattr(startup, "SHORTCUT", Path("C:/o'x/VoiceToText.lnk"))
    monkeypatch.setattr(startup, "APP_DIR", Path("C:/a'b"))
    captured = {}
    monkeypatch.setattr(startup.subprocess, "run",
                        lambda args, **k: captured.setdefault("script", args[-1]))
    startup.install()
    assert "''" in captured["script"]            # quotes were doubled
    assert "CreateShortcut('" in captured["script"]  # still single-quoted args
