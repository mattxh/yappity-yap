"""Pure correction-detection core for the auto-learning dictionary.

Given the text we inserted, the field's text right after paste, and the field's text
later, find words the user *corrected* (a similar-but-different replacement of one of
our words) — biased toward names/jargon, guarded against junk.
"""
import difflib
import re

_TOKEN = re.compile(r"\S+")
_PUNCT = " .,!?;:\"'()[]{}…—-。，、；：？！「」『』（）"

# Common words we never want to auto-learn even if they look like a "correction".
_STOPWORDS = {
    "the", "and", "for", "are", "but", "not", "you", "all", "any", "can", "had", "her",
    "was", "one", "our", "out", "day", "get", "has", "him", "his", "how", "now", "see",
    "two", "way", "who", "boy", "did", "its", "let", "put", "say", "she", "too", "use",
    "there", "their", "they", "this", "that", "with", "have", "from", "your", "here",
    "what", "when", "then", "than", "them", "were", "been", "into", "over", "also",
}


def _ratio(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a, b).ratio()


def _is_learnable(old: str, new: str, known_lower=frozenset(), min_ratio: float = 0.6) -> bool:
    n = new.strip()
    if len(n) < 3 or " " in n:
        return False
    if not any(c.isalpha() for c in n):
        return False
    nl = n.lower()
    if nl in known_lower or nl in _STOPWORDS:
        return False
    if old.strip().lower() == nl:
        return False
    return _ratio(old.strip().lower(), nl) >= min_ratio


def extract_corrections(inserted: str, snapshot_after: str, current: str,
                        known=frozenset(), min_ratio: float = 0.6) -> list:
    """Return corrected terms (as the user typed them) to learn into the dictionary."""
    inserted_words = {w.strip(_PUNCT).lower() for w in _TOKEN.findall(inserted)}
    a = _TOKEN.findall(snapshot_after)
    b = _TOKEN.findall(current)
    known_lower = {str(k).lower() for k in known}
    sm = difflib.SequenceMatcher(None, [w.lower() for w in a], [w.lower() for w in b])
    out: list = []
    seen = set()
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag != "replace":
            continue
        for old, new in zip(a[i1:i2], b[j1:j2]):
            o = old.strip(_PUNCT)
            n = new.strip(_PUNCT)
            if o.lower() not in inserted_words:
                continue   # only learn corrections to words we inserted
            if n.lower() in seen:
                continue
            if _is_learnable(o, n, known_lower, min_ratio):
                out.append(n)
                seen.add(n.lower())
    return out
