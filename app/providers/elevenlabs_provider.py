"""ElevenLabs Scribe speech-to-text (proprietary API, not OpenAI-compatible).

Best published Mandarin accuracy; batch endpoint, which suits push-to-talk dictation.
ElevenLabs has no transcription-biasing prompt, so `prompt` is ignored here — dictionary
biasing is applied in the cleanup pass instead. Output script (Simplified/Traditional)
does not matter: the OpenCC s2twp post-pass guarantees Traditional.
"""
import requests

from .. import net
from .base import TranscriptionError


class ElevenLabsProvider:
    name = "elevenlabs"
    base_url = "https://api.elevenlabs.io/v1"

    def __init__(self, api_key: str, model: str = "scribe_v1"):
        self.api_key = api_key
        self.model = model

    def transcribe(self, wav_bytes: bytes, language: str | None, prompt: str | None) -> str:
        if not self.api_key:
            raise TranscriptionError("API key not configured", retryable=False)
        data = {"model_id": self.model}
        if language:
            data["language_code"] = language  # ISO-639-1 ("en", "zh") accepted
        try:
            resp = net.post(
                f"{self.base_url}/speech-to-text",
                headers={"xi-api-key": self.api_key},
                data=data,
                files={"file": ("audio.wav", wav_bytes, "audio/wav")},
                timeout=60,
            )
        except requests.RequestException as e:
            raise TranscriptionError(str(e), retryable=True) from e
        if resp.status_code == 429 or resp.status_code >= 500:
            raise TranscriptionError(f"HTTP {resp.status_code}: {resp.text[:200]}", retryable=True)
        if resp.status_code != 200:
            raise TranscriptionError(f"HTTP {resp.status_code}: {resp.text[:200]}", retryable=False)
        try:
            return resp.json().get("text", "").strip()
        except ValueError as e:
            raise TranscriptionError(f"bad response: {e}", retryable=False) from e
