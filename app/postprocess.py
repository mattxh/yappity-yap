"""Guarantee Traditional Chinese output and apply trailing-space rule."""
import re

from opencc import OpenCC

_cc = OpenCC("s2twp")  # Simplified -> Traditional with Taiwan phrasing

# CJK Unified Ideographs (+ExtA, compat) — presence triggers conversion.
_HAN_RE = re.compile(r"[㐀-䶿一-鿿豈-﫿]")
# Characters after which a trailing space makes no sense.
_NO_SPACE_AFTER = "。，、；：？！「」『』（）…—"


def to_traditional(text: str) -> str:
    if _HAN_RE.search(text):
        return _cc.convert(text)
    return text


def apply_spacing(text: str, append_space: bool) -> str:
    text = text.strip()
    if not text or not append_space:
        return text
    last = text[-1]
    if _HAN_RE.match(last) or last in _NO_SPACE_AFTER:
        return text
    return text + " "


def process(text: str, append_space: bool) -> str:
    return apply_spacing(to_traditional(text), append_space)
