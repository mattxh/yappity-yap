"""Calm synthesized sound cues and toast notifications.

Replaces winsound.Beep (a harsh square wave) with soft sine-tone chimes that have a
short fade-in/out envelope, so there is no sharp attack click. Tones are precomputed
16-bit PCM mono WAVs played with winsound.PlaySound(SND_MEMORY) — non-blocking.
"""
import io
import logging
import math
import struct
import threading
import wave
import winsound

log = logging.getLogger(__name__)

SAMPLERATE = 44100

# Two-note chimes (freq Hz, duration s). Lower register + quieter than before for a
# softer, more muted feel. Rising = start, falling = stop, etc.
_CHIMES = {
    "start": [(392.00, 0.10), (523.25, 0.10)],     # G4 -> C5, soft rise
    "stop": [(523.25, 0.10), (392.00, 0.10)],      # C5 -> G4, soft fall
    "cancel": [(392.00, 0.08), (329.63, 0.12)],    # G4 -> E4, soft dismiss
    "error": [(293.66, 0.12), (293.66, 0.16)],     # D4 x2, low and calm
}


def synth_wav(segments, samplerate: int = SAMPLERATE,
              volume: float = 0.18, fade_ms: int = 24) -> bytes:
    """Render a sequence of (freq_hz, duration_s) sine segments to WAV bytes.

    Each segment gets a linear fade-in/out (fade_ms per side) to avoid click
    transients — this is what makes the cue sound soft rather than sharp.
    """
    amp = int(volume * 32767)
    fade_n = max(1, int(samplerate * fade_ms / 1000))
    frames = bytearray()
    for freq, dur in segments:
        n = int(samplerate * dur)
        for i in range(n):
            env = 1.0
            if i < fade_n:
                env = i / fade_n
            elif i > n - fade_n:
                env = max(0.0, (n - i) / fade_n)
            sample = int(amp * env * math.sin(2 * math.pi * freq * i / samplerate))
            frames += struct.pack("<h", sample)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(samplerate)
        w.writeframes(bytes(frames))
    return buf.getvalue()


CUES = {kind: synth_wav(segs) for kind, segs in _CHIMES.items()}


def _play(data: bytes):
    """Play WAV bytes on a daemon thread. winsound cannot play from memory
    asynchronously (SND_MEMORY | SND_ASYNC raises), so we play synchronously
    off-thread to avoid blocking the caller."""
    def run():
        try:
            winsound.PlaySound(data, winsound.SND_MEMORY | winsound.SND_NODEFAULT)
        except Exception:
            log.debug("sound cue failed", exc_info=True)

    t = threading.Thread(target=run, daemon=True, name="beep")
    t.start()
    return t


def beep(kind: str, enabled: bool = True):
    if not enabled:
        return
    data = CUES.get(kind)
    if data:
        _play(data)


class Notifier:
    """Toast notifications; falls back to log if tray isn't up yet."""

    def __init__(self):
        self._sink = None  # set by tray: callable(message, title)

    def set_sink(self, sink):
        self._sink = sink

    def toast(self, message: str, title: str = "VoiceToText"):
        log.info("notify: %s", message)
        if self._sink is not None:
            try:
                self._sink(message, title)
            except Exception:
                log.debug("toast failed", exc_info=True)
