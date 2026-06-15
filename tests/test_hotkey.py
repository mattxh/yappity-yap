import pytest

from app.hotkey import ChordMachine


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


def test_chord_ignored_when_other_key_already_held(rig):
    m, spy, _ = rig
    m.handle("down", "other")
    m.handle("down", "ctrl")
    m.handle("down", "win")
    assert spy.calls == []
    m.handle("up", "other")
    m.handle("up", "ctrl")
    m.handle("up", "win")


def test_busy_blocks_new_chord_until_pipeline_done(rig):
    m, spy, clock = rig
    m.handle("down", "ctrl")
    m.handle("down", "win")
    clock.advance(0.6)
    m.handle("up", "win")
    m.handle("up", "ctrl")
    assert spy.calls == ["start", "stop"]
    m.handle("down", "ctrl")
    m.handle("down", "win")  # ignored: busy
    assert spy.calls == ["start", "stop"]
    m.handle("up", "win")
    m.handle("up", "ctrl")
    m.pipeline_done()
    m.handle("down", "ctrl")
    m.handle("down", "win")
    assert spy.calls == ["start", "stop", "start"]


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
    m.handle("down", "win")  # busy -> ignored
    assert spy.calls == ["start"]
    m.pipeline_done()


def test_external_stop_noop_when_idle(rig):
    m, spy, _ = rig
    assert m.external_stop() is False


def test_in_chord_hint_for_start_menu_suppression(rig):
    m, _, clock = rig
    assert m.handle("down", "ctrl") is False  # nothing yet
    assert m.handle("down", "win") is True    # chord began
    clock.advance(0.6)
    assert m.handle("up", "win") is True      # inside interaction
    assert m.handle("up", "ctrl") is True     # still draining busy chord keys
    m.pipeline_done()
    assert m.handle("down", "other") is False
