from app.textcmds import (snippet_match, apply_spoken_formatting, is_learn_command,
                          is_add_command)


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


def test_is_learn_command_matches_triggers():
    for s in ["correct it", "Correct it.", "learn this", "add to dictionary",
              "remember this", "記住"]:
        assert is_learn_command(s) is True


def test_is_learn_command_rejects_normal_instructions():
    for s in ["make it formal", "summarize this", "translate to English", "hello there"]:
        assert is_learn_command(s) is False


def test_is_add_command_matches_add_phrases():
    for s in ["add to dictionary", "Add to the dictionary.", "add word", "加入字典"]:
        assert is_add_command(s) is True
        assert is_learn_command(s) is True   # add phrases are also learn commands


def test_is_add_command_rejects_correct_phrases():
    for s in ["correct it", "learn this", "remember this", "記住", "make it formal"]:
        assert is_add_command(s) is False
