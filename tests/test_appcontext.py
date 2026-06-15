from app.appcontext import match_style, DEFAULT_APP_STYLES


def test_match_style_slack_casual():
    style = match_style(DEFAULT_APP_STYLES, "slack.exe", "general | Acme")
    assert "casual" in style.lower()


def test_match_style_email_formal():
    style = match_style(DEFAULT_APP_STYLES, "outlook.exe", "Inbox - me@x.com")
    assert "email" in style.lower()


def test_match_style_code_editor():
    style = match_style(DEFAULT_APP_STYLES, "Code.exe", "main.py - Visual Studio Code")
    assert "code" in style.lower()


def test_match_style_unknown_returns_empty():
    assert match_style(DEFAULT_APP_STYLES, "randomgame.exe", "Some Game") == ""


def test_user_entries_take_priority_and_first_match_wins():
    user = [{"match": "acme", "style": "Use the house style."}]
    # user entries are checked before defaults; matched on proc+title
    style = match_style(user + DEFAULT_APP_STYLES, "slack.exe", "channel - Acme Corp")
    assert style == "Use the house style."


def test_match_style_case_insensitive():
    assert match_style([{"match": "SLACK", "style": "x"}], "slack.exe", "") == "x"
