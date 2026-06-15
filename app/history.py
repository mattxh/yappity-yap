"""Append-only dictation history (history.jsonl)."""
import datetime
import json
import logging
from pathlib import Path

log = logging.getLogger(__name__)

HISTORY_PATH = Path(__file__).resolve().parent.parent / "history.jsonl"


def append_entry(path: Path, lang: str, duration_s: float, text: str) -> None:
    entry = {
        "ts": datetime.datetime.now().isoformat(timespec="seconds"),
        "lang": lang,
        "duration_s": round(duration_s, 2),
        "chars": len(text),
        "text": text,
    }
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        log.exception("history append failed")
