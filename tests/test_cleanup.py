import pytest

from app import cleanup
from app.cleanup import (CleanupError, build_messages, clean, preserves_language,
                         added_content, answered_instead_of_cleaned,
                         contains_unsupported_script)


class FakeResponse:
    def __init__(self, status_code=200, content="cleaned text", payload=None, text=""):
        self.status_code = status_code
        self._payload = payload if payload is not None else {
            "choices": [{"message": {"content": content}}]
        }
        self.text = text or "resp"

    def json(self):
        return self._payload


def _capture_post(monkeypatch, response):
    calls = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        calls.update(url=url, headers=headers, json=json, timeout=timeout)
        return response

    monkeypatch.setattr("app.net.post", fake_post)
    return calls


def test_build_messages_balanced_includes_rules_and_text():
    msgs = build_messages("hi there", style="balanced", dictionary=[], language="auto")
    assert msgs[0]["role"] == "system"
    assert "filler" in msgs[0]["content"]
    assert "Never translate" in msgs[0]["content"]
    assert msgs[1] == {"role": "user", "content": "hi there"}


def test_build_messages_dictionary_only_when_present():
    without = build_messages("x", style="balanced", dictionary=[], language="auto")
    assert "Spell these names" not in without[0]["content"]
    with_terms = build_messages("x", style="balanced",
                                dictionary=["Adithya", "git diff"], language="auto")
    assert "Adithya" in with_terms[0]["content"]
    assert "git diff" in with_terms[0]["content"]


def test_build_messages_app_hint_included():
    msgs = build_messages("x", style="balanced", dictionary=[], language="auto",
                          app_hint="slack.exe Slack", app_style="Casual tone.")
    assert "slack" in msgs[0]["content"].lower()
    assert "Casual tone." in msgs[0]["content"]


def test_build_messages_app_hint_omitted_when_empty():
    msgs = build_messages("x", style="balanced", dictionary=[], language="auto")
    assert "typing into" not in msgs[0]["content"].lower()


def test_build_messages_language_hint():
    zh = build_messages("x", style="balanced", dictionary=[], language="zh")
    assert "Traditional Chinese" in zh[0]["content"]
    auto = build_messages("x", style="balanced", dictionary=[], language="auto")
    # auto must not pin a language ("The text is in ...")
    assert "The text is in" not in auto[0]["content"]


def test_preserves_language_flags_english_to_chinese():
    # the reported bug: English transcript turned into Chinese
    assert preserves_language("let's meet at noon tomorrow", "我們明天中午見面") is False


def test_preserves_language_keeps_english():
    assert preserves_language("lets meet at noon", "Let's meet at noon.") is True


def test_preserves_language_keeps_chinese():
    assert preserves_language("今天天气很好", "今天天氣很好。") is True


def test_preserves_language_keeps_mixed_codeswitch():
    # English+Chinese mix should not be seen as a language flip
    assert preserves_language("用 VSCode 寫程式", "用 VSCode 寫程式。") is True


def test_preserves_language_flags_partial_translation():
    # the reported bug: English transcript, cleanup rendered 'Traditional Chinese' as 繁體中文
    assert preserves_language("when I said replace in Traditional Chinese",
                              "When I said replace in 繁體中文") is False


def test_preserves_language_flags_english_injected_into_chinese():
    # a Chinese-only transcript must not sprout English words
    assert preserves_language("今天天氣很好", "Today the weather is 很好") is False


def test_preserves_language_allows_english_with_digits_and_punct():
    assert preserves_language("call me at 5 pm", "Call me at 5 PM.") is True


def test_preserves_language_allows_pinyin_to_han_in_mixed():
    # a mixed sentence whose romanized Chinese is converted to Han must NOT be reverted
    assert preserves_language("我要用 shu ju 分析這個 quan xian",
                              "我要用數據分析這個權限") is True


def test_build_messages_traditional_rule_is_scoped_to_chinese():
    # the Traditional rule is present but scoped to "if the transcript contains Chinese",
    # so it won't prime translation of English dictation (the preserves_language guard
    # still backstops that). It also forbids pinyin.
    content = build_messages("x", style="balanced", dictionary=[], language="auto")[0]["content"]
    assert "traditional chinese" in content.lower()
    assert "if the transcript contains chinese" in content.lower()
    assert "pinyin" in content.lower()


def test_build_messages_forbids_synonym_swaps():
    content = build_messages("x", style="balanced", dictionary=[], language="auto")[0]["content"]
    assert "synonym" in content.lower()
    assert "數據" in content and "權限" in content


