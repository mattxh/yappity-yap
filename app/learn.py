"""Pure correction-detection core for the auto-learning dictionary.

Given the text we inserted, the field's text right after paste, and the field's text
later, find words the user *corrected* (a similar-but-different replacement of one of
our words) — biased toward names/jargon, guarded against junk.
"""
import difflib
import json
import re
from pathlib import Path

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
    """Return (old, new) correction pairs the user made to words we inserted."""
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
                out.append((o, n))
                seen.add(n.lower())
    return out


# -- correction-frequency store (promote to dictionary after N rewrites) ------

def load_corrections(path) -> dict:
    try:
        store = json.loads(Path(path).read_text(encoding="utf-8"))
        return store if isinstance(store, dict) else {}
    except (OSError, ValueError):
        return {}


def save_corrections(store: dict, path) -> None:
    try:
        Path(path).write_text(json.dumps(store, ensure_ascii=False, indent=2),
                              encoding="utf-8")
    except OSError:
        pass


def bump_corrections(store: dict, pairs) -> None:
    """Increment the seen-count for each (old, new) correction (keyed by new)."""
    for old, new in pairs:
        key = new.lower()
        entry = store.get(key) or {"old": old, "new": new, "count": 0, "promoted": False}
        entry["old"] = old
        entry["new"] = new
        entry["count"] = entry.get("count", 0) + 1
        store[key] = entry


def due_for_promotion(store: dict, threshold: int = 2) -> list:
    """Return new terms whose count now exceeds `threshold` and mark them promoted."""
    promoted = []
    for entry in store.values():
        if not entry.get("promoted") and entry.get("count", 0) > threshold:
            entry["promoted"] = True
            promoted.append(entry["new"])
    return promoted
