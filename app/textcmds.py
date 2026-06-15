"""Deterministic dictation-text commands: snippet expansion and spoken formatting.

Both match the WHOLE utterance only (a recording that is exactly the trigger), to
avoid false positives inside normal speech.
"""

_FORMAT = {
    "new line": "\n",
    "newline": "\n",
    "new paragraph": "\n\n",
    "new para": "\n\n",
}

_STRIP = " .!?。！？，,"


def _norm(text: str) -> str:
    return text.strip().lower().strip(_STRIP).strip()


def snippet_match(text: str, snippets: dict) -> str | None:
    """Return the expansion if the whole utterance equals a snippet trigger."""
    key = _norm(text)
    if not key:
        return None
    for trigger, expansion in snippets.items():
        if _norm(trigger) == key:
            return expansion
    return None


def apply_spoken_formatting(text: str) -> str | None:
    """Return a newline string if the whole utterance is a formatting command."""
    return _FORMAT.get(_norm(text))
