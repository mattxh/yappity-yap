"""Win+Ctrl chord detection: pure state machine + keyboard-library adapter."""
import logging
import time

log = logging.getLogger(__name__)

IDLE = "idle"          # waiting for chord
HELD = "held"          # recording; tap/hold not yet classified
TOGGLED = "toggled"    # recording hands-free after a tap
DRAIN = "drain"        # cancelled; wait for full release
BUSY = "busy"          # pipeline running; ignore chords


class ChordMachine:
    def __init__(self, on_start, on_stop, on_cancel,
                 tap_threshold_ms=400, clock=time.monotonic):
        self.on_start = on_start
        self.on_stop = on_stop
        self.on_cancel = on_cancel
        self.tap_threshold = tap_threshold_ms / 1000.0
        self.clock = clock
        self.state = IDLE
        self.ctrl = False
        self.win = False
        self.other_held = 0
        self.t0 = 0.0

    # -- public API ---------------------------------------------------------

    def handle(self, etype: str, key: str) -> bool:
        """Feed one normalized event. Returns True if the event is part of a
        chord interaction (adapter uses this to suppress the Start menu)."""
        in_chord_before = self.state != IDLE

        if key == "ctrl":
            self.ctrl = etype == "down"
        elif key == "win":
            self.win = etype == "down"
        elif key == "other":
            if etype == "down":
                self.other_held += 1
            else:
                self.other_held = max(0, self.other_held - 1)

        chord_complete = (
            etype == "down" and key in ("ctrl", "win") and self.ctrl and self.win
        )

        if self.state == IDLE:
            if chord_complete and self.other_held == 0:
                self.state = HELD
                self.t0 = self.clock()
                self._safe(self.on_start)
                return True
            return False

        if self.state == HELD:
            if key in ("esc", "other") and etype == "down":
                self.state = DRAIN
                self._safe(self.on_cancel)
            elif etype == "up" and key in ("ctrl", "win"):
                elapsed = self.clock() - self.t0
                if elapsed < self.tap_threshold:
                    self.state = TOGGLED
                else:
                    self.state = BUSY
                    self._safe(self.on_stop)
            return True

        if self.state == TOGGLED:
            if key == "esc" and etype == "down":
                self.state = IDLE
                self._safe(self.on_cancel)
            elif chord_complete:
                self.state = BUSY
                self._safe(self.on_stop)
            return True

        if self.state == DRAIN:
            if not self.ctrl and not self.win and self.other_held == 0:
                self.state = IDLE
            return True

        if self.state == BUSY:
            return key in ("ctrl", "win")

        return in_chord_before

    def external_stop(self) -> bool:
        """Force-stop (max-duration timer). Caller runs the pipeline itself;
        no on_stop callback is fired. Returns True if we were recording."""
        if self.state in (HELD, TOGGLED):
            self.state = BUSY
            return True
        return False

    def pipeline_done(self):
        if self.state == BUSY:
            self.state = IDLE

    def is_recording(self) -> bool:
        return self.state in (HELD, TOGGLED)

    # -- internals ----------------------------------------------------------

    def _safe(self, cb):
        try:
            cb()
        except Exception:
            log.exception("hotkey callback failed")


class KeyboardHookAdapter:
    """Bridges the `keyboard` library to ChordMachine. Listen-only hook
    (no global suppression — safer). Injects a dummy VK on Win-up inside a
    chord so Windows never opens the Start menu."""

    def __init__(self, machine: ChordMachine):
        self.machine = machine
        self._hook = None

    @staticmethod
    def normalize(name: str) -> str:
        n = (name or "").lower()
        if "ctrl" in n:
            return "ctrl"
        if "windows" in n or n in ("win", "left win", "right win", "cmd"):
            return "win"
        if n in ("esc", "escape"):
            return "esc"
        return "other"

    def start(self):
        import keyboard  # imported here so logic tests never need the hook

        def callback(event):
            etype = "down" if event.event_type == "down" else "up"
            key = self.normalize(event.name)
            in_chord = self.machine.handle(etype, key)
            # Also fire when Ctrl is still physically down (user held the chord
            # through the whole pipeline; machine may already be back to idle).
            if key == "win" and etype == "up" and (in_chord or self.machine.ctrl):
                self._send_dummy_vk()

        self._hook = keyboard.hook(callback)

    def stop(self):
        if self._hook is not None:
            import keyboard

            keyboard.unhook(self._hook)
            self._hook = None

    @staticmethod
    def _send_dummy_vk():
        """Send unassigned VK 0xE8 so the OS sees 'another key' before Win-up
        and does not open the Start menu (classic AutoHotkey trick)."""
        import ctypes

        ctypes.windll.user32.keybd_event(0xE8, 0, 0, 0)
        ctypes.windll.user32.keybd_event(0xE8, 0, 2, 0)  # KEYEVENTF_KEYUP
