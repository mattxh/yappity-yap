import io
import wave

from app.recorder import raw_to_wav, MIN_DURATION_S, duration_of


def test_raw_to_wav_header_and_payload():
    raw = b"\x00\x01" * 16000  # 1 second of 16 kHz mono int16
    wav_bytes = raw_to_wav(raw, samplerate=16000)
    with wave.open(io.BytesIO(wav_bytes)) as w:
        assert w.getnchannels() == 1
        assert w.getsampwidth() == 2
        assert w.getframerate() == 16000
        assert w.getnframes() == 16000
        assert w.readframes(2) == b"\x00\x01\x00\x01"


def test_duration_of():
    assert duration_of(b"\x00" * 32000, 16000) == 1.0


def test_min_duration_constant():
    assert MIN_DURATION_S == 0.3
