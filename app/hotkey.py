"""Modifier-chord detection: pure state machine + keyboard-library adapter.

The chord is any pair of modifiers (default Win+Ctrl for dictation; Win+Alt is
used for command mode). Both members must be down to start; releasing either ends
a hold, a quick press toggles hands-free.
"""
import logging
import time

log = logging.getLogger(__name__)

IDLE = "idle"          # waiting for chord
HELD = "held"          # recording; tap/hold not yet classified
TOGGLED = "toggled"    # recording hands-free after a tap
DRAIN = "drain"        # cancelled; wait for full release
BUSY = "busy"          # pipeline running; ignore chords

MENU_KEY = "win"       # releasing this can open the Start menu (suppressed by the adapter)


def chord_mods(hotkey: str):
    """Map a hotkey string to a normalized (primary, 'win') modifier pair, or
    None if it isn't one of the supported chords. Only Win+Ctrl and Win+Alt get
    the full hold/tap behavior; anything else falls back to simple toggle mode."""
    toks = {t for t in (hotkey or "").lower().replace("+", " ").split()}
    mods = set()
    for t in toks:
        if "ctrl" in t:
            mods.add("ctrl")
        elif "alt" in t:
            mods.add("alt")
        elif "win" in t or t == "cmd":
            mods.add("win")
    if mods == {"ctrl", "win"}:
        return ("ctrl", "win")
    if mods == {"alt", "win"}:
        return ("alt", "win")
    return None


def single_key(hotkey: str):
    """Return the key name if `hotkey` is a single non-modifier key (e.g. 'f9'),
    else None. Such keys get tap-or-hold: a ChordMachine with mods=(key,) driven by
    the key's own press/release edges. Windows delivers those reliably (it doesn't
    steal a bare function key the way it grabs Win chords), so the release is
    dependable and the machine never strands."""
    h = (hotkey or "").strip().lower()
    if not h or "+" in h:
        return None
    if h in ("ctrl", "alt", "shift", "win", "windows", "cmd", "esc", "escape"):
        return None
    return h


class ChordMachine:
    def __init__(self, on_start, on_stop, on_cancel, mods=("ctrl", "win"),
                 tap_threshold_ms=400, clock=time.monotonic):
        self.on_start = on_start
        self.on_stop = on_stop
        self.on_cancel = on_cancel
        self.mods = tuple(mods)
        self.tap_threshold = tap_threshold_ms / 1000.0
        self.clock = clock
        self.state = IDLE
        self.down = {m: False for m in self.mods}
        self.t0 = 0.0

    # -- public API ---------------------------------------------------------

    def handle(self, etype: str, key: str) -> bool:
        """Feed one normalized event. Returns True if the event is part of a
        chord interaction (adapter uses this to suppress the Start menu)."""
        in_chord_before = self.state != IDLE

        was_down = self.down.get(key, False)
        if key in self.down:
            self.down[key] = etype == "down"
        # A press only counts as fresh if the key was actually up before it — OS
        # auto-repeat re-sends "down" while a key is held and must never re-trigger.
        fresh_press = etype == "down" and key in self.down and not was_down

        chord_complete = (
            etype == "down" and key in self.mods and all(self.down.values())
        )

        if self.state == IDLE:
            # Start on any completed chord. We deliberately do NOT gate on other
            # keys being held — that gate, fed by a drift-prone counter, was what
            # wedged the hotkey after a few uses.
            if chord_complete:
                self.state = HELD
                self.t0 = self.clock()
                self._safe(self.on_start)
                return True
            return False

        if self.state == HELD:
            if key in ("esc", "other") and etype == "down":
                self.state = DRAIN
                self._safe(self.on_cancel)
            elif etype == "up" and key in self.mods:
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
            # A fresh, complete chord means the user is starting again — recover even if
            # a key-up was missed (e.g. Win+Ctrl+arrow switched desktops and the OS ate an
            # up), which would otherwise strand us in DRAIN and swallow the next tap.
            if chord_complete:
                self.state = HELD
                self.t0 = self.clock()
                self._safe(self.on_start)
                return True
            if not any(self.down.values()):
                self.state = IDLE
            return True

        if self.state == BUSY:
            # The last take is still transcribing, but a fresh press means the user
            # wants the next one now — recording may overlap the pipeline (the App
            # decides whether to accept; the job queue keeps the output in order).
            if chord_complete and fresh_press:
                self.state = HELD
                self.t0 = self.clock()
                self._safe(self.on_start)
                return True
            return key in self.mods

        return in_chord_before

    def menu_guard_active(self) -> bool:
        """True if a non-Win modifier of this chord is still physically down, so
        the adapter keeps suppressing the Start menu even after the machine has
        gone idle (the user held the chord through the whole pipeline)."""
        return any(down for key, down in self.down.items() if key != MENU_KEY)

    def external_stop(self) -> bool:
        """Force-stop (max-duration timer). Caller runs the pipeline itself;
        no on_stop callback is fired. Returns True if we were recording."""
        if self.state in (HELD, TOGGLED):
            self.state = BUSY
            return True
        return False

    def force_start(self) -> bool:
        """Used by custom non-chord hotkeys (toggle mode). Caller invokes the
        recorder/UI itself, mirroring external_stop's contract. Starting from BUSY is
        allowed — the next take may be recorded while the last one transcribes."""
        if self.state in (IDLE, BUSY):
            self.state = TOGGLED
            self.t0 = self.clock()
            return True
        return False

    def pipeline_done(self):
        if self.state == BUSY:
            self.state = IDLE

    def is_recording(self) -> bool:
        return self.state in (HELD, TOGGLED)

    def is_idle(self) -> bool:
        return self.state == IDLE

    def reset(self):
        """Force back to IDLE and clear modifier tracking. Used by the watchdog
        to recover if the global hook ever drops a key event and desyncs us."""
        self.state = IDLE
        for m in self.down:
            self.down[m] = False

    # -- internals ----------------------------------------------------------

    def _safe(self, cb):
        try:
            cb()
        except Exception:
            log.exception("hotkey callback failed")


