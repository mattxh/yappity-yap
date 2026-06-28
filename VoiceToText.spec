# -*- mode: python ; coding: utf-8 -*-
# Build a single-file Windows .exe:  python -m PyInstaller --noconfirm VoiceToText.spec
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

datas = []
datas += collect_data_files("opencc")            # Simplified -> Traditional dictionaries
datas += collect_data_files("_sounddevice_data")  # the PortAudio DLL (recording needs it)

binaries = []

hiddenimports = []
hiddenimports += collect_submodules("comtypes")   # UI Automation
hiddenimports += ["pystray._win32", "PIL._tkinter_finder"]

a = Analysis(
    ["run_app.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="VoiceToText",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=False,          # tray app — no console window
    disable_windowed_traceback=False,
    icon=None,
)
