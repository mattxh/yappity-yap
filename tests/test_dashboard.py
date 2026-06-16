from app.dashboard import render_dashboard

ENTRIES = [
    {"ts": "2026-06-16T09:00:00", "lang": "en", "duration_s": 3, "chars": 11,
     "text": "hello world", "cost": 0.01, "model": "gpt-4o-transcribe"},
    {"ts": "2026-06-16T10:00:00", "lang": "zh", "duration_s": 2, "chars": 6,
     "text": "今天天氣很好", "cost": 0.02, "model": "scribe_v1"},
]
DICTIONARY = ["Anthropic", "Adithya", "Kubernetes"]
AUTO_LEARNED = ["Adithya"]
CORRECTIONS = {
    "adithya": {"old": "aditya", "new": "Adithya", "count": 3, "promoted": True},
    "kubernetes": {"old": "kubernets", "new": "Kubernetes", "count": 1, "promoted": False},
}


def _html():
    return render_dashboard(ENTRIES, DICTIONARY, AUTO_LEARNED, CORRECTIONS, promote_after=2)


def test_dashboard_is_self_contained_html():
    html = _html()
    assert html.startswith("<!doctype html>")
    assert "src=" not in html           # no external scripts/images — works offline
    assert "https://" not in html


def test_dashboard_shows_saved_and_auto_words():
    html = _html()
    assert "Anthropic" in html          # saved (manual)
    assert "Adithya" in html            # auto-added


def test_dashboard_shows_daily_and_cost():
    html = _html()
    assert "2026-06-16" in html
    assert "$" in html                  # cost figures


def test_dashboard_shows_pending_correction():
    html = _html()
    # the not-yet-promoted correction appears in the pending section
    assert "Kubernetes" in html
    assert "kubernets" in html


def test_dashboard_handles_empty():
    html = render_dashboard([], [], [], {}, promote_after=2)
    assert html.startswith("<!doctype html>")
