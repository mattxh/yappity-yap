"""Command mode: transform selected text by a spoken instruction (LLM edit).

Uses an OpenAI-compatible chat endpoint (the cleanup endpoint). Pure prompt builder +
a thin request; failures raise CommandError so the caller can leave the selection alone.
"""
import logging

import requests

log = logging.getLogger(__name__)


class CommandError(Exception):
    pass


_SYSTEM = (
    "You are a text editor. Apply the user's spoken instruction to the selected text "
    "and output ONLY the resulting text — no preamble, quotes, or explanation. Preserve "
    "the original language(s); for Chinese use Traditional Chinese characters. If the "
    "instruction does not clearly apply, return the selected text unchanged."
)


def build_messages(selection: str, instruction: str):
    return [
        {"role": "system", "content": _SYSTEM},
        {"role": "user",
         "content": f"Instruction: {instruction}\n\nSelected text:\n{selection}"},
    ]


def transform(selection: str, instruction: str, *, model, api_key, base_url,
              timeout=30) -> str:
    if not selection.strip():
        return ""
    if not instruction.strip():
        return selection
    if not api_key:
        raise CommandError("API key not configured")
    try:
        resp = requests.post(
            f"{base_url}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={"model": model, "messages": build_messages(selection, instruction),
                  "temperature": 0},
            timeout=timeout,
        )
    except requests.RequestException as e:
        raise CommandError(str(e)) from e
    if resp.status_code != 200:
        raise CommandError(f"HTTP {resp.status_code}: {resp.text[:200]}")
    try:
        content = resp.json()["choices"][0]["message"]["content"]
    except (KeyError, IndexError, ValueError, TypeError) as e:
        raise CommandError(f"unexpected response: {e}") from e
    return content.strip()
