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

# Spoken instructions (in command mode) that mean "fix the word I just dictated":
# diff the last dictation against the selection.
_CORRECT_COMMANDS = {
    "correct it", "correct this", "correct that", "learn this", "learn that",
    "learn it", "learn these", "remember this", "remember that", "remember these",
    "記住", "記下來", "學起來",
}
# Instructions that mean "add the selected text to the dictionary" — a direct add,
# no prior dictation needed.
_ADD_COMMANDS = {
    "add to dictionary", "add to the dictionary", "add to my dictionary",
    "add word", "add words", "add this word", "add this to the dictionary",
    "save to dictionary", "加入字典", "加到字典",
}
_LEARN_COMMANDS = _CORRECT_COMMANDS | _ADD_COMMANDS


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
    """True if the spoken command means 'add to / correct the dictionary'."""
    return _norm(text) in _LEARN_COMMANDS


def is_add_command(text: str) -> bool:
    """True if the command means 'add the selected text to the dictionary directly'
    (rather than diffing it against the last dictation)."""
    return _norm(text) in _ADD_COMMANDS
