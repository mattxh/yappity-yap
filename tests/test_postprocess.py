from app import postprocess as pp


def test_simplified_converted_to_traditional():
    assert pp.process("简体中文测试", append_space=True) == "簡體中文測試"


def test_traditional_unchanged():
    assert pp.process("繁體中文測試", append_space=True) == "繁體中文測試"


def test_english_gets_trailing_space():
    assert pp.process("Hello world", append_space=True) == "Hello world "


def test_english_sentence_punctuation_gets_trailing_space():
    assert pp.process("Hello world.", append_space=True) == "Hello world. "


def test_no_trailing_space_when_disabled():
    assert pp.process("Hello world", append_space=False) == "Hello world"


def test_no_trailing_space_after_cjk_punctuation():
    assert pp.process("你好。", append_space=True) == "你好。"


def test_mixed_text_converted_and_no_space_after_han():
    # Simplified 请 -> Traditional 請; ends with Han 我 so no trailing space.
    assert pp.process("请 email 我", append_space=True) == "請 email 我"


def test_mixed_text_ending_in_latin_gets_space():
    # Han converted, but ends with a latin word -> trailing space.
    assert pp.process("请检查 email", append_space=True) == "請檢查 email "


def test_whitespace_stripped_and_empty_safe():
    assert pp.process("  hi  ", append_space=True) == "hi "
    assert pp.process("   ", append_space=True) == ""
    assert pp.process("", append_space=True) == ""
