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
    inject.insert_text("HELLO", settle_ms=0)            # restore_clipboard defaults off
    assert seen["at_paste"] == "HELLO"   # the transcript is on the clipboard for the paste
    assert store["v"] == "HELLO"         # and stays there


def test_insert_text_with_restore_schedules_background_restore(monkeypatch):
    clip, store = _fake_clipboard(initial="ORIGINAL")
    seen = {}
    kb = types.SimpleNamespace(send=lambda combo: seen.__setitem__("at_paste", store["v"]),
                               is_pressed=lambda k: False)
    _install(monkeypatch, clip, kb)
    monkeypatch.setattr("app.uia.read_focused_text", lambda: "BASE")
    started = {}

    class FakeThread:
        def __init__(self, target=None, args=(), daemon=None, name=None):
            started["target"], started["args"] = target, args

        def start(self):
            started["started"] = True

    monkeypatch.setattr(inject.threading, "Thread", FakeThread)
    inject.insert_text("HELLO", settle_ms=0, restore_clipboard=True)
    assert seen["at_paste"] == "HELLO"        # transcript is on the clipboard for the paste
    assert started.get("started") is True     # a background restore was scheduled


def test_restore_clipboard_when_pasted_confirms_then_restores():
    reads = iter(["BASE", "BASE", "BASE+PASTED"])   # field changes on the 3rd poll
    sets, t = [], [0.0]
    inject._restore_clipboard_when_pasted(
        "PRIOR", "BASE", lambda: next(reads, "BASE+PASTED"), sets.append,
        timeout_ms=5000, poll_ms=60,
        clock=lambda: t[0], sleep=lambda s: t.__setitem__(0, t[0] + s))
    assert sets == ["PRIOR"]
    assert t[0] < 5.0          # restored as soon as the paste was seen, not at timeout


def test_restore_clipboard_when_pasted_falls_back_to_timeout():
    sets, t = [], [0.0]
    inject._restore_clipboard_when_pasted(
        "PRIOR", "BASE", lambda: "BASE", sets.append,   # never changes (e.g. no UIA)
        timeout_ms=500, poll_ms=60,
        clock=lambda: t[0], sleep=lambda s: t.__setitem__(0, t[0] + s))
    assert sets == ["PRIOR"]
    assert t[0] >= 0.5         # waited the full timeout before restoring


def test_set_clipboard_copies(monkeypatch):
    clip, store = _fake_clipboard()
    monkeypatch.setitem(sys.modules, "pyperclip", clip)
    assert inject.set_clipboard("hello") is True
    assert store["v"] == "hello"
