"""Append-only dictation history (history.jsonl) + read/stats/HTML helpers."""
import datetime
import json
import logging
import re
from pathlib import Path

from . import config as _config

log = logging.getLogger(__name__)

HISTORY_PATH = _config.data_dir() / "history.jsonl"

_LATIN_WORD = re.compile(r"[A-Za-z0-9]+")
_LATIN_CH = re.compile(r"[A-Za-z]")
_CJK = re.compile(r"[一-鿿㐀-䶿豈-﫿]")


def append_entry(path: Path, lang: str, duration_s: float, text: str,
                 cost: float = 0.0, model: str = "") -> None:
    entry = {
        "ts": datetime.datetime.now().isoformat(timespec="seconds"),
        "lang": lang,
        "duration_s": round(duration_s, 2),
        "chars": len(text),
        "text": text,
        "cost": round(cost, 6),
        "model": model,
    }
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        log.exception("history append failed")


def read_entries(path) -> list:
    """All history entries in file order (oldest first); [] if missing/empty."""
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError):
        return []
    out = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def tail(path, n: int) -> list:
    """The n most-recent entries, newest first."""
    return list(reversed(read_entries(path)))[:n]


def word_count(text: str) -> int:
    """Latin words (whitespace tokens with letters/digits) + CJK chars individually."""
    return len(_LATIN_WORD.findall(text)) + len(_CJK.findall(text))


def _entry_cost(entry: dict) -> float:
    cost = entry.get("cost")
    if cost is None:
        from . import costs
        cost = costs.estimate_cost(float(entry.get("duration_s", 0) or 0),
                                   entry.get("model", ""), cleanup=False)
    return float(cost or 0)


def stats(entries: list) -> dict:
    words = sum(word_count(e.get("text", "")) for e in entries)
    seconds = sum(float(e.get("duration_s", 0) or 0) for e in entries)
    typing_min = words / 40.0          # ~40 wpm typing baseline
    saved_min = typing_min - seconds / 60.0
    return {
        "dictations": len(entries),
        "words": words,
        "audio_seconds": round(seconds, 1),
        "time_saved_min": round(saved_min, 1),
        "cost": round(sum(_entry_cost(e) for e in entries), 4),
    }


def classify_language(text: str) -> str:
    """Rough content language: 'zh', 'en', or 'mixed' (for the language-split trend)."""
    han = len(_CJK.findall(text))
    latin = len(_LATIN_CH.findall(text))
    base = han + latin
    if base == 0:
        return "en"
    ratio = han / base
    if ratio > 0.6:
        return "zh"
    if ratio < 0.1:
        return "en"
    return "mixed"


def daily_stats(entries: list) -> list:
    """Per-day {date, dictations, words, cost, audio_s}, sorted by date ascending."""
    by_date: dict = {}
    for e in entries:
        date = (e.get("ts") or "")[:10]
        if not date:
            continue
        d = by_date.setdefault(date, {"date": date, "dictations": 0, "words": 0,
                                      "cost": 0.0, "audio_s": 0.0})
        d["dictations"] += 1
        d["words"] += word_count(e.get("text", ""))
        d["audio_s"] += float(e.get("duration_s", 0) or 0)
        d["cost"] += _entry_cost(e)
    return [by_date[k] for k in sorted(by_date)]


def render_html(entries: list) -> str:
    """A self-contained, searchable history page (newest first)."""
    data = json.dumps(list(reversed(entries)), ensure_ascii=False).replace("</", "<\\/")
    s = stats(entries)
    return _HTML_TEMPLATE.format(
        data=data,
        dictations=s["dictations"],
        words=s["words"],
        saved=s["time_saved_min"],
    )


_HTML_TEMPLATE = """<!doctype html>
<html><head><meta charset="utf-8"><title>Yappity Yapp history</title>
<style>
 body{{font-family:Segoe UI,system-ui,sans-serif;max-width:820px;margin:24px auto;padding:0 16px;color:#1c1c20}}
 h1{{font-size:20px;font-weight:600}}
 .stat{{color:#555;font-size:13px;margin-bottom:14px}}
 #q{{width:100%;padding:10px 12px;font-size:15px;border:1px solid #ccc;border-radius:10px;box-sizing:border-box}}
 .row{{border:1px solid #eee;border-radius:10px;padding:10px 12px;margin:10px 0}}
 .meta{{color:#888;font-size:12px;display:flex;justify-content:space-between}}
 .txt{{margin-top:6px;white-space:pre-wrap}}
 button{{font-size:12px;border:1px solid #ccc;background:#fff;border-radius:7px;padding:3px 9px;cursor:pointer}}
</style></head><body>
<h1>Yappity Yapp history</h1>
<div class="stat">{dictations} dictations · {words} words · ~{saved} min saved</div>
<input id="q" placeholder="Search…" oninput="render()">
<div id="list"></div>
<script>
const DATA = {data};
const list = document.getElementById('q');
function esc(s){{const d=document.createElement('div');d.textContent=s;return d.innerHTML;}}
function render(){{
  const q = document.getElementById('q').value.toLowerCase();
  const box = document.getElementById('list');
  box.innerHTML = '';
  for (const e of DATA){{
    if (q && !(e.text||'').toLowerCase().includes(q)) continue;
    const row = document.createElement('div'); row.className='row';
    row.innerHTML = '<div class="meta"><span>'+esc(e.ts||'')+' · '+esc(e.lang||'')+
      '</span><button>Copy</button></div><div class="txt">'+esc(e.text||'')+'</div>';
    row.querySelector('button').onclick = () => navigator.clipboard.writeText(e.text||'');
    box.appendChild(row);
  }}
}}
render();
</script></body></html>
"""
