# Dashboard Panel + Frequency-Gated Learning — Design

**Date:** 2026-06-16
**Status:** Approved by user (browser HTML panel; all trend groups)
**Extends:** the built app (history, cleanup dictionary, auto-learn).

## Goal

A clickable **Dashboard** (tray → Dashboard) that opens a self-contained, offline HTML
page showing: the dictionary split into **Saved** vs **Auto-added** words; **cost & usage
by day** with trends; and **pending corrections**. Plus a behavior change: a corrected
word is added to the dictionary only after it's been rewritten **more than twice** (3rd
identical rewrite), instead of immediately.

## User decisions (locked)

| Decision | Choice |
|---|---|
| Panel | Offline HTML in the browser (inline charts, no deps) |
| Trends | Cost & volume/day · Time saved · Language split · Top words & averages |
| Cost | Estimated from audio duration × model rate (no billing API) |
| Promotion | Add to dictionary on the 3rd identical rewrite (count > 2) |

## Architecture (small, focused units)

```
app/costs.py        estimate_cost(duration_s, model, cleanup) -> float   (pure)
app/history.py      + cost on each entry; daily_stats(); classify_language(); aggregates
app/learn.py        extract_corrections -> (old,new) pairs; corrections store + promotion
app/dashboard.py    render_dashboard(...) -> str (self-contained HTML)   (pure)
app/__main__.py     wire: cost on append, frequency-gated learn, open_dashboard()
app/tray.py         "Dashboard" menu item
corrections.json    persistent correction counts (gitignored)
config              cleanup.auto_learned: []  ·  learn.promote_after: 2
```

## Cost estimation (`app/costs.py`)

```python
_RATES = {  # USD per minute of audio (transcription)
    "gpt-4o-transcribe": 0.006, "gpt-4o-mini-transcribe": 0.003, "whisper-1": 0.006,
    "whisper-large-v3-turbo": 0.0007, "scribe_v1": 0.0067, "scribe_v2": 0.0067,
}
_DEFAULT_RATE = 0.006
_CLEANUP_FLAT = 0.0002   # ~per gpt-4o-mini cleanup call

def estimate_cost(duration_s, model, cleanup) -> float:
    cost = (duration_s / 60.0) * _RATES.get(model, _DEFAULT_RATE)
    if cleanup:
        cost += _CLEANUP_FLAT
    return round(cost, 6)
```

## History changes (`app/history.py`)

- `append_entry(..., cost=0.0, model="")` — store `cost` and `model` on the entry.
  `App` computes `cost = costs.estimate_cost(duration, transcription_model, cleanup_on)`.
- `daily_stats(entries) -> list[dict]` (sorted by date asc): `{date, dictations, words,
  cost, audio_s}`. Missing `cost` (old entries) is estimated from duration × default rate.
- `classify_language(text) -> "en"|"zh"|"mixed"` from Han/Latin ratio (`zh` if Han-ratio
  > 0.6, `en` if < 0.1, else `mixed`). Used for the language-split trend.
- `word_count`/`stats` already exist; `stats` reused for totals (and gains `cost`).

## Frequency-gated learning (`app/learn.py`)

- `extract_corrections(...)` now returns **`list[(old, new)]`** pairs (was `list[str]`).
- Correction store (JSON): `{ new_lower: {"old","new","count","promoted"} }`.
  - `load_corrections(path) -> dict` / `save_corrections(store, path)`.
  - `bump_corrections(store, pairs)` — increment count per `new` (case-insensitive key).
  - `due_for_promotion(store, threshold=2) -> list[str]` — returns `new` terms with
    `count > threshold` and not yet promoted; marks them `promoted=True`.
- Pure functions (dict/file in/out), fully unit-tested.

### Pipeline wiring (`App._consume_pending_learn`)
1. `pairs = extract_corrections(inserted, snapshot, current, known=set(dictionary))`
   (already-known words are skipped, so promoted words stop being counted).
2. `store = load_corrections(); bump_corrections(store, pairs)`
3. `promoted = due_for_promotion(store, cfg["learn"]["promote_after"])`; `save_corrections`.
4. For each promoted term: append to `cleanup.dictionary` **and** `cleanup.auto_learned`
   (dedup, cap `max_terms`), save config, toast `learned`.

So the 1st/2nd rewrite only increments the counter (shown as "pending" on the dashboard);
the 3rd promotes the word.

## Dashboard (`app/dashboard.py`)

`render_dashboard(entries, dictionary, auto_learned, corrections) -> str` builds one
self-contained HTML page (inline CSS + inline SVG bars; no external requests). Sections:

- **Header tiles:** total dictations · words · estimated cost · time saved.
- **Cost & usage by day:** inline SVG bar charts (last 14 days) for est. cost/day,
  dictations/day, words/day.
- **Trends:** language split (EN/中文/mixed %), avg words per dictation, busiest day,
  total time saved.
- **Dictionary:** two columns — **Saved** (`dictionary` minus `auto_learned`) and
  **Auto-added** (`auto_learned`, each annotated with original→corrected + times seen
  from the corrections store).
- **Pending corrections:** entries in the store with `count <= promote_after` (not yet
  promoted), showing `old → new` and `count/threshold`.

`App.open_dashboard()` writes `dashboard.html` next to history and `os.startfile`s it.
Tray gains a **Dashboard** item (i18n `dashboard`). The existing **Open history**
(transcript search) and **Usage stats** toast remain.

## Config additions
`cleanup.auto_learned: []` (subset of dictionary that was auto-added) and
`learn.promote_after: 2` (promote when a correction count exceeds this).

## Testing
- `costs.estimate_cost`: known model rates, default fallback, cleanup flat add.
- `history.daily_stats`: groups by date, sums words/cost, estimates missing cost.
- `history.classify_language`: en / zh / mixed.
- `learn.extract_corrections`: returns `(old,new)` pairs (existing tests updated).
- `learn.bump_corrections`/`due_for_promotion`: counts increment; promote only when
  `count > threshold`; promoted not re-promoted; round-trip load/save.
- `dashboard.render_dashboard`: contains saved + auto-added words, daily figures, and
  pending corrections; valid self-contained HTML (`<!doctype html>`, no external src).

## Risks
| Risk | Mitigation |
|---|---|
| Cost is an estimate, not the real bill | Labeled "estimated" in the UI; rate table easy to edit. |
| Old history entries lack `cost`/`model` | `daily_stats` estimates missing cost from duration; still useful. |
| corrections.json grows unbounded | Only stores corrected terms; effectively tiny. Dictionary capped by `max_terms`. |
| Behavior change (no longer learns on 1st rewrite) | Intended per user; pending list shows progress; `promote_after` configurable. |
