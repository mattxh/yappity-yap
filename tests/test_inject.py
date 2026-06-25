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


def test_capture_selection_returns_copied_text_and_restores_clipboard(monkeypatch):
    clip, store = _fake_clipboard()
    # Ctrl+C copies the live selection -> simulate by overwriting the clipboard
    kb = types.SimpleNamespace(send=lambda combo: store.__setitem__("v", "SELECTED"),
                               is_pressed=lambda k: False)
    _install(monkeypatch, clip, kb)
    assert inject.capture_selection(settle_ms=0) == "SELECTED"
    assert store["v"] == "PREV"   # selection read, but the user's clipboard is restored


def test_capture_selection_empty_when_nothing_selected(monkeypatch):
    clip, store = _fake_clipboard()
    # nothing selected -> Ctrl+C is a no-op, so the sentinel survives
    kb = types.SimpleNamespace(send=lambda combo: None, is_pressed=lambda k: False)
    _install(monkeypatch, clip, kb)
    assert inject.capture_selection(settle_ms=0) == ""
    assert store["v"] == "PREV"   # clipboard restored, sentinel not left behind


def test_insert_text_pastes_and_leaves_text_on_clipboard(monkeypatch):
    clip, store = _fake_clipboard(initial="ORIGINAL")
    seen = {}
    # capture what's on the clipboard at the moment Ctrl+V fires
    kb = types.SimpleNamespace(send=lambda combo: seen.__setitem__("at_paste", store["v"]),
                               is_pressed=lambda k: False)
    _install(monkeypatch, clip, kb)
    inject.insert_text("HELLO", settle_ms=0)
    assert seen["at_paste"] == "HELLO"   # the transcript is on the clipboard for the paste
    assert store["v"] == "HELLO"         # and stays there — no racy restore that could
    #                                      paste the OLD clipboard instead


def test_set_clipboard_copies(monkeypatch):
    clip, store = _fake_clipboard()
    monkeypatch.setitem(sys.modules, "pyperclip", clip)
    assert inject.set_clipboard("hello") is True
    assert store["v"] == "hello"
