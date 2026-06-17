"""Render a self-contained, offline Help page listing everything the app does."""

_CSS = """
 body{font-family:Segoe UI,system-ui,sans-serif;max-width:820px;margin:24px auto;
   padding:0 18px;color:#1c1c20;line-height:1.55}
 h1{font-size:22px;font-weight:600} h2{font-size:16px;margin:26px 0 6px}
 .keys{background:#f5f4f0;border-radius:10px;padding:12px 16px;font-size:14px}
 kbd{background:#fff;border:1px solid #ccc;border-bottom-width:2px;border-radius:5px;
   padding:1px 6px;font-family:Segoe UI,sans-serif;font-size:13px}
 ul{margin:4px 0 0;padding-left:1.2rem} li{margin:3px 0;font-size:14px}
 .muted{color:#777} code{background:#f0eee9;border-radius:4px;padding:1px 5px;font-size:13px}
"""


def _row(keys, desc):
    return f"<li><kbd>{keys}</kbd> — {desc}</li>"


def render_help(hotkey: str, command_hotkey: str) -> str:
    p = ["<!doctype html><html><head><meta charset='utf-8'>",
         "<title>VoiceToText help</title><style>", _CSS, "</style></head><body>",
         "<h1>VoiceToText — what it does</h1>",
         f"<div class='keys'><b>Dictation hotkey:</b> hold <kbd>Win+Ctrl</kbd> "
         f"<span class='muted'>(configured: <code>{hotkey}</code>)</span> &nbsp;·&nbsp; "
         f"<b>Command hotkey:</b> hold <kbd>Win+Alt</kbd> "
         f"<span class='muted'>(configured: <code>{command_hotkey}</code>)</span></div>"]

    p.append("<h2>Dictation</h2><ul>")
    p.append("<li><b>Hold</b> Win+Ctrl, speak, release — text is typed at your cursor "
             "(and left on the clipboard).</li>")
    p.append("<li><b>Tap</b> Win+Ctrl to toggle hands-free recording; tap again to finish.</li>")
    p.append("<li><kbd>Esc</kbd> while recording cancels. Win+Ctrl+←/→ etc. pass through.</li>")
    p.append("<li>A waveform shows while recording; yellow dots while transcribing.</li>")
    p.append("</ul>")

    p.append("<h2>Command mode — edit selected text by voice</h2><ul>")
    p.append("<li>Select text, <b>hold Win+Alt</b> (or tap to start, tap to finish), and "
             "speak an instruction: <i>“make this formal”, “summarize”, “turn into bullet "
             "points”, “translate to English”</i>. The selection is replaced with the "
             "result, and the overlay shows “Applying: …” while it works.</li>")
    p.append("<li>Fix a misheard word by hand, select the corrected text, then hold "
             "Win+Alt and say <i>“correct it”</i> — the app compares it to what it "
             "dictated and adds the fixed word to your dictionary right away.</li>")
    p.append("</ul>")

    p.append("<h2>Snippets &amp; spoken formatting</h2><ul>")
    p.append("<li>Dictate a snippet trigger to expand it (set up <code>snippets</code> in config).</li>")
    p.append("<li>Dictate just “new line” or “new paragraph” to insert a break.</li>")
    p.append("</ul>")

    p.append("<h2>Languages &amp; accuracy</h2><ul>")
    p.append("<li>Speak English or Mandarin — Chinese always comes out as "
             "<b>Traditional</b> characters.</li>")
    p.append("<li>Tray → Language pins Auto / English / 中文.</li>")
    p.append("<li>App-aware tone: casual in chat, formal in email, code-verbatim in editors.</li>")
    p.append("<li>A cleanup pass fixes punctuation, fillers, and self-corrections "
             "(tray → Clean up text; styles light/balanced/heavy).</li>")
    p.append("</ul>")

    p.append("<h2>Providers</h2><ul>")
    p.append("<li>Switch transcription provider in tray → Provider: <b>OpenAI</b> "
             "(gpt-4o-transcribe), <b>ElevenLabs</b> Scribe (best Mandarin), or "
             "<b>Groq</b>. Keys live in <code>config.json</code>.</li>")
    p.append("</ul>")

    p.append("<h2>Dictionary</h2><ul>")
    p.append("<li>Tray → <b>Add word…</b> to add names/jargon live (no restart).</li>")
    p.append("<li>Tray → <b>Remove word</b> to delete any word (auto-added ones are marked).</li>")
    p.append("<li>With auto-learn on (<code>learn.enabled</code>), a corrected word is "
             "added automatically after you've rewritten it more than twice.</li>")
    p.append("</ul>")

    p.append("<h2>Dashboard &amp; history</h2><ul>")
    p.append("<li>Tray → <b>Dashboard</b>: dictionary (saved vs auto-added), cost &amp; "
             "usage by day, trends, and pending corrections.</li>")
    p.append("<li>Tray → <b>Recent</b> re-inserts a past dictation; <b>Usage stats</b> "
             "shows totals; <b>Open history</b> is a searchable log.</li>")
    p.append("</ul>")

    p.append("<h2>Starting, quitting &amp; settings</h2><ul>")
    p.append("<li><b>Start:</b> double-click the Desktop shortcut. <b>Quit:</b> tray → Quit. "
             "<b>Auto-start:</b> tray → Start with Windows.</li>")
    p.append("<li>Tray → <b>Open config</b> edits <code>config.json</code> "
             "(hotkeys, models, silence threshold, snippets, and more).</li>")
    p.append("</ul>")

    p.append("</body></html>")
    return "".join(p)
