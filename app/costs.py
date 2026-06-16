"""Estimate per-dictation cost from audio duration and model.

There's no billing API, so this is an estimate: transcription is priced per minute
of audio, plus a small flat cost when the cleanup pass runs. Rates in USD; easy to
edit as pricing changes.
"""

_RATES = {  # USD per minute of audio (transcription)
    "gpt-4o-transcribe": 0.006,
    "gpt-4o-mini-transcribe": 0.003,
    "whisper-1": 0.006,
    "whisper-large-v3-turbo": 0.0007,   # Groq, approx
    "scribe_v1": 0.0067,                # ElevenLabs ~$0.40/hr
    "scribe_v2": 0.0067,
}
DEFAULT_RATE = 0.006
CLEANUP_FLAT = 0.0002   # ~per gpt-4o-mini cleanup call


def estimate_cost(duration_s: float, model: str, cleanup: bool) -> float:
    cost = (duration_s / 60.0) * _RATES.get(model, DEFAULT_RATE)
    if cleanup:
        cost += CLEANUP_FLAT
    return round(cost, 6)
