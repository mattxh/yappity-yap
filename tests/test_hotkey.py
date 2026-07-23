import pytest

from app.hotkey import ChordMachine, KeyboardHookAdapter, chord_mods, single_key


class FakeClock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t

    def advance(self, s):
        self.t += s


class Spy:
    def __init__(self):
        self.calls = []

    def start(self):
        self.calls.append("start")

    def stop(self):
        self.calls.append("stop")

    def cancel(self):
        self.calls.append("cancel")


@pytest.fixture()
def rig():
    clock = FakeClock()
    spy = Spy()
    m = ChordMachine(on_start=spy.start, on_stop=spy.stop, on_cancel=spy.cancel,
                     tap_threshold_ms=400, clock=clock)
    return m, spy, clock


def test_hold_flow_push_to_talk(rig):
    m, spy, clock = rig
    m.handle("down", "ctrl")
    m.handle("down", "win")
    assert spy.calls == ["start"]
    clock.advance(0.6)
    m.handle("up", "win")
    assert spy.calls == ["start", "stop"]
    m.handle("up", "ctrl")
    assert spy.calls == ["start", "stop"]  # no double fire


def test_reverse_order_also_starts(rig):
    m, spy, _ = rig
    m.handle("down", "win")
    m.handle("down", "ctrl")
    assert spy.calls == ["start"]


def test_tap_toggles_then_second_tap_stops(rig):
    m, spy, clock = rig
    m.handle("down", "ctrl")
    m.handle("down", "win")
    clock.advance(0.1)
    m.handle("up", "win")
    m.handle("up", "ctrl")
    assert spy.calls == ["start"]  # still recording (toggled)
    clock.advance(2.0)
    m.handle("down", "ctrl")
    m.handle("down", "win")  # chord completes again -> stop
    assert spy.calls == ["start", "stop"]
    m.handle("up", "win")
    m.handle("up", "ctrl")
    assert spy.calls == ["start", "stop"]


def test_esc_cancels_while_held(rig):
    m, spy, _ = rig
    m.handle("down", "ctrl")
    m.handle("down", "win")
    m.handle("down", "esc")
    assert spy.calls == ["start", "cancel"]
    m.handle("up", "esc")
    m.handle("up", "win")
    m.handle("up", "ctrl")
    # after full release a new chord works again
    m.pipeline_done()  # no-op safety
    m.handle("down", "ctrl")
    m.handle("down", "win")
    assert spy.calls == ["start", "cancel", "start"]


def test_esc_cancels_while_toggled(rig):
    m, spy, clock = rig
    m.handle("down", "ctrl")
    m.handle("down", "win")
    clock.advance(0.1)
    m.handle("up", "win")
    m.handle("up", "ctrl")
    m.handle("down", "esc")
    assert spy.calls == ["start", "cancel"]


def test_other_key_during_hold_cancels_passthrough(rig):
    m, spy, _ = rig
    m.handle("down", "ctrl")
    m.handle("down", "win")
    m.handle("down", "other")  # e.g. Win+Ctrl+Left
    assert spy.calls == ["start", "cancel"]
    m.handle("up", "other")
    m.handle("up", "win")
    m.handle("up", "ctrl")
    m.handle("down", "ctrl")
    m.handle("down", "win")
    assert spy.calls == ["start", "cancel", "start"]


def test_chord_starts_despite_stray_other_key(rig):
    # Regression: a leaked/unbalanced "other" key-down (a missed key-up or the
    # synthetic Start-menu-suppression key) must NEVER block the hotkey from
    # starting. This is what wedged the hotkey "after a few uses".
    m, spy, _ = rig
    m.handle("down", "other")   # no matching "up" — would have leaked the old counter
    m.handle("down", "ctrl")
    m.handle("down", "win")
    assert spy.calls == ["start"]


def test_busy_fresh_chord_starts_next_take(rig):
    # Changed design: a fresh chord while the last take transcribes starts the next
    # take immediately (the App layer enforces the queue-depth limit).
    m, spy, clock = rig
    m.handle("down", "ctrl")
    m.handle("down", "win")
    clock.advance(0.6)
    m.handle("up", "win")
    m.handle("up", "ctrl")
    assert spy.calls == ["start", "stop"]
    m.handle("down", "ctrl")
    m.handle("down", "win")  # fresh chord while busy -> next take
    assert spy.calls == ["start", "stop", "start"]
    assert m.is_recording()


