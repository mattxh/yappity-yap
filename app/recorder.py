"""Microphone capture at 16 kHz mono int16 via sounddevice (no numpy)."""
import array
import io
import logging
import threading
import wave

log = logging.getLogger(__name__)

SAMPLERATE = 16000
MIN_DURATION_S = 0.3
_LEVEL_GAIN = 2500.0  # RMS divisor → ~0..1; lower = more sensitive


def compute_level(raw: bytes, gain: float = _LEVEL_GAIN) -> float:
    """Return a 0..1 loudness estimate (RMS) for int16 mono PCM bytes.

    Subsamples to stay cheap enough for the audio callback thread. No numpy
    (and Python 3.13+ removed audioop), so RMS is computed directly.
    """
    usable = len(raw) - (len(raw) % 2)
    if usable <= 0:
        return 0.0
    samples = array.array("h")
    samples.frombytes(raw[:usable])
    n = len(samples)
    step = max(1, n // 200)
    total = 0
    count = 0
    for i in range(0, n, step):
        v = samples[i]
        total += v * v
        count += 1
    rms = (total / count) ** 0.5
    # sqrt curve boosts quiet/moderate speech so the meter visibly moves
    # instead of hugging the floor until you shout.
    return min(1.0, (rms / gain) ** 0.5)


def raw_to_wav(raw: bytes, samplerate: int = SAMPLERATE) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(samplerate)
        w.writeframes(raw)
    return buf.getvalue()


def duration_of(raw: bytes, samplerate: int = SAMPLERATE) -> float:
    return len(raw) / (samplerate * 2)


class MicError(Exception):
    pass


class Recorder:
    def __init__(self, device=None, silence_threshold: float = 0.0):
        self.device = device
        self.silence_threshold = silence_threshold
        self._stream = None
        self._buf = bytearray()
        self._lock = threading.Lock()
        self._level = 0.0   # live loudness 0..1, updated on the audio thread
        self._peak = 0.0    # max level seen during the current take

    def level(self) -> float:
        """Current input loudness (0..1). Read by the overlay's waveform."""
        return self._level

    def start(self):
        import sounddevice as sd

        with self._lock:
            self._buf = bytearray()
            self._peak = 0.0

        def callback(indata, frames, time_info, status):
            if status:
                log.warning("audio status: %s", status)
            data = bytes(indata)
            with self._lock:
                self._buf.extend(data)
            lvl = compute_level(data)
            self._level = lvl
            if lvl > self._peak:
                self._peak = lvl

        try:
            self._stream = sd.RawInputStream(
                samplerate=SAMPLERATE, channels=1, dtype="int16",
                device=self.device, callback=callback,
            )
            self._stream.start()
        except Exception as e:
            self._stream = None
            raise MicError(str(e)) from e

    def stop(self) -> bytes | None:
        """Stop and return WAV bytes, or None if too short or too quiet to be speech."""
        peak = self._peak
        raw = self._close()
        if duration_of(raw) < MIN_DURATION_S:
            return None
        if peak < self.silence_threshold:
            return None
        return raw_to_wav(raw)

    def cancel(self):
        self._close()

    def is_active(self) -> bool:
        return self._stream is not None

    def _close(self) -> bytes:
        # Swap out stream+buffer atomically under the lock so concurrent
        # stop/cancel calls from different threads can't double-close.
        with self._lock:
            self._level = 0.0
            self._peak = 0.0
            stream, self._stream = self._stream, None
            raw, self._buf = bytes(self._buf), bytearray()
        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except Exception:
                log.exception("closing stream")
        return raw


def list_devices() -> str:
    import sounddevice as sd

    return str(sd.query_devices())
