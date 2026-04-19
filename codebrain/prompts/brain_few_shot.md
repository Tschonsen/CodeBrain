## Purpose

HTTP client for the local Ollama server. Wraps a single-turn chat call and a model-list call, and surfaces connection / HTTP errors as a single domain exception.

## Key exports

- `chat` — send a single-turn prompt to Ollama, return the assistant message.
- `list_models` — return the names of models installed in the local Ollama.
- `BackendError` — raised when the Ollama call fails for any reason.

## Collaborators

- `codebrain/server.py` — imports `chat`, `list_models`, and `BackendError`, wraps them in MCP tools.

## Gotchas

- Request timeout defaults to 300s via `CODEBRAIN_TIMEOUT`; long Qwen generations on a cold start can approach this ceiling.
- `chat()` calls `response.raise_for_status()` before reading JSON, so a 500 with a JSON error body raises `BackendError` before the JSON parse step runs.
- `list_models()` uses a separate 10s timeout hard-coded; env var does not apply here.

## Conventions

- Async throughout — all outward-facing functions are `async def` and use `httpx.AsyncClient` as a context manager per call.
- Errors are surfaced as a single domain exception (`BackendError`) chained via `raise ... from exc`. No bare `except`.
- Configuration is read from environment at module load time, with sensible defaults.