def test_external_stop_in_toggled(rig):
    m, spy, clock = rig
    m.handle("down", "ctrl")
    m.handle("down", "win")
    clock.advance(0.1)
    m.handle("up", "win")
    m.handle("up", "ctrl")
    assert m.external_stop() is True  # auto-stop fires
    assert spy.calls == ["start"]  # external_stop does NOT call on_stop; caller owns pipeline
    m.handle("down", "ctrl")
    m.handle("down", "win")  # fresh chord while busy -> next take starts
    assert spy.calls == ["start", "start"]


def test_external_stop_noop_when_idle(rig):
    m, spy, _ = rig
    assert m.external_stop() is False


def test_drain_recovers_on_fresh_chord_after_missed_keyup(rig):
    # Reproduces "first tap in a new box fails, second works": a cancel drops us into
    # DRAIN, then a modifier key-up is missed (e.g. Win+Ctrl+arrow switched desktops),
    # so DRAIN would normally strand and swallow the next tap. A fresh chord must recover.
    m, spy, clock = rig
    m.handle("down", "ctrl")
    m.handle("down", "win")            # HELD (recording)
    m.handle("down", "other")          # DRAIN (cancelled)
    assert spy.calls == ["start", "cancel"]
    m.handle("up", "other")
    m.handle("up", "win")              # NOTE: ctrl-up is never seen (missed) -> still DRAIN
    assert not m.is_idle()
    clock.advance(1.0)
    m.handle("down", "ctrl")
    m.handle("down", "win")            # fresh chord -> should start, not be swallowed
    assert spy.calls == ["start", "cancel", "start"]


def test_reset_recovers_to_idle(rig):
    m, spy, _ = rig
    m.handle("down", "ctrl")
    m.handle("down", "win")          # HELD (recording)
    assert not m.is_idle()
    m.reset()
    assert m.is_idle() and not m.is_recording()
    m.handle("down", "ctrl")
    m.handle("down", "win")          # works again after recovery
    assert spy.calls == ["start", "start"]


def test_force_start_only_from_idle(rig):
    m, spy, _ = rig
    assert m.force_start() is True
    assert m.is_recording() is True
    assert m.force_start() is False   # already recording
    assert spy.calls == []            # caller owns UI/recorder side effects
    assert m.external_stop() is True
    m.pipeline_done()
    assert m.force_start() is True


def test_in_chord_hint_for_start_menu_suppression(rig):
    m, _, clock = rig
    assert m.handle("down", "ctrl") is False  # nothing yet
    assert m.handle("down", "win") is True    # chord began
    clock.advance(0.6)
    assert m.handle("up", "win") is True      # inside interaction
    assert m.handle("up", "ctrl") is True     # still draining busy chord keys
    m.pipeline_done()
    assert m.handle("down", "other") is False


# -- generalized modifier pair (alt+win for command mode) --------------------

def _alt_rig():
    clock = FakeClock()
    spy = Spy()
    m = ChordMachine(on_start=spy.start, on_stop=spy.stop, on_cancel=spy.cancel,
                     mods=("alt", "win"), tap_threshold_ms=400, clock=clock)
    return m, spy, clock


def test_alt_win_hold_push_to_talk():
    m, spy, clock = _alt_rig()
    m.handle("down", "alt")
    m.handle("down", "win")
    assert spy.calls == ["start"]
    clock.advance(0.6)
    m.handle("up", "win")
    assert spy.calls == ["start", "stop"]


def test_alt_win_tap_toggles():
    m, spy, clock = _alt_rig()
    m.handle("down", "alt")
    m.handle("down", "win")
    clock.advance(0.1)
    m.handle("up", "win")
    m.handle("up", "alt")
    assert spy.calls == ["start"]      # still recording (toggled)
    clock.advance(1.0)
    m.handle("down", "alt")
    m.handle("down", "win")            # second chord -> stop
    assert spy.calls == ["start", "stop"]


