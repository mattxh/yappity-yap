import threading
import time

from app import tray


class BoomIcon:
    """Its icon setter always fails, like pystray's Win32 backend raising
    WinError 1402 when the native icon handle is briefly invalid."""

    @property
    def icon(self):
        return None

    @icon.setter
    def icon(self, value):
        raise OSError("[WinError 1402] invalid icon handle")


class ConcurrencyProbe:
    """Flags if two threads are ever inside the icon setter at once."""

    def __init__(self):
        self._inside = False
        self.violation = False
        self._icon = None

    @property
    def icon(self):
        return self._icon

    @icon.setter
    def icon(self, value):
        if self._inside:
            self.violation = True
        self._inside = True
        time.sleep(0.001)          # widen the window; the GIL is released here
        self._inside = False
        self._icon = value


def test_apply_icon_swallows_backend_error():
    # A flaky tray backend must never propagate into the dictation pipeline.
    tray.apply_icon(BoomIcon(), object())   # must not raise


def test_apply_icon_serializes_concurrent_updates():
    # The hotkey, worker and watchdog threads all set the tray state; pystray's
    # setter is not thread-safe, so apply_icon must serialize them.
    probe = ConcurrencyProbe()

    def hammer():
        for _ in range(25):
            tray.apply_icon(probe, object())

    threads = [threading.Thread(target=hammer) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert probe.violation is False


def test_apply_icon_sets_the_image():
    probe = ConcurrencyProbe()
    sentinel = object()
    tray.apply_icon(probe, sentinel)
    assert probe.icon is sentinel
