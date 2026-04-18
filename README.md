# CodeBrain

**An MCP server that lets Claude Code offload bulk work to a local LLM running on your own hardware.**

![Status](https://img.shields.io/badge/status-Phase_1_scaffold-yellow)
![Stack](https://img.shields.io/badge/stack-Python_%2B_MCP_%2B_Ollama-blue)
![License](https://img.shields.io/badge/license-MIT-lightgrey)

---

## What this is (and isn't)

**Is:** A Model Context Protocol (MCP) server that Claude Code registers as a sub-agent backend. When a session includes the kind of task a 14B local coder model handles well — generating 50 event templates, polishing 20 React components, drafting boilerplate — Claude Code calls into CodeBrain instead of spending its own output tokens. The local model does the bulk draft, Claude reviews and applies.

**Is not:** A Claude replacement. The reasoning, architecture decisions, debugging, and anything where "close enough" isn't good enough stays with Claude. CodeBrain is a **Claude-offloader**, not a Claude-competitor.

**Why:** Large-volume content and polish work burns through Claude's context and rate limits fast. A local model you can run unlimited costs nothing extra per call and keeps the high-value context free for the hard parts of the session.

## Status

**Phase 1 scaffold.** Skeleton works, three tools exposed, Ollama backend wired. Not yet battle-tested across real workflows. This README will evolve as integration matures.

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

Three tools are exposed today:

| Tool | When Claude would reach for it |
|---|---|
| `codebrain_generate(prompt, system)` | Bulk content, boilerplate, repetitive transformations, first drafts |
| `codebrain_explain(code, question)` | Quick read-only explanations without burning Claude context |
| `codebrain_status()` | Check which models are installed locally |

The list is deliberately short for Phase 1. Batch-polish, context-aware `.brain` helpers, and a VERIFIER test-loop are planned for later phases.

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

Restart any Claude Code session — the tools `codebrain_generate`, `codebrain_explain`, and `codebrain_status` should now appear in the available-tools list.

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

### Phase 1 — scaffold *(current)*
- [x] Ollama HTTP client with error handling
- [x] FastMCP server with stdio transport
- [x] Three core tools: generate, explain, status
- [x] Documented setup + Claude Code config
- [ ] Test in a real session — does Claude actually reach for these tools when appropriate?

### Phase 2 — batch & context
- `codebrain_batch_generate` for mass content with a shared system prompt
- `codebrain_polish` for applying a style across many files
- `.brain`-style project summaries passed as context automatically

### Phase 3 — VERIFIER loop
- Wire output through test-runner / linter / type-checker
- Auto-retry with error feedback (max 3 iterations)
- Per-error-type repair strategies

### Phase 4 — MEMORY
- RAG over the user's own code for style consistency
- Correction learning

## License

MIT — see [`LICENSE`](LICENSE).
