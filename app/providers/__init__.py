"""Provider factory."""
from ..config import get_api_key
from .elevenlabs_provider import ElevenLabsProvider
from .groq_provider import GroqProvider
from .openai_provider import OpenAIProvider

_PROVIDERS = {
    "openai": OpenAIProvider,
    "groq": GroqProvider,
    "elevenlabs": ElevenLabsProvider,
}


def create_provider(cfg: dict):
    name = cfg.get("provider", "openai")
    cls = _PROVIDERS.get(name)
    if cls is None:
        raise ValueError(f"Unknown provider {name!r}. Available: {sorted(_PROVIDERS)}. "
                         "'local' is a future slot — see README.")
    pcfg = cfg.get("providers", {}).get(name, {})
    return cls(api_key=get_api_key(cfg, name), model=pcfg.get("model") or cls(api_key="").model)