class KeyboardHookAdapter:
    """Bridges the `keyboard` library to ChordMachine. Listen-only hook
    (no global suppression — safer). While Win is held as part of a chord it
    injects a throwaway key so Windows never treats the release as a lone Win
    press and opens the Start menu, and it swallows that injected key so the
    chord machine never mistakes it for a real one."""

    def __init__(self, machine: ChordMachine):
        self.machine = machine
        self._hook = None
        self._skip = 0            # our injected dummy key echoing back through the hook
        self._dummy_sent = False  # dummy already injected for the current Win hold

    def normalize(self, name: str) -> str:
        """Map a raw key name to this chord's vocabulary. Modifiers outside this
        chord (e.g. Ctrl for an Alt+Win chord) become 'other' so they can't start
        or interfere with it."""
        n = (name or "").lower()
        if n in ("esc", "escape"):
            return "esc"
        if "ctrl" in n and "ctrl" in self.machine.mods:
            return "ctrl"
        if "alt" in n and "alt" in self.machine.mods:
            return "alt"
        if ("windows" in n or n in ("win", "left win", "right win", "cmd")) \
                and "win" in self.machine.mods:
            return "win"
        return "other"

    def start(self):
        import keyboard  # imported here so logic tests never need the hook

        def callback(event):
            etype = "down" if event.event_type == "down" else "up"
            self._dispatch(etype, event.name)

        self._hook = keyboard.hook(callback)

    def _dispatch(self, etype: str, name: str):
        """Feed one raw key event to the machine (split out from start() so the
        full adapter->machine wiring is unit-testable without the global hook)."""
        key = self.normalize(name)
        if self._skip and key == "other":
            self._skip -= 1          # this is our own injected dummy echoing back
            return
        self.machine.handle(etype, key)
        if MENU_KEY not in self.machine.mods:
            return
        if key == MENU_KEY and etype == "up":
            self._dummy_sent = False
        elif etype == "down" and self.machine.down.get(MENU_KEY) \
                and self.machine.menu_guard_active() and not self._dummy_sent:
            # Win is held together with the chord's other modifier. Inject the dummy
            # NOW, while Win is down, so its eventual release isn't seen as a lone Win
            # (a listen-only hook can't suppress the release, so on-release is too late).
            self._dummy_sent = True
            self._send_dummy_vk()

    def stop(self):
        if self._hook is not None:
            import keyboard

            keyboard.unhook(self._hook)
            self._hook = None

    def _send_dummy_vk(self):
        """Send unassigned VK 0xE8 so the OS sees 'another key' during the Win hold
        and does not open the Start menu (classic AutoHotkey trick). The two events
        echo back through our own hook, so pre-arm _skip to swallow them."""
        import ctypes

        self._skip += 2
        ctypes.windll.user32.keybd_event(0xE8, 0, 0, 0)
        ctypes.windll.user32.keybd_event(0xE8, 0, 2, 0)  # KEYEVENTF_KEYUP
