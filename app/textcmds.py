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

# Spoken instructions (in command mode) that mean "learn the fixes I just made".
_LEARN_COMMANDS = {
    "correct it", "correct this", "correct that", "learn this", "learn that",
    "learn it", "learn these", "add to dictionary", "add to the dictionary",
    "remember this", "remember that", "remember these",
    "記住", "記下來", "學起來", "加入字典",
}


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


def is_learn_command(text: str) -> bool:
    """True if the spoken command means 'learn the corrections I just made'."""
    return _norm(text) in _LEARN_COMMANDS