def test_alt_win_chord_ignores_foreign_modifier():
    # ctrl is normalized to "other" for an alt+win chord and must never start it
    m, spy, _ = _alt_rig()
    m.handle("down", "other")   # e.g. ctrl
    m.handle("down", "win")
    assert spy.calls == []      # alt never pressed -> no start


def test_default_mods_are_ctrl_win():
    m = ChordMachine(lambda: None, lambda: None, lambda: None)
    assert m.mods == ("ctrl", "win")


def test_adapter_normalizes_for_its_own_mods():
    cmd = KeyboardHookAdapter(ChordMachine(lambda: None, lambda: None, lambda: None,
                                           mods=("alt", "win")))
    assert cmd.normalize("left alt") == "alt"
    assert cmd.normalize("right windows") == "win"
    assert cmd.normalize("ctrl") == "other"     # foreign to this chord
    assert cmd.normalize("escape") == "esc"

    dic = KeyboardHookAdapter(ChordMachine(lambda: None, lambda: None, lambda: None))
    assert dic.normalize("left ctrl") == "ctrl"
    assert dic.normalize("alt") == "other"      # foreign to ctrl+win
    assert dic.normalize("windows") == "win"


def test_menu_guard_active_tracks_non_win_modifier():
    m = ChordMachine(lambda: None, lambda: None, lambda: None, mods=("alt", "win"))
    assert m.menu_guard_active() is False
    m.handle("down", "alt")
    assert m.menu_guard_active() is True        # alt held -> keep suppressing Start menu
    m.handle("up", "alt")
    assert m.menu_guard_active() is False


@pytest.mark.parametrize("text,expected", [
    ("ctrl+windows", ("ctrl", "win")),
    ("windows+ctrl", ("ctrl", "win")),
    ("alt+windows", ("alt", "win")),
    ("win+alt", ("alt", "win")),
    ("f8", None),
    ("ctrl+alt", None),
    ("", None),
])
def test_chord_mods_parsing(text, expected):
    assert chord_mods(text) == expected


def test_adapter_dispatch_drives_hold_for_alt_win(monkeypatch):
    # End-to-end through the adapter: real OS key names -> normalize -> machine.
    # Proves Win+Alt hold-to-talk fires start on press and stop on release.
    clock = FakeClock()
    spy = Spy()
    m = ChordMachine(on_start=spy.start, on_stop=spy.stop, on_cancel=spy.cancel,
                     mods=("alt", "win"), tap_threshold_ms=400, clock=clock)
    adapter = KeyboardHookAdapter(m)
    monkeypatch.setattr(adapter, "_send_dummy_vk", lambda: None)
    adapter._dispatch("down", "left alt")
    adapter._dispatch("down", "left windows")
    assert spy.calls == ["start"]
    clock.advance(0.6)
    adapter._dispatch("up", "left windows")     # release after a hold -> stop
    assert spy.calls == ["start", "stop"]


@pytest.mark.parametrize("hk,expected", [
    ("f9", "f9"),
    ("F10", "f10"),
    ("space", "space"),
    ("ctrl+alt+s", None),
    ("ctrl+windows", None),
    ("ctrl", None),
    ("", None),
])
def test_single_key_parsing(hk, expected):
    assert single_key(hk) == expected


def _key_machine():
    clock = FakeClock()
    spy = Spy()
    m = ChordMachine(on_start=spy.start, on_stop=spy.stop, on_cancel=spy.cancel,
                     mods=("f9",), tap_threshold_ms=400, clock=clock)
    return m, spy, clock


def test_single_key_hold_to_talk():
    m, spy, clock = _key_machine()
    m.handle("down", "f9")            # press -> start
    assert spy.calls == ["start"] and m.is_recording()
    clock.advance(0.6)                # held past the tap threshold
    m.handle("up", "f9")              # release -> stop (push-to-talk)
    assert spy.calls == ["start", "stop"]


def test_single_key_tap_to_toggle():
    m, spy, clock = _key_machine()
    m.handle("down", "f9")
    clock.advance(0.1)
    m.handle("up", "f9")              # quick tap -> keep recording hands-free
    assert spy.calls == ["start"] and m.is_recording()
    m.handle("down", "f9")           # tap again -> stop
    assert spy.calls == ["start", "stop"]


