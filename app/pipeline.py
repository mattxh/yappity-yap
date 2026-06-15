"""Job coordination for the dictation pipeline.

JobGate serializes transcription jobs (hotkey-stop, auto-stop, retry all funnel
through it) and owns the auto-stop timer, with all shared state under one lock so the
hook / timer / tray / worker threads can't race.
"""
import threading


class JobGate:
    def __init__(self, timer_factory=threading.Timer):
        self._timer_factory = timer_factory
        self._lock = threading.Lock()
        self._active = False
        self._timer = None

    def try_begin(self) -> bool:
        """Accept a new job only if none is in flight. Returns False if busy."""
        with self._lock:
            if self._active:
                return False
            self._active = True
            return True

    def end(self):
        with self._lock:
            self._active = False

    def is_active(self) -> bool:
        with self._lock:
            return self._active

    def start_timer(self, seconds, callback):
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
            timer = self._timer_factory(seconds, callback)
            timer.daemon = True
            self._timer = timer
            timer.start()

    def cancel_timer(self):
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
