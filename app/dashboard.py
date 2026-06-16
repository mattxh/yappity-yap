"""Render the usage/dictionary dashboard as a self-contained, offline HTML page."""
import html as _html

from . import history

_CSS = """
 body{font-family:Segoe UI,system-ui,sans-serif;max-width:860px;margin:24px auto;
   padding:0 16px;color:#1c1c20}
 h1{font-size:22px;font-weight:600} h2{font-size:17px;margin-top:28px}
 h3{font-size:14px;color:#555;margin:0 0 8px}
 .tiles{display:flex;gap:12px;flex-wrap:wrap;margin-top:8px}
 .tile{flex:1;min-width:120px;background:#f5f4f0;border-radius:12px;padding:14px 16px}
 .tile .v{font-size:24px;font-weight:600} .tile .l{font-size:12px;color:#777}
 .note{color:#999;font-size:12px} .empty{color:#999;font-size:13px}
 table{border-collapse:collapse;width:100%;font-size:13px}
 th,td{text-align:left;padding:6px 8px;border-bottom:1px solid #eee}
 th{color:#888;font-weight:500}
 .bar{display:inline-block;width:90px;height:8px;background:#eee;border-radius:4px;
   overflow:hidden;vertical-align:middle;margin-left:6px}
 .bar .fill{height:100%}
 .cols{display:flex;gap:24px;flex-wrap:wrap} .cols>div{flex:1;min-width:220px}
 .chip{display:inline-block;background:#eef;border-radius:7px;padding:3px 9px;
   margin:0 6px 6px 0;font-size:13px}
 .chip.auto{background:#fdf0dc} .cnt{color:#999;font-size:11px}
 ul.trends{font-size:13px;line-height:1.8;color:#333}
"""


def _esc(s):
    return _html.escape(str(s))


def _tile(label, value):
    return f"<div class='tile'><div class='v'>{_esc(value)}</div><div class='l'>{_esc(label)}</div></div>"


def _bar(value, maxv, color):
    pct = (value / maxv * 100) if maxv else 0
    return (f"<span class='bar'><span class='fill' style='width:{pct:.0f}%;"
            f"background:{color}'></span></span>")


def render_dashboard(entries, dictionary, auto_learned, corrections, promote_after=2):
    st = history.stats(entries)
    days = history.daily_stats(entries)[-14:]
    counts = {"en": 0, "zh": 0, "mixed": 0}
    for e in entries:
        counts[history.classify_language(e.get("text", ""))] += 1
    total = sum(counts.values()) or 1
    auto_set = {w.lower() for w in auto_learned}
    saved = [w for w in dictionary if w.lower() not in auto_set]
    corr_count = {e["new"].lower(): e.get("count", 0) for e in corrections.values()}
    pending = sorted((e for e in corrections.values() if not e.get("promoted")),
                     key=lambda x: -x.get("count", 0))
    avg_words = (st["words"] / st["dictations"]) if st["dictations"] else 0
    busiest = max(days, key=lambda d: d["dictations"], default=None)

    p = ["<!doctype html><html><head><meta charset='utf-8'>",
         "<title>VoiceToText dashboard</title><style>", _CSS, "</style></head><body>",
         "<h1>VoiceToText dashboard</h1>",
         "<div class='tiles'>",
         _tile("dictations", st["dictations"]),
         _tile("words", st["words"]),
         _tile("est. cost", f"${st['cost']:.2f}"),
         _tile("time saved", f"{st['time_saved_min']:.0f} min"),
         "</div>",
         "<p class='note'>Cost is an estimate (audio minutes × model rate), "
         "not your actual bill.</p>"]

    p.append("<h2>By day</h2>")
    if days:
        maxcost = max((d["cost"] for d in days), default=0)
        p.append("<table><tr><th>Date</th><th>Dictations</th><th>Words</th>"
                 "<th>Est. cost</th></tr>")
        for d in days:
            p.append(f"<tr><td>{_esc(d['date'])}</td><td>{d['dictations']}</td>"
                     f"<td>{d['words']}</td><td>${d['cost']:.3f}"
                     f"{_bar(d['cost'], maxcost, '#e67e22')}</td></tr>")
        p.append("</table>")
    else:
        p.append("<p class='empty'>No dictations yet.</p>")

    p.append("<h2>Trends</h2><ul class='trends'>")
    p.append(f"<li>Language: English {counts['en'] * 100 // total}% · "
             f"Mandarin {counts['zh'] * 100 // total}% · "
             f"Mixed {counts['mixed'] * 100 // total}%</li>")
    p.append(f"<li>Average {avg_words:.1f} words per dictation</li>")
    if busiest:
        p.append(f"<li>Busiest day: {_esc(busiest['date'])} "
                 f"({busiest['dictations']} dictations)</li>")
    p.append("</ul>")

    p.append("<h2>Dictionary</h2><div class='cols'>")
    saved_html = "".join(f"<span class='chip'>{_esc(w)}</span>" for w in saved)
    p.append("<div><h3>Saved</h3>" + (saved_html or "<p class='empty'>None yet.</p>") + "</div>")
    auto_html = "".join(
        f"<span class='chip auto'>{_esc(w)} <span class='cnt'>×{corr_count.get(w.lower(), '')}</span></span>"
        for w in auto_learned)
    p.append("<div><h3>Auto-added</h3>" + (auto_html or "<p class='empty'>None yet.</p>") + "</div>")
    p.append("</div>")

    p.append("<h2>Pending corrections</h2>")
    if pending:
        p.append("<table><tr><th>Rewrite</th><th>Seen</th></tr>")
        for e in pending:
            p.append(f"<tr><td>{_esc(e['old'])} → {_esc(e['new'])}</td>"
                     f"<td>{e['count']} / {promote_after + 1}</td></tr>")
        p.append("</table>")
    else:
        p.append(f"<p class='empty'>None — a word is added after being rewritten "
                 f"more than {promote_after} times.</p>")

    p.append("</body></html>")
    return "".join(p)
