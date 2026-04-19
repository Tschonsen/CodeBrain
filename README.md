# CodeBrain

**An MCP server that lets Claude Code offload bulk work to a local LLM running on your own hardware.**

![Status](https://img.shields.io/badge/status-Phases_1--4_complete-brightgreen)
![Stack](https://img.shields.io/badge/stack-Python_%2B_MCP_%2B_Ollama-blue)
![License](https://img.shields.io/badge/license-MIT-lightgrey)

---

## What this is (and isn't)

**Is:** A Model Context Protocol (MCP) server that Claude Code registers as a sub-agent backend. When a session includes the kind of task a 14B local coder model handles well — generating 50 event templates, polishing 20 React components, drafting boilerplate — Claude Code calls into CodeBrain instead of spending its own output tokens. The local model does the bulk draft, Claude reviews and applies.

**Is not:** A Claude replacement. The reasoning, architecture decisions, debugging, and anything where "close enough" isn't good enough stays with Claude. CodeBrain is a **Claude-offloader**, not a Claude-competitor.

**Why:** Large-volume content and polish work burns through Claude's context and rate limits fast. A local model you can run unlimited costs nothing extra per call and keeps the high-value context free for the hard parts of the session.

## Status

**Phases 1–4 complete, Phase 5 deferred.** Nine tools exposed, `.brain/context.md` passthrough live, per-file brain summaries scanner, verifier loop, consensus decoding. MCP integration verified in a real Claude Code session. Phase 5 (RAG) was explicitly scoped as "only if needed" and current use doesn't show cross-file search as a bottleneck, so it stays deferred.

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

Nine tools are exposed today:

| Tool | When Claude would reach for it |
|---|---|
| `codebrain_generate(prompt, system, use_brain)` | Bulk content, boilerplate, repetitive transformations, first drafts |
| `codebrain_batch_generate(prompts, system, use_brain)` | N prompts with one shared system message, serial execution, index-stable errors so one failure doesn't abort the batch |
| `codebrain_polish(text, instructions, use_brain)` | Targeted transform over existing text — shorten, rephrase, translate, tighten. Auto-retries on no-op output. |
| `codebrain_explain(code, question)` | Quick read-only explanations without burning Claude context |
| `codebrain_generate_verified(prompt, min_words, max_words, must_match, max_retries)` | Generation with deterministic verifier loop: word-count / regex-schema checks, tightened-instruction retry on violation |
| `codebrain_consensus_generate(prompt, n)` | N candidates + judge call → best single output. Use on high-variance tasks. |
| `codebrain_init(root, force)` | One-shot repo onboarding: detects stack, writes `.brain/context.md` template |
| `codebrain_scan_file(path, force)` | Generate or refresh one `<source>.brain` summary file |
| `codebrain_scan_repo(root, force, extensions, exclude_dirs)` | Walk + scan a tree; hash-gated, per-file failures don't abort the batch |
| `codebrain_status()` | Check which models are installed locally |

The `use_brain` flag on generation tools automatically prepends `.brain/context.md` from the current working directory to the system prompt, so project-specific context travels with every call without Claude having to pass it manually.

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

## Keep brain files in sync automatically

Once you've run `codebrain_init` on a repo and scanned it with `codebrain_scan_repo`, you probably want brain files to refresh automatically whenever Claude edits source. Two pieces wire that up:

**1. Project CLAUDE.md snippet** — tell Claude to read brain files before opening source:

```markdown
## Brain files

This repo has per-file `.brain` summaries next to each source file.
Before reading a full source file, read its `<path>.brain` sibling first.
Only open the source when the brain file is insufficient for the task.
```

**2. PostToolUse hook** — regenerate the brain after every Edit/Write.

Add to `.claude/settings.json` in the repo root:

```json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "Edit|Write",
        "hooks": [
          {
            "type": "command",
            "command": "python -c \"import asyncio, json, sys; from codebrain.brain_scanner import scan_file; d = json.load(sys.stdin); p = d.get('tool_input', {}).get('file_path'); p and p.endswith(('.py', '.ts', '.tsx', '.js', '.jsx', '.java', '.go', '.rs')) and print(asyncio.run(scan_file(p)))\""
          }
        ]
      }
    ]
  }
}
```

The hook inspects the edited path, skips non-source files via the extension filter, and kicks off a scan. Hash-gated: unchanged files don't hit Qwen.

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
│   ├── server.py              # FastMCP server + tool definitions
│   ├── brain_scanner.py       # scan_file / scan_repo + hash gate
│   ├── brain_init.py          # one-shot .brain/context.md seeding
│   ├── verifier.py            # deterministic output checks
│   └── prompts/
│       └── brain_few_shot.md  # few-shot for brain-file generation
├── tests/                     # 96 unit + integration tests
├── .spec/
│   ├── CURRENT.md             # phase state
│   └── brain-file-format.md   # brain-file format v1
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

### Phase 2.5 — brain system ✓
Per-file `<source>.brain` summaries sit next to each source file. Claude reads the brain first and only opens the source when the brain is insufficient.

- [x] `codebrain_scan_file(path, force)` — generate or refresh one brain file
- [x] `codebrain_scan_repo(root, force, extensions, exclude_dirs)` — bulk walk + scan
- [x] `codebrain_init(root, force)` — seed `.brain/context.md` with stack detection
- [x] Hash-gated regeneration (SHA256) — idempotent reruns
- [x] Programmatic frontmatter — deterministic `source`, `source_hash`, `model`; Qwen only writes the five sections
- [x] Defense-in-depth validation: fence-strip, skip-empty-sources (<10 chars), section-presence/order, retry-on-invalid
- [x] CLAUDE.md convention + PostToolUse hook snippet in this README

### Phase 3 — VERIFIER loop ✓
Dogfood showed the local model drifts on text transforms. The verifier catches no-ops, length violations, and schema misses deterministically before they reach Claude.

- [x] `detect_noop` — whitespace-normalised equality check (auto-retries inside `codebrain_polish`)
- [x] `check_word_count(min_words, max_words)` — bounded-window gate
- [x] `check_regex_schema(pattern)` — structured-output check
- [x] `codebrain_generate_verified(prompt, min_words, max_words, must_match, max_retries)` — loop with tightened retry instructions, returns `[codebrain warning] ...` if verification fails after retries

### Phase 4 — consensus decoding ✓
- [x] `codebrain_consensus_generate(prompt, n)` — generate N candidates (clamped to [2,5]), Qwen picks the best verbatim. N+1 inference calls, tightens quality on high-variance tasks.
- Multi-pass skeleton→logic→edges→polish: deferred (low measured value; individual tools already compose).

### Phase 5 — RAG *(deferred — not a bottleneck)*
Brain files already act as an index; cross-file RAG only makes sense if future use actually shows that indexing is the blocker. No current signal for it, so not built.

## License

MIT — see [`LICENSE`](LICENSE).