def test_added_content_flags_sentence_completion():
    # cleanup must not finish the thought
    assert added_content(
        "i think we should",
        "I think we should meet tomorrow to discuss the whole roadmap in detail") is True


def test_added_content_allows_normal_cleanup():
    # filler removal + punctuation shrinks or keeps length
    assert added_content("um so i think we should uh meet the client",
                         "I think we should meet the client.") is False


def test_added_content_allows_small_grammar_fix():
    assert added_content("me want go store", "I want to go to the store") is False


def test_answered_flags_question_replaced_by_answer():
    # cleanup must not answer the dictated question
    assert answered_instead_of_cleaned("what is the capital of france", "Paris") is True


def test_answered_allows_normal_cleanup():
    assert answered_instead_of_cleaned(
        "um what is the capital of france by the way",
        "What is the capital of France?") is False


def test_answered_exempts_heavy_style():
    # heavy style is allowed to rephrase freely
    assert answered_instead_of_cleaned(
        "what is the capital of france", "Paris", style="heavy") is False


def test_answered_ignores_short_utterances():
    assert answered_instead_of_cleaned("thanks", "Got it.") is False


def test_answered_not_tripped_by_number_to_digit_conversion():
    # a number-heavy utterance turned into digits must NOT look like an "answer"
    assert answered_instead_of_cleaned(
        "five five five one two three four", "5551234") is False
    assert answered_instead_of_cleaned(
        "june eighteenth twenty twenty six", "June 18, 2026") is False


def test_build_messages_includes_numeric_formatting_rule():
    msgs = build_messages("x", style="balanced", dictionary=[], language="auto")
    content = msgs[0]["content"].lower()
    assert "digits" in content and "june 18" in content


def test_contains_unsupported_script_flags_foreign_languages():
    assert contains_unsupported_script("안녕하세요") is True        # Korean
    assert contains_unsupported_script("こんにちは") is True        # Japanese hiragana
    assert contains_unsupported_script("カタカナ") is True          # Japanese katakana
    assert contains_unsupported_script("Привет") is True           # Cyrillic


def test_contains_unsupported_script_allows_english_and_chinese():
    assert contains_unsupported_script("Hello, world!") is False
    assert contains_unsupported_script("今天天氣很好，2026年。") is False   # Mandarin + digits
    assert contains_unsupported_script("用 VSCode 寫程式") is False         # mixed EN/中文
    assert contains_unsupported_script("") is False


def test_build_messages_forbids_answering():
    msgs = build_messages("hi", style="balanced", dictionary=[], language="auto")
    sys = msgs[0]["content"].lower()
    assert "not an assistant" in sys or "do not answer" in sys or "do not reply" in sys


def test_clean_success(monkeypatch):
    calls = _capture_post(monkeypatch, FakeResponse(content="Hello, world."))
    out = clean("hello world", model="gpt-4o-mini", api_key="sk-x",
                base_url="https://api.openai.com/v1")
    assert out == "Hello, world."
    assert calls["url"] == "https://api.openai.com/v1/chat/completions"
    assert calls["headers"]["Authorization"] == "Bearer sk-x"
    assert calls["json"]["model"] == "gpt-4o-mini"
    assert calls["json"]["temperature"] == 0


def test_clean_strips_one_pair_of_wrapping_quotes(monkeypatch):
    _capture_post(monkeypatch, FakeResponse(content='"Quoted output"'))
    assert clean("x", model="m", api_key="k", base_url="u") == "Quoted output"


def test_clean_keeps_inner_quotes(monkeypatch):
    _capture_post(monkeypatch, FakeResponse(content='He said "hi" to me'))
    assert clean("x", model="m", api_key="k", base_url="u") == 'He said "hi" to me'


def test_clean_empty_input_makes_no_call(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("should not call API for empty text")

    monkeypatch.setattr("app.net.post", boom)
    assert clean("   ", model="m", api_key="k", base_url="u") == ""


def test_clean_missing_key_raises_without_call(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("should not call API without key")

    monkeypatch.setattr("app.net.post", boom)
    with pytest.raises(CleanupError):
        clean("hi", model="m", api_key="", base_url="u")


def test_clean_http_error_raises(monkeypatch):
    _capture_post(monkeypatch, FakeResponse(status_code=500, text="boom"))
    with pytest.raises(CleanupError):
        clean("hi", model="m", api_key="k", base_url="u")


def test_clean_network_error_raises(monkeypatch):
    import requests as real_requests

    def fake_post(*a, **k):
        raise real_requests.ConnectionError("no net")

    monkeypatch.setattr("app.net.post", fake_post)
    with pytest.raises(CleanupError):
        clean("hi", model="m", api_key="k", base_url="u")
