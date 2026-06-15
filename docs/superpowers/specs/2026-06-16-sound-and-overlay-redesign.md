# Sound + Overlay Redesign — Design

**Date:** 2026-06-16
**Status:** Approved by user (mockup direction chosen: Glass pill + soft two-note chime)
**Files:** `app/notify.py` (sound), `app/overlay.py` (status pill)

## Goal

Replace the harsh `winsound.Beep` square-wave cues with calm, synthesized sine-tone
chimes, and replace the flat rectangular tkinter overlay with a sleek rounded "glass
pill". No new dependencies (stdlib `wave`/`struct`/`math`/`winsound`, existing tkinter).

## Sound (`app/notify.py`)

- `winsound.Beep` is a pure square wave (harsh edges) — the source of the "sharp" feel.
- Replace with **synthesized 16-bit PCM mono WAV** tones played via
  `winsound.PlaySound(data, SND_MEMORY | SND_ASYNC | SND_NODEFAULT)` (non-blocking;
  no helper thread needed).
- Pure synth function `synth_wav(segments, samplerate=44100, volume=0.30, fade_ms=12)`
  where `segments = [(freq_hz, dur_s), ...]`. Each segment is a sine wave with a linear
  **fade-in/out envelope** (`fade_ms` each side) so there is no click/attack transient —
  this is what makes it calm.
- Two-note chime palette (warm, gentle):
  - `start`: rising C5→E5 `[(523.25, 0.085), (659.25, 0.085)]`
  - `stop`: falling E5→C5 `[(659.25, 0.085), (523.25, 0.085)]`
  - `cancel`: soft falling A4→G4 `[(440.0, 0.07), (392.0, 0.11)]`
  - `error`: low gentle D4 double `[(293.66, 0.10), (293.66, 0.14)]`
- WAVs precomputed once at import into `CUES: dict[str, bytes]`.
- `beep(kind: str, enabled: bool = True)` signature unchanged (callers in `__main__`
  untouched). On unknown kind or playback failure, fail silently (log debug).

### Tests (`tests/test_notify.py`)
- `synth_wav` returns valid WAV (wave module: 1 channel, 2-byte samples, 44100 Hz,
  nframes ≈ sum(durations)·44100).
- Envelope applied: first frame ≈ 0 (fade-in), a mid frame is non-trivially large.
- Samples stay within int16 range.
- `CUES` has keys `start`, `stop`, `cancel`, `error`, each non-empty `bytes`.
- `beep("start", enabled=False)` plays nothing (monkeypatch `winsound.PlaySound`,
  assert not called); `beep("start", True)` calls PlaySound once with the cue bytes.

## Overlay (`app/overlay.py`) — Glass pill

Keep the existing architecture (own tkinter thread, queue-driven commands, click-through
`WS_EX_NOACTIVATE | WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW` ex-styles, `NullOverlay`
fallback). Replace only the look:

- **Rounded translucent pill:** `overrideredirect` window with a Canvas; window
  `-transparentcolor` set to a key color (`#FF00FF`) so the area outside the pill is
  fully transparent → true rounded corners. Pill drawn as a rounded rectangle
  (smoothed polygon) in near-black `#1c1c20` with a 1px hairline border `#3a3a40`.
  `-alpha 0.96` for a faint translucency.
- **Contents:** a status indicator + main label + a dimmer hint.
  - recording: a **minimal audio-reactive waveform** — 6 thin coral `#f4796f` bars
    whose heights follow the live mic loudness, with a center-weighted shape profile and
    a small per-bar wiggle so it looks organic. Label "Recording", hint "Esc to cancel".
  - transcribing: a softly pulsing amber dot `#f0a83a`, label "Transcribing…", no hint.
- **Audio reactivity:** `Recorder.compute_level()` derives a 0..1 RMS loudness from each
  audio chunk on the capture thread (no numpy; Python 3.13+ removed `audioop`, so RMS is
  computed directly via `array`). `Recorder.level()` exposes it; the overlay is given
  this as a `level_source` callable and pulls it each frame. A `root.after(33ms)` loop
  (~30fps) eases the value toward the target (smoothing jitter) and maps it to bar
  heights; the transcribing dot interpolates its fill toward a dimmed shade. If no
  `level_source` is provided, bars fall back to a gentle sine loop.
- **DPI-aware & crisp:** the process is made per-monitor DPI-aware in `__main__`
  (`SetProcessDpiAwareness`), and the overlay scales every dimension and font by the
  display DPI factor (`winfo_fpixels('1i')/96`). Without this, tkinter renders at logical
  resolution and Windows bitmap-stretches it on scaled displays (e.g. 150%) → blurry.
- **Sizing:** width measured from text via `tkinter.font.Font.measure`; pill height
  fixed (~40px); positioned bottom-center (existing logic).
- Localized strings keep coming from `i18n.tr` (existing `recording`/`transcribing`
  keys), so the hint text adapts to UI language. The "Recording — Esc to cancel" key
  already contains the hint; the pill renders label and hint together.

### Verification
- Overlay is a UI shim (no unit tests, matching the original). Verify with a **screenshot
  harness**: a short script creates the overlay, shows the recording then transcribing
  state, captures the screen via `PIL.ImageGrab`, saves PNGs; review them. Plus the
  existing launch smoke test (no crash) and full pytest suite stays green.

## Risks
| Risk | Mitigation |
|---|---|
| `-transparentcolor` corner aliasing looks rough | Acceptable; still far sleeker than a rectangle. Pill color avoids the key color. |
| tkinter Canvas can't do true alpha on the dot | Pulse via color interpolation toward bg, not real alpha — visually equivalent. |
| Screenshot harness can't run headless | It's local on the user's desktop session; if it fails, fall back to launch smoke + user confirmation. |