def test_tap_during_pipeline_starts_next_take():
    # While the last take is transcribing (BUSY), a fresh tap starts the next one
    # instead of being swallowed — recording overlaps the pipeline.
    m, spy, clock = _key_machine()
    m.handle("down", "f9")
    clock.advance(0.1)
    m.handle("up", "f9")              # tap -> hands-free recording
    m.handle("down", "f9")            # tap again -> stop, pipeline runs (BUSY)
    assert spy.calls == ["start", "stop"]
    m.handle("up", "f9")
    m.handle("down", "f9")            # fresh press while BUSY -> next take starts
    assert spy.calls == ["start", "stop", "start"]
    assert m.is_recording()


def test_holding_the_stopping_tap_does_not_restart():
    # The tap that STOPS a recording must not restart one via OS key auto-repeat
    # if the user holds it a beat too long.
    m, spy, clock = _key_machine()
    m.handle("down", "f9")
    clock.advance(0.1)
    m.handle("up", "f9")
    m.handle("down", "f9")            # stop -> BUSY (key still held)
    m.handle("down", "f9")            # auto-repeat
    m.handle("down", "f9")            # auto-repeat
    assert spy.calls == ["start", "stop"]
    assert not m.is_recording()


def test_force_start_allowed_while_pipeline_runs():
    # Combo (non-single-key) hotkeys go through force_start; it too may begin the
    # next take during BUSY.
    m, spy, clock = _key_machine()
    m.handle("down", "f9")
    clock.advance(0.1)
    m.handle("up", "f9")
    m.handle("down", "f9")            # BUSY
    m.handle("up", "f9")
    assert m.force_start() is True
    assert m.is_recording()


def test_single_key_autorepeat_during_hold_is_noop():
    m, spy, clock = _key_machine()
    m.handle("down", "f9")
    m.handle("down", "f9")           # Windows key auto-repeat while held
    m.handle("down", "f9")
    assert spy.calls == ["start"]
    clock.advance(0.6)
    m.handle("up", "f9")
    assert spy.calls == ["start", "stop"]


def test_dummy_injected_while_win_held_not_on_release():
    # Start-menu suppression must fire while Win is still down (a listen-only hook
    # can't suppress the release, so injecting on-release is too late).
    clock = FakeClock()
    spy = Spy()
    m = ChordMachine(on_start=spy.start, on_stop=spy.stop, on_cancel=spy.cancel,
                     mods=("ctrl", "win"), tap_threshold_ms=400, clock=clock)
    adapter = KeyboardHookAdapter(m)
    sent = []
    adapter._send_dummy_vk = lambda: sent.append(m.state)   # capture when it fires

    adapter._dispatch("down", "left ctrl")
    assert sent == []                       # not until Win joins the chord
    adapter._dispatch("down", "left windows")
    assert sent and m.is_recording()        # injected during the hold, once
    adapter._dispatch("down", "left windows")   # key auto-repeat must not re-inject
    assert len(sent) == 1


def test_echoed_dummy_key_does_not_cancel_recording():
    # The injected VK 0xE8 comes back through our own hook as an 'other' key; the
    # adapter must swallow it so the machine doesn't treat it as a cancel.
    clock = FakeClock()
    spy = Spy()
    m = ChordMachine(on_start=spy.start, on_stop=spy.stop, on_cancel=spy.cancel,
                     mods=("ctrl", "win"), tap_threshold_ms=400, clock=clock)
    adapter = KeyboardHookAdapter(m)
    adapter._send_dummy_vk = lambda: setattr(adapter, "_skip", adapter._skip + 2)

    adapter._dispatch("down", "left ctrl")
    adapter._dispatch("down", "left windows")   # starts recording + arms _skip
    assert spy.calls == ["start"]
    adapter._dispatch("down", "e8")             # dummy echo (down) -> swallowed
    adapter._dispatch("up", "e8")               # dummy echo (up)   -> swallowed
    assert spy.calls == ["start"]               # NOT cancelled

    # a genuine 'other' key after the echo still cancels as before
    adapter._dispatch("down", "x")
    assert spy.calls == ["start", "cancel"]
