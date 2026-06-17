import sys
import types

from app import inject


def _fake_clipboard(initial="PREV"):
    store = {"v": initial}
    mod = types.SimpleNamespace(
        copy=lambda s: store.__setitem__("v", s),
        paste=lambda: store["v"],
    )
    return mod, store


def _install(monkeypatch, clip, kb):
    monkeypatch.setitem(sys.modules, "pyperclip", clip)
    monkeypatch.setitem(sys.modules, "keyboard", kb)
    monkeypatch.setattr(inject, "_wait_modifiers_released", lambda *a, **k: None)


def test_capture_selection_returns_copied_text(monkeypatch):
    clip, store = _fake_clipboard()
    # Ctrl+C copies the live selection -> simulate by overwriting the clipboard
    kb = types.SimpleNamespace(send=lambda combo: store.__setitem__("v", "SELECTED"),
                               is_pressed=lambda k: False)
    _install(monkeypatch, clip, kb)
    assert inject.capture_selection(settle_ms=0) == "SELECTED"


def test_capture_selection_empty_when_nothing_selected(monkeypatch):
    clip, store = _fake_clipboard()
    # nothing selected -> Ctrl+C is a no-op, so the sentinel survives
    kb = types.SimpleNamespace(send=lambda combo: None, is_pressed=lambda k: False)
    _install(monkeypatch, clip, kb)
    assert inject.capture_selection(settle_ms=0) == ""
    assert store["v"] == "PREV"   # clipboard restored, sentinel not left behind
