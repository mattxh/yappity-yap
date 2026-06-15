"""Provider protocol and error type."""
from typing import Protocol


class TranscriptionError(Exception):
    def __init__(self, message: str, retryable: bool = False):
        super().__init__(message)
        self.retryable = retryable


class TranscriptionProvider(Protocol):
    name: str

    def transcribe(self, wav_bytes: bytes, language: str | None, prompt: str | None) -> str:
        """Return transcript text. Raise TranscriptionError on failure."""
        ...
