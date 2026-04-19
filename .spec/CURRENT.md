# CodeBrain — Current State

_Last updated: 2026-04-19 (evening session)_

## Status

**Phases 1–4 complete, Phase 5 deferred.**

### Live tools (9)

- `codebrain_generate`, `codebrain_batch_generate`, `codebrain_polish` (with auto-noop retry), `codebrain_explain`, `codebrain_status`
- `codebrain_scan_file`, `codebrain_scan_repo`, `codebrain_init`
- `codebrain_generate_verified` (word-count / regex-schema / retry loop)
- `codebrain_consensus_generate` (N candidates → judge call)

### Backend

- Ollama on Windows native, `qwen2.5-coder:14b` (9 GB, fits 12 GB VRAM at Q5).
- Registered in Claude Code via `~/.claude.json` → `projects` → `C:/Users/wirsc` → `mcpServers.codebrain`.
- `.brain/context.md` passthrough: tools read it from cwd and prepend to system prompt.

### Architecture highlights this session

- **Programmatic frontmatter** in brain files: Qwen only writes the five sections, scanner assembles deterministic YAML header. No more frontmatter hallucinations.
- **Defense-in-depth validation**: wrapper-fence strip, skip-empty-sources (<10 chars), section presence/order, retry with tightened instructions.
- **Verifier layer** (`codebrain/verifier.py`): noop / word-count / regex-schema checks, shared across `polish` and `generate_verified`.
- **Repo-root discovery** for `source:` frontmatter path — walks up for `pyproject.toml` / `.git`, falls back to CWD then absolute POSIX.
- **Hash gate** (SHA256) is the sole regeneration trigger — mtime is informational only.

## Known limitations (not bugs — modeled in)

- **qwen2.5-coder:14b ignores format-rules in brain-file generation** (e.g. listed stdlib in Collaborators, produces signatures despite "name only" rule). Content-quality tuning would need either a larger model (32B, needs 24 GB VRAM → second RTX 4070 on the secondary box) or qwen3-coder (not yet tested).
- Brain files are **navigation-grade, not implementation-detail-grade** — good for "which file is responsible", not for "exact retry logic". For detail, read source.
- **MCP tool timeout**: `scan_repo` on ~5+ files serially exceeds the client-side tool call deadline. Call on smaller scopes until progress-streaming lands (not on roadmap).

## Test coverage

- `tests/test_brain_scanner.py` — 56 tests (hash helper, frontmatter parser, validator, fence stripper, display-path resolver, repo-root discovery, prompt builders, scan_file integration, iter_source_files, scan_repo)
- `tests/test_brain_init.py` — 17 tests (extension counting, marker detection, stack inference, context.md builder, init_repo orchestrator + fallback)
- `tests/test_verifier.py` — 14 tests (noop / word-count / regex-schema / run_checks / tightened-retry)
- `tests/test_server_verified.py` — 9 tests (polish-noop-retry, generate_verified loop, consensus judge call)
- **96 tests total, all passing.**

## As next (optional, when use reveals a need)

- **Phase 5 RAG** — only if cross-file search becomes a measurable bottleneck. Brain files already act as an index.
- **Model bump to qwen3-coder** — one `ollama pull` + env var swap, test whether rule-compliance improves.
- **Multi-pass generation** (Phase 4 skipped sub-feature) — skeleton→logic→edges→polish as a tool sequence. Compose manually for now.
- **Progress-streaming in scan_repo** — kills the MCP-timeout problem on large repos.

## Constraints

- Qwen 14B ignores negative/format instructions unreliably → brain-file generation uses programmatic frontmatter + post-validation + retry.
- Single GPU → all Ollama calls serial. `scan_repo` on 500+ files = slow; rely on hash-gate for resume-on-rerun.
- CodeBrain is a support layer, not Claude replacement. Brain files must still be Claude-consumable (markdown), not internal binary format.

## Tech reference

- Path: `C:\Users\wirsc\Desktop\CodeBrain`
- Package entrypoint: `python -m codebrain` (see `__main__.py`)
- Env vars: `CODEBRAIN_OLLAMA_URL`, `CODEBRAIN_MODEL`, `CODEBRAIN_TIMEOUT`
- MCP config block: `~/.claude.json` → `projects` → `C:/Users/wirsc` → `mcpServers.codebrain`
