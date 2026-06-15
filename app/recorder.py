"""Microphone capture at 16 kHz mono int16 via sounddevice (no numpy)."""
import io
import logging
import threading
import wave

log = logging.getLogger(__name__)

SAMPLERATE = 16000
MIN_DURATION_S = 0.3


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
    def __init__(self, device=None):
        self.device = device
        self._stream = None
        self._buf = bytearray()
        self._lock = threading.Lock()

    def start(self):
        import sounddevice as sd

        with self._lock:
            self._buf = bytearray()

        def callback(indata, frames, time_info, status):
            if status:
                log.warning("audio status: %s", status)
            with self._lock:
                self._buf.extend(bytes(indata))

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
        """Stop and return WAV bytes, or None if too short to be speech."""
        raw = self._close()
        if duration_of(raw) < MIN_DURATION_S:
            return None
        return raw_to_wav(raw)

    def cancel(self):
        self._close()

    def is_active(self) -> bool:
        return self._stream is not None

    def _close(self) -> bytes:
        stream, self._stream = self._stream, None
        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except Exception:
                log.exception("closing stream")
        with self._lock:
            raw, self._buf = bytes(self._buf), bytearray()
        return raw


def list_devices() -> str:
    import sounddevice as sd

    return str(sd.query_devices())
