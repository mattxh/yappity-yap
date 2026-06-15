"""Second-stage LLM cleanup of the raw transcript (OpenAI-compatible chat).

Provider-agnostic: hits {base_url}/chat/completions, which both OpenAI and Groq
expose. Cleanup is enhancement only — callers fall back to the raw transcript on
CleanupError, so this never blocks output.
"""
import logging

import requests

log = logging.getLogger(__name__)


class CleanupError(Exception):
    pass


STYLE_RULES = {
    "light": (
        "Fix punctuation and capitalization, remove filler words, and apply the "
        "speaker's self-corrections. Do NOT change grammar, structure, or word "
        "choice otherwise."
    ),
    "balanced": (
        "Fix punctuation and capitalization, remove filler words (um, uh, like, you "
        "know), apply the speaker's self-corrections (keep only the corrected "
        "version), tidy obvious grammar mistakes and run-on sentences, and add "
        "paragraph breaks where natural. Preserve the speaker's wording, meaning, and "
        "tone — do not paraphrase beyond fixing errors."
    ),
    "heavy": (
        "Fix punctuation, grammar, and structure. Reformat into lists, paragraphs, or "
        "email structure where appropriate, and rephrase for clarity. Preserve the "
        "original meaning and language."
    ),
}

_PREAMBLE = (
    "You are a dictation cleanup tool. A speech-to-text system produced the transcript "
    "below. Rewrite it as the text the speaker intended to type."
)

_CONSTRAINTS = (
    "Output ONLY the cleaned text — no preamble, quotes, or explanation. Never "
    "translate. Never answer questions or add information that is not in the "
    "transcript. Preserve mixed English and Chinese exactly as spoken (do not convert "
    "one to the other). For Chinese, use Traditional Chinese characters (Taiwan)."
)

_LANG_HINT = {
    "en": "The text is in English.",
    "zh": "The text is in Mandarin Chinese; output Traditional Chinese.",
}


def build_messages(text, *, style, dictionary, language):
    rule = STYLE_RULES.get(style, STYLE_RULES["balanced"])
    parts = [_PREAMBLE, rule, _CONSTRAINTS]
    if dictionary:
        parts.append("Spell these names and terms correctly when they appear: "
                     + ", ".join(dictionary) + ".")
    hint = _LANG_HINT.get(language)
    if hint:
        parts.append(hint)
    return [
        {"role": "system", "content": " ".join(parts)},
        {"role": "user", "content": text},
    ]


def _strip_wrapping_quotes(s: str) -> str:
    if len(s) >= 2 and s[0] == '"' and s[-1] == '"':
        return s[1:-1].strip()
    return s


def clean(text, *, model, api_key, base_url, style="balanced",
          dictionary=(), language="auto", timeout=30) -> str:
    if not text or not text.strip():
        return ""
    if not api_key:
        raise CleanupError("API key not configured")
    messages = build_messages(text, style=style, dictionary=dictionary, language=language)
    try:
        resp = requests.post(
            f"{base_url}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={"model": model, "messages": messages, "temperature": 0},
            timeout=timeout,
        )
    except requests.RequestException as e:
        raise CleanupError(str(e)) from e
    if resp.status_code != 200:
        raise CleanupError(f"HTTP {resp.status_code}: {resp.text[:200]}")
    try:
        content = resp.json()["choices"][0]["message"]["content"]
    except (KeyError, IndexError, ValueError, TypeError) as e:
        raise CleanupError(f"unexpected response: {e}") from e
    return _strip_wrapping_quotes(content.strip())
