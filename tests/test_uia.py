from app import uia


def test_focused_is_text_input_none_when_uia_unavailable(monkeypatch):
    # When UI Automation can't be reached, the check is inconclusive (None) so the
    # caller falls back to pasting as usual.
    monkeypatch.setattr(uia, "_client", lambda: (None, None))
    assert uia.focused_is_text_input() is None


def test_read_focused_text_none_when_uia_unavailable(monkeypatch):
    monkeypatch.setattr(uia, "_client", lambda: (None, None))
    assert uia.read_focused_text() is None
