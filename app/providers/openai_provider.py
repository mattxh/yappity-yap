"""OpenAI-compatible /audio/transcriptions client (plain requests)."""
import requests

from .base import TranscriptionError


class OpenAIProvider:
    name = "openai"
    base_url = "https://api.openai.com/v1"

    def __init__(self, api_key: str, model: str = "gpt-4o-transcribe"):
        self.api_key = api_key
        self.model = model

    def transcribe(self, wav_bytes: bytes, language: str | None, prompt: str | None) -> str:
        if not self.api_key:
            raise TranscriptionError("API key not configured", retryable=False)
        data = {"model": self.model, "response_format": "json"}
        if language:
            data["language"] = language
        if prompt:
            data["prompt"] = prompt
        try:
            resp = requests.post(
                f"{self.base_url}/audio/transcriptions",
                headers={"Authorization": f"Bearer {self.api_key}"},
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
        return resp.json().get("text", "").strip()
