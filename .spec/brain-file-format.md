# Brain-File Format — v1

_Status: draft, 2026-04-19. Locked in dialog between User and Claude before implementing Phase 2.5a/b._

## Purpose

A `.brain` file is a short, semantic summary of one source file. It lets Claude (or any other reader) understand what the source does and how it fits into the project **without reading the source itself**. This saves context budget: a 400-line source file becomes a ~30-line brain file.

Brain files are **summaries, not stubs.** They describe purpose and role, not exact signatures. When a reader needs signatures or implementation detail, they read the source directly.

## File naming and placement

- **Inline convention:** `<source>.brain` lives next to the source.
  - `codebrain/backend.py` → `codebrain/backend.py.brain`
  - `src/components/Button.tsx` → `src/components/Button.tsx.brain`
- Not a mirror tree. Not a central `.brain/` folder. One source = one `.brain` next to it.
- Brain files SHOULD be committed to the repo so that teammates / fresh Claude sessions see them immediately.
- `.brain` is a Markdown file at its core — editors that don't recognise the extension will not syntax-highlight, but any tool reading it as text will work.

## Frontmatter schema

YAML frontmatter at the top of every brain file:

```yaml
---
source: codebrain/backend.py
source_hash: sha256:8a3c1f...   # SHA256 of source file contents (full hex)
source_mtime: 2026-04-19T14:32:00Z   # Info field only — NOT used for gating
model: qwen2.5-coder:14b
generated_at: 2026-04-19T14:32:05Z
---
```

Rules:

- `source` is the repo-relative path (POSIX separators, regardless of OS).
- `source_hash` is content-only SHA256, hex-encoded, prefixed with `sha256:`. **This is the sole input to the skip-gate.**
- `source_mtime` and `generated_at` are ISO-8601 UTC. Informational, for humans debugging "when was this touched".
- `model` records which model generated the file, so a model bump (e.g. to `qwen3-coder`) can trigger regeneration even when source hash is unchanged (future feature — v1 does not act on this field).
- **Foreign-model respect:** if the existing brain's `model` field does not start with `qwen` (e.g. `claude-inline`, indicating it was written by Claude directly per SDCD §1.6), CodeBrain's scanner MUST NOT overwrite it under `force=False`. Rationale: a Claude-written brain is usually richer than a Qwen-written one; stepping on it silently is a regression. Under `force=True`, the user has explicitly opted in.

## Section schema

Exactly five sections, in this order. Section headers are `## <Name>` (level-2, exact spelling). Every brain file MUST contain all five headers even if the content is empty or `_None._`.

### 1. `## Purpose`

One to two sentences. What does this file do in the context of the project.

- **Good:** "HTTP client for the local Ollama server. Wraps a single-turn chat call and a model-list call, and surfaces connection / HTTP errors as `BackendError`."
- **Bad:** "This file contains Python code." (meaningless)
- **Bad:** "Defines `chat` and `list_models`." (that's Key exports)

### 2. `## Key exports`

Bullet list. One line per exported symbol. Format: `` `name` — one-liner what it is/does ``.

- Only top-level exports users of this file would reach for. Skip private helpers.
- No signatures, no parameter lists, no return types. The source has those.
- Order by importance, not alphabetic.

### 3. `## Collaborators`

Bullet list. Which other files this one depends on **or** is depended on by, in terms of direct coupling. Skip standard library and framework imports.

- **Good:** "`codebrain/server.py` — imports `chat` and `BackendError` and wraps them in MCP tools."
- **Bad:** "`httpx`, `os`" (stdlib / third-party libs don't belong here)
- Can be `_None._` for leaf utilities with no project-internal couplings.

### 4. `## Gotchas`

Bullet list. Non-obvious behaviour, invariants, or lurking bugs. The stuff a reader would get wrong if they only read the signatures.

- **Good:** "`chat()` uses `response.raise_for_status()` before reading JSON — a 500 with a JSON error body never reaches the JSON parse step."
- **Good:** "Request timeout defaults to 300s via env var; long Qwen generations will hit this ceiling on a cold start."
- Can be `_None._` when the file is genuinely unsurprising.

### 5. `## Conventions`

Bullet list. How the code in this file "thinks" — the patterns a new contributor should match when adding to it. Async/sync style, error style, naming, typing.

- **Good:** "Async throughout — all outward-facing functions are `async def`."
- **Good:** "Errors are surfaced as a single domain exception (`BackendError`) chained via `raise ... from exc`. No bare `except`."
- Can be `_None._` for tiny files without clear patterns.

## Hash gate

Scanner tools MUST skip regeneration when the existing brain file's `source_hash` matches the current source's SHA256. No mtime check. No heuristics. Content-equal source → existing brain is valid by definition.

- Whitespace-only edits do not trigger regeneration (they do not change the hash).
- Touching a file with `touch` does not trigger regeneration.
- Force-regeneration is an explicit tool parameter (`force=True`), not an automatic fallback.

## Generation constraints

Brain-file generation is **LLM-only** and **language-agnostic**. No AST parser. No language-specific extractor. The same prompt-template must work for Python, Java, JS/TS, Rust, Go, or any other source file.

Because Qwen 14B ignores format constraints unreliably (see `memory/project_codebrain.md`), generation is a two-step pipeline:

1. **Few-shot prompt:** the system prompt includes one full example brain file (this spec's example below) as a format anchor.
2. **Post-validator:** the generator parses the Qwen output and checks:
   - Frontmatter is valid YAML with all required keys.
   - All five section headers (`## Purpose`, `## Key exports`, `## Collaborators`, `## Gotchas`, `## Conventions`) appear in order.
   - Each section has at least one non-empty line (including `_None._`).
   On validation failure: one retry with a harsher instruction ("you omitted `## Gotchas`; produce the full file again with all five sections"). Two fails → return error, do not write a broken brain file.

## Example

Below is the reference brain file for `codebrain/backend.py`. Scanners use this verbatim as the few-shot example in their generation prompt.

```markdown
---
source: codebrain/backend.py
source_hash: sha256:REPLACE_WITH_ACTUAL_SHA256_AT_BUILD
source_mtime: 2026-04-19T00:00:00Z
model: qwen2.5-coder:14b
generated_at: 2026-04-19T00:00:00Z
---

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
```

## Open items (tracked separately)

- `scan_repo` behaviour (in-place regenerate vs dry-run first) — decide during 2.5a implementation.
- `codebrain-init` setup script — decide during 2.5b.
- Model-bump regeneration semantics — v2 concern.
