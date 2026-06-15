import io
import struct
import wave

from app.recorder import raw_to_wav, MIN_DURATION_S, duration_of, compute_level


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


def test_compute_level_empty_and_silence():
    assert compute_level(b"") == 0.0
    assert compute_level(b"\x00\x00" * 1000) == 0.0


def test_compute_level_full_scale_clamps_to_one():
    loud = struct.pack("<" + "h" * 1000, *([32767] * 1000))
    assert compute_level(loud) == 1.0


def test_compute_level_louder_is_higher():
    quiet = struct.pack("<" + "h" * 1000, *([300] * 1000))
    loud = struct.pack("<" + "h" * 1000, *([1200] * 1000))
    lq, ll = compute_level(quiet), compute_level(loud)
    assert 0.0 < lq < ll < 1.0


def test_compute_level_handles_odd_byte_count():
    # a stray trailing byte must not crash
    assert 0.0 <= compute_level(b"\x10\x20\x30") <= 1.0
