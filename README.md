# CodeBrain

**An MCP server that lets Claude Code offload bulk work to a local LLM running on your own hardware.**

![Status](https://img.shields.io/badge/status-Phase_2_complete-brightgreen)
![Stack](https://img.shields.io/badge/stack-Python_%2B_MCP_%2B_Ollama-blue)
![License](https://img.shields.io/badge/license-MIT-lightgrey)

---

## What this is (and isn't)

**Is:** A Model Context Protocol (MCP) server that Claude Code registers as a sub-agent backend. When a session includes the kind of task a 14B local coder model handles well — generating 50 event templates, polishing 20 React components, drafting boilerplate — Claude Code calls into CodeBrain instead of spending its own output tokens. The local model does the bulk draft, Claude reviews and applies.

**Is not:** A Claude replacement. The reasoning, architecture decisions, debugging, and anything where "close enough" isn't good enough stays with Claude. CodeBrain is a **Claude-offloader**, not a Claude-competitor.

**Why:** Large-volume content and polish work burns through Claude's context and rate limits fast. A local model you can run unlimited costs nothing extra per call and keeps the high-value context free for the hard parts of the session.

## Status

**Phase 2 complete.** Five tools exposed, `.brain/context.md` passthrough live, MCP integration verified in a real Claude Code session. Dogfood-tested on coding tasks (LRU cache, refactors, closure explanations) and structured text generation. Phase 2.5 (per-file brain system) is next — see the roadmap below.

## How it works

```
Claude Code session                     CodeBrain MCP server              Local machine
─────────────────────      stdio       ───────────────────                ─────────────
Claude delegates a         ────────►   codebrain_generate()     ────►    Ollama HTTP
bulk / polish task                     codebrain_explain()                (localhost:11434)
                                       codebrain_status()                      │
                                                                                ▼
                                                                        Qwen2.5-Coder 14B
                                                                              (GPU)
Claude reviews,            ◄────────   tool result string        ◄────    streamed response
applies, or pushes back
```

Five tools are exposed today:

| Tool | When Claude would reach for it |
|---|---|
| `codebrain_generate(prompt, system, use_brain)` | Bulk content, boilerplate, repetitive transformations, first drafts |
| `codebrain_batch_generate(prompts, system, use_brain)` | N prompts with one shared system message, serial execution, index-stable errors so one failure doesn't abort the batch |
| `codebrain_polish(text, instructions, use_brain)` | Targeted transform over existing text — shorten, rephrase, translate, tighten — preserves meaning and structure instead of regenerating |
| `codebrain_explain(code, question)` | Quick read-only explanations without burning Claude context |
| `codebrain_status()` | Check which models are installed locally |

The `use_brain` flag on generation tools automatically prepends `.brain/context.md` from the current working directory to the system prompt, so project-specific context travels with every call without Claude having to pass it manually.

Per-file brain summaries (`foo.py.brain` siblings with signatures, dependencies, and purpose) and a text-output VERIFIER loop are next on the roadmap.

## Requirements

- **Python 3.11+**
- **Ollama** — [download for your OS](https://ollama.com/download). Tested with Ollama on Windows native, talking over `localhost:11434`.
- **A coder model pulled locally:**
  ```bash
  ollama pull qwen2.5-coder:14b
  ```
  ~9 GB download. Fits in 12 GB VRAM at Q5. Other models work too (DeepSeek-Coder, Qwen3 if available) — set via `CODEBRAIN_MODEL` env var.
- **Claude Code CLI** on the machine that will call the server (obviously).

## Install

```bash
git clone <this repo> CodeBrain
cd CodeBrain
python -m venv .venv
.venv\Scripts\activate                         # on Windows
# source .venv/bin/activate                    # on macOS / Linux
pip install -e .
```

## Configure Claude Code

Add CodeBrain to your Claude Code MCP config. On Windows, that's usually `~/.claude.json` (adjust path to where you cloned):

```json
{
  "mcpServers": {
    "codebrain": {
      "command": "C:\\Users\\YOU\\Desktop\\CodeBrain\\.venv\\Scripts\\python.exe",
      "args": ["-m", "codebrain"]
    }
  }
}
```

Restart any Claude Code session — the five `codebrain_*` tools should now appear in the available-tools list.

## Sanity check

Inside a Claude Code session, ask Claude:

> Call `codebrain_status` and tell me what's installed.

If Ollama is running and the model is pulled, you'll get back `qwen2.5-coder:14b` in the list.

## Configuration

Environment variables read by the backend:

| Variable | Default | What it does |
|---|---|---|
| `CODEBRAIN_OLLAMA_URL` | `http://localhost:11434` | Point at a remote Ollama (e.g., an inference box on your LAN) |
| `CODEBRAIN_MODEL` | `qwen2.5-coder:14b` | Switch to any model you've pulled |
| `CODEBRAIN_TIMEOUT` | `300` | Seconds to wait for a single generation |

## Project structure

```
CodeBrain/
├── codebrain/
│   ├── __init__.py
│   ├── __main__.py            # `python -m codebrain` entry
│   ├── backend.py             # Ollama HTTP client
│   └── server.py              # FastMCP server + tool definitions
├── pyproject.toml
├── LICENSE
└── README.md
```

## Roadmap

### Phase 1 — scaffold ✓
- [x] Ollama HTTP client with error handling
- [x] FastMCP server with stdio transport
- [x] Three core tools: `generate`, `explain`, `status`
- [x] Documented setup + Claude Code config
- [x] Verified in a real Claude Code session

### Phase 2 — batch & context ✓
- [x] `codebrain_batch_generate` for mass content with one shared system prompt, index-stable errors
- [x] `codebrain_polish` for targeted transforms (shorten / rephrase / translate) instead of regeneration
- [x] `.brain/context.md` passthrough — cwd project context auto-prepended to every generation call
- [x] Dogfood: coding tasks solid, text-transform tasks revealed real limits (informs Phase 3)

### Phase 2.5 — brain system *(next)*
The real context-budget saver. For each code file `foo.py`, a companion `foo.py.brain` that captures signatures, dependencies, purpose, and gotchas. Claude reads the brain file first and only opens the source when it actually needs to.

- `codebrain_scan_file(path)` — generate or refresh a single brain file
- `codebrain_scan_repo(root, globs)` — bulk-seed brain files across a codebase
- Hash-gated regeneration so calls are idempotent (skip when source hash matches)
- Claude-side integration: CLAUDE.md convention + a `PostToolUse` hook snippet so brain files stay in sync after every edit
- Verifier-friendly format (frontmatter with source hash + mtime, structured sections) so Phase 3 can grep-check that claimed exports actually exist

### Phase 3 — VERIFIER loop (text-focused)
Dogfood showed the local model handles code well but drifts on text transforms — no-op polishes, ignored word limits, schema violations. So the verifier targets text:

- No-op detection (output stripped equals input stripped → retry with sharper instruction)
- Deterministic word-count / length gates
- Regex-schema checks for structured `batch_generate` outputs
- LLM-as-judge for tone-adherence (optional, costs a second inference call)
- Auto-retry with tightened instructions (max 2–3 iterations)

### Phase 4 — quality wrappers (optional)
- **Consensus decoding**: 5× generate, pick best → halves error rate, +3 s overhead
- **Multi-pass**: skeleton → logic → edge cases → polish as a tool sequence

### Phase 5 — RAG for style consistency *(only if needed)*
Brain files from Phase 2.5 already act as an index. Full RAG only gets built if cross-file search becomes the bottleneck.

## License

MIT — see [`LICENSE`](LICENSE).
