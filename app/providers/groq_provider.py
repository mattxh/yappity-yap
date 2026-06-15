"""Groq: same wire format as OpenAI, different host/model."""
from .openai_provider import OpenAIProvider


class GroqProvider(OpenAIProvider):
    name = "groq"
    base_url = "https://api.groq.com/openai/v1"

    def __init__(self, api_key: str, model: str = "whisper-large-v3-turbo"):
        super().__init__(api_key=api_key, model=model)
