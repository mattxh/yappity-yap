from app.helppage import render_help


def test_help_is_self_contained():
    html = render_help("ctrl+windows", "alt+windows")
    assert html.startswith("<!doctype html>")
    assert "src=" not in html           # offline, no external resources
    assert "https://" not in html


def test_help_lists_core_features():
    html = render_help("ctrl+windows", "alt+windows")
    for kw in ["Win+Ctrl", "Win+Alt", "Command", "Snippet", "Dashboard",
               "dictionary", "Traditional"]:
        assert kw in html
