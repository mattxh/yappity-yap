from app.learn import _ratio, _is_learnable, extract_corrections


def test_ratio_identical_and_disjoint():
    assert _ratio("adithya", "adithya") == 1.0
    assert _ratio("cat", "dog") < 0.4


def test_is_learnable_near_miss_name():
    assert _is_learnable("aditya", "Adithya") is True


def test_is_learnable_rejects_low_similarity():
    assert _is_learnable("cat", "dog") is False


def test_is_learnable_rejects_unchanged():
    assert _is_learnable("now", "now") is False


def test_is_learnable_rejects_common_word():
    assert _is_learnable("their", "there") is False   # 'there' is a stopword


def test_is_learnable_rejects_short_and_known():
    assert _is_learnable("ab", "ax") is False                       # too short
    assert _is_learnable("aditya", "Adithya", {"adithya"}) is False  # already known


def test_extract_corrections_finds_name_fix():
    out = extract_corrections("call aditya now", "call aditya now", "call Adithya now")
    assert out == ["Adithya"]


def test_extract_corrections_no_change():
    assert extract_corrections("hello world", "hello world", "hello world") == []


def test_extract_corrections_unrelated_rewrite():
    out = extract_corrections("the cat sat", "the cat sat", "completely different stuff")
    assert out == []


def test_extract_corrections_respects_known():
    out = extract_corrections("call aditya now", "call aditya now", "call Adithya now",
                              known={"Adithya"})
    assert out == []
