from app.pipeline import JobGate


class FakeTimer:
    def __init__(self, seconds, cb):
        self.seconds = seconds
        self.cb = cb
        self.started = False
        self.cancelled = False
        self.daemon = False

    def start(self):
        self.started = True

    def cancel(self):
        self.cancelled = True


def _factory(store):
    def make(seconds, cb):
        t = FakeTimer(seconds, cb)
        store.append(t)
        return t
    return make


def test_try_begin_serializes_jobs():
    g = JobGate()
    assert g.try_begin() is True       # first job accepted
    assert g.try_begin() is False      # second rejected while active
    assert g.is_active() is True
    g.end()
    assert g.is_active() is False
    assert g.try_begin() is True       # accepted again after end


def test_timer_start_and_cancel():
    store = []
    g = JobGate(timer_factory=_factory(store))
    g.start_timer(5, lambda: None)
    assert len(store) == 1 and store[0].started and store[0].daemon
    g.cancel_timer()
    assert store[0].cancelled


def test_timer_replace_cancels_previous():
    store = []
    g = JobGate(timer_factory=_factory(store))
    g.start_timer(5, lambda: None)
    g.start_timer(5, lambda: None)
    assert store[0].cancelled
    assert store[1].started and not store[1].cancelled


def test_cancel_timer_when_none_is_safe():
    g = JobGate(timer_factory=_factory([]))
    g.cancel_timer()  # no timer set — must not raise
