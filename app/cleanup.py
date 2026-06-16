"""Second-stage LLM cleanup of the raw transcript (OpenAI-compatible chat).

Provider-agnostic: hits {base_url}/chat/completions, which both OpenAI and Groq
expose. Cleanup is enhancement only — callers fall back to the raw transcript on
CleanupError, so this never blocks output.
"""
import logging
import re

import requests

from . import net

log = logging.getLogger(__name__)

_HAN = re.compile(r"[一-鿿㐀-䶿豈-﫿]")
_LATIN = re.compile(r"[A-Za-z]")


class CleanupError(Exception):
    pass


def _han_ratio(text: str) -> float:
    han = len(_HAN.findall(text))
    latin = len(_LATIN.findall(text))
    base = han + latin
    return han / base if base else 0.0


def preserves_language(before: str, after: str, max_shift: float = 0.5) -> bool:
    """True unless cleanup flipped the language (e.g. English -> Chinese). Compares
    the Han / (Han+Latin) character ratio; a large swing means a translation."""
    return abs(_han_ratio(after) - _han_ratio(before)) <= max_shift


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
    # NB: must NOT command Chinese output — that would translate English input.
    # It only governs script (Traditional vs Simplified) for text already Chinese.
    "zh": "If the text is in Chinese, write it in Traditional Chinese characters "
          "(Taiwan), never Simplified. Do not translate non-Chinese text.",
}


def build_messages(text, *, style, dictionary, language, app_hint="", app_style=""):
    rule = STYLE_RULES.get(style, STYLE_RULES["balanced"])
    parts = [_PREAMBLE, rule, _CONSTRAINTS]
    if dictionary:
        parts.append("Spell these names and terms correctly when they appear: "
                     + ", ".join(dictionary) + ".")
    hint = _LANG_HINT.get(language)
    if hint:
        parts.append(hint)
    if app_hint:
        line = f"The user is typing into {app_hint}."
        if app_style:
            line += f" {app_style}"
        parts.append(line)
    return [
        {"role": "system", "content": " ".join(parts)},
        {"role": "user", "content": text},
    ]


def _strip_wrapping_quotes(s: str) -> str:
    if len(s) >= 2 and s[0] == '"' and s[-1] == '"':
        return s[1:-1].strip()
    return s


def clean(text, *, model, api_key, base_url, style="balanced",
          dictionary=(), language="auto", app_hint="", app_style="", timeout=30) -> str:
    if not text or not text.strip():
        return ""
    if not api_key:
        raise CleanupError("API key not configured")
    messages = build_messages(text, style=style, dictionary=dictionary, language=language,
                              app_hint=app_hint, app_style=app_style)
    try:
        resp = net.post(
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
