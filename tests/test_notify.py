import io
import struct
import wave

from app import notify
from app.notify import CUES, synth_wav


def _frames(wav_bytes):
    with wave.open(io.BytesIO(wav_bytes)) as w:
        assert w.getnchannels() == 1
        assert w.getsampwidth() == 2
        assert w.getframerate() == 44100
        n = w.getnframes()
        raw = w.readframes(n)
    samples = struct.unpack("<" + "h" * n, raw)
    return samples


def test_synth_wav_is_valid_and_right_length():
    wav = synth_wav([(523.25, 0.05), (659.25, 0.05)])
    samples = _frames(wav)
    expected = int(44100 * 0.10)
    assert abs(len(samples) - expected) <= 2  # ~0.1s total


def test_envelope_fades_in_from_silence():
    wav = synth_wav([(523.25, 0.1)], fade_ms=12)
    samples = _frames(wav)
    assert abs(samples[0]) < 200            # starts near silence (fade-in)
    mid = samples[len(samples) // 2]
    assert abs(mid) > 1000                   # body of the tone is audible


def test_samples_within_int16_range():
    wav = synth_wav([(440.0, 0.08)], volume=0.9)
    samples = _frames(wav)
    assert max(samples) <= 32767
    assert min(samples) >= -32768


def test_cues_present_and_nonempty():
    for kind in ("start", "stop", "cancel", "error"):
        assert kind in CUES
        assert isinstance(CUES[kind], bytes) and len(CUES[kind]) > 44  # header + data


def test_beep_disabled_plays_nothing(monkeypatch):
    calls = []
    monkeypatch.setattr(notify.winsound, "PlaySound", lambda *a, **k: calls.append(a))
    notify.beep("start", enabled=False)
    assert calls == []


def test_beep_enabled_plays_cue_bytes(monkeypatch):
    calls = []
    monkeypatch.setattr(notify.winsound, "PlaySound", lambda *a, **k: calls.append(a))
    notify.beep("start", enabled=True)
    assert len(calls) == 1
    assert calls[0][0] == CUES["start"]      # plays the precomputed cue


def test_beep_unknown_kind_is_silent(monkeypatch):
    calls = []
    monkeypatch.setattr(notify.winsound, "PlaySound", lambda *a, **k: calls.append(a))
    notify.beep("nonexistent", enabled=True)
    assert calls == []
