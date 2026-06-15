import json

from app.history import append_entry


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
