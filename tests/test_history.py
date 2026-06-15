import json

from app.history import append_entry, tail, stats, render_html, word_count


def test_append_creates_file_and_appends(tmp_path):
    p = tmp_path / "history.jsonl"
    append_entry(p, lang="auto", duration_s=2.5, text="hello world")
    append_entry(p, lang="zh", duration_s=1.0, text="你好")
    lines = p.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    first = json.loads(lines[0])
    assert first["text"] == "hello world"
    assert first["chars"] == 11
    assert first["duration_s"] == 2.5
    assert "ts" in first
    second = json.loads(lines[1])
    assert second["text"] == "你好"  # unicode preserved, not \u escaped
    assert "你好" in lines[1]


def test_append_never_raises(tmp_path):
    # unwritable target (a directory) must not crash the pipeline
    append_entry(tmp_path, lang="en", duration_s=1.0, text="x")


def test_tail_returns_newest_first(tmp_path):
    p = tmp_path / "history.jsonl"
    for i in range(5):
        append_entry(p, lang="en", duration_s=1.0, text=f"entry {i}")
    last2 = tail(p, 2)
    assert [e["text"] for e in last2] == ["entry 4", "entry 3"]


def test_tail_missing_file_is_empty(tmp_path):
    assert tail(tmp_path / "nope.jsonl", 5) == []


def test_word_count_latin_and_cjk():
    assert word_count("hello world") == 2
    assert word_count("你好世界") == 4           # CJK counted per character
    assert word_count("hello 你好") == 3          # 1 latin word + 2 CJK


def test_stats_totals(tmp_path):
    p = tmp_path / "history.jsonl"
    append_entry(p, lang="en", duration_s=2.0, text="one two three")
    append_entry(p, lang="zh", duration_s=1.0, text="你好")
    s = stats(tail(p, 100))
    assert s["dictations"] == 2
    assert s["words"] == 5            # 3 + 2
    assert s["audio_seconds"] == 3.0
    assert "time_saved_min" in s


def test_render_html_contains_search_and_text():
    entries = [{"ts": "t", "lang": "en", "duration_s": 1, "chars": 10, "text": "hello note"}]
    html = render_html(entries)
    assert 'id="q"' in html               # search input present
    assert "hello note" in html           # data embedded for the viewer


def test_render_html_neutralizes_script_close():
    # embedded data must not be able to break out of the <script> tag
    entries = [{"ts": "t", "lang": "en", "duration_s": 1, "chars": 1,
                "text": "</script><b>x"}]
    html = render_html(entries)
    assert "</script><b>x" not in html    # the raw closing tag is neutralized
