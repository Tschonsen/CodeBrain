"""Ollama HTTP client — the thin wrapper around the local model."""

from __future__ import annotations

import os

import httpx

OLLAMA_URL = os.environ.get("CODEBRAIN_OLLAMA_URL", "http://localhost:11434")
DEFAULT_MODEL = os.environ.get("CODEBRAIN_MODEL", "qwen2.5-coder:14b")
REQUEST_TIMEOUT = float(os.environ.get("CODEBRAIN_TIMEOUT", "300"))


class BackendError(RuntimeError):
    """Ollama call failed (connection, HTTP error, or unexpected payload)."""


async def chat(
    prompt: str,
    system: str = "",
    model: str | None = None,
    temperature: float = 0.2,
) -> str:
    """Send a single-turn chat request to Ollama and return the assistant message."""
    model = model or DEFAULT_MODEL
    messages: list[dict[str, str]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "options": {"temperature": temperature},
    }

    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            response = await client.post(f"{OLLAMA_URL}/api/chat", json=payload)
            response.raise_for_status()
            data = response.json()
    except httpx.ConnectError as exc:
        raise BackendError(
            f"Cannot reach Ollama at {OLLAMA_URL} — is `ollama serve` running?"
        ) from exc
    except httpx.HTTPStatusError as exc:
        raise BackendError(
            f"Ollama returned {exc.response.status_code}: {exc.response.text}"
        ) from exc

    try:
        return data["message"]["content"]
    except (KeyError, TypeError) as exc:
        raise BackendError(f"Unexpected Ollama response shape: {data!r}") from exc


async def list_models() -> list[str]:
    """List models currently installed in the local Ollama."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{OLLAMA_URL}/api/tags")
            response.raise_for_status()
            return [m["name"] for m in response.json().get("models", [])]
    except httpx.ConnectError as exc:
        raise BackendError(
            f"Cannot reach Ollama at {OLLAMA_URL} — is `ollama serve` running?"
        ) from exc
