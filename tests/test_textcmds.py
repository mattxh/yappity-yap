from app.textcmds import snippet_match, apply_spoken_formatting


def test_snippet_exact_match_case_and_punct_insensitive():
    snippets = {"my email": "me@example.com", "sign off": "Best,\nMatt"}
    assert snippet_match("My email.", snippets) == "me@example.com"
    assert snippet_match("sign off", snippets) == "Best,\nMatt"


def test_snippet_no_match_returns_none():
    assert snippet_match("hello there", {"my email": "x"}) is None
    assert snippet_match("anything", {}) is None


def test_snippet_partial_does_not_match():
    # must be the whole utterance, not a substring
    assert snippet_match("please send my email now", {"my email": "x"}) is None


def test_spoken_formatting_commands():
    assert apply_spoken_formatting("new line") == "\n"
    assert apply_spoken_formatting("New paragraph.") == "\n\n"
    assert apply_spoken_formatting("newline") == "\n"


def test_spoken_formatting_non_command_returns_none():
    assert apply_spoken_formatting("hello world") is None
    assert apply_spoken_formatting("start a new line of business") is None
