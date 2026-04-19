"""MCP server — exposes CodeBrain tools to Claude Code via stdio."""

from __future__ import annotations

from pathlib import Path

from mcp.server.fastmcp import FastMCP

from . import brain_init, brain_scanner, verifier
from .backend import BackendError, chat, list_models

mcp = FastMCP("codebrain")

BRAIN_CONTEXT_PATH = Path(".brain") / "context.md"


def _load_brain_context() -> str:
    """Read `.brain/context.md` from cwd if present, else empty string."""
    try:
        return BRAIN_CONTEXT_PATH.read_text(encoding="utf-8").strip()
    except (FileNotFoundError, OSError):
        return ""


def _compose_system(system: str, use_brain: bool) -> str:
    """Prepend project .brain context to the user-provided system prompt."""
    if not use_brain:
        return system
    brain = _load_brain_context()
    if not brain:
        return system
    header = "Project context (from .brain/context.md):\n" + brain
    return f"{header}\n\n{system}" if system else header


@mcp.tool()
async def codebrain_generate(prompt: str, system: str = "", use_brain: bool = True) -> str:
    """Delegate a generation task to the local Qwen-Coder model via Ollama.

    Use this for bulk or routine work where a 14B local model is good enough:
    generating event templates, headlines, company descriptions, UI polish
    drafts, boilerplate, or repetitive transformations. The response is
    returned as raw text — review before applying.

    Args:
        prompt: The task description or content request.
        system: Optional system message to steer tone / format / constraints.
        use_brain: If true, prepend `.brain/context.md` from cwd to the system prompt.
    """
    try:
        return await chat(prompt, system=_compose_system(system, use_brain))
    except BackendError as exc:
        return f"[codebrain error] {exc}"


@mcp.tool()
async def codebrain_explain(code: str, question: str = "What does this do?") -> str:
    """Ask the local model to explain a snippet of code (read-only, no generation).

    Useful for getting quick, token-free explanations without consuming
    Claude's context budget on understanding-only tasks.

    Args:
        code: The code snippet to explain.
        question: The specific question to answer about the code.
    """
    system = (
        "You explain code clearly and briefly. No fluff, no disclaimers. "
        "Answer the question directly."
    )
    prompt = f"{question}\n\n```\n{code}\n```"
    try:
        return await chat(prompt, system=system)
    except BackendError as exc:
        return f"[codebrain error] {exc}"


@mcp.tool()
async def codebrain_batch_generate(
    prompts: list[str],
    system: str = "",
    use_brain: bool = True,
) -> str:
    """Run several generation prompts in sequence and return all results.

    One shared system prompt applies to every item. Prompts are processed
    serially (Ollama serialises on a single GPU anyway). A failure on one
    prompt is captured inline as `[codebrain error] ...` at that index, so
    the whole batch never aborts.

    Returns a single string with per-item delimiters:

        --- [0] ---
        <result for prompts[0]>

        --- [1] ---
        <result for prompts[1]>

    Args:
        prompts: List of prompts to run with the same system message.
        system: Optional shared system message.
        use_brain: If true, prepend `.brain/context.md` from cwd to the system prompt.
    """
    if not prompts:
        return "[codebrain error] prompts list is empty"

    composed_system = _compose_system(system, use_brain)
    parts: list[str] = []
    for i, p in enumerate(prompts):
        try:
            result = await chat(p, system=composed_system)
        except BackendError as exc:
            result = f"[codebrain error] {exc}"
        parts.append(f"--- [{i}] ---\n{result}")
    return "\n\n".join(parts)


@mcp.tool()
async def codebrain_polish(
    text: str,
    instructions: str,
    use_brain: bool = True,
) -> str:
    """Apply a targeted transform to existing text — do not regenerate from scratch.

    Use this when you have a draft and want it tightened, shortened, rephrased,
    made more formal, translated, or similar. The system prompt forces the
    model into transform-mode: it must preserve meaning and structure and only
    apply the requested change.

    Args:
        text: The existing text to polish.
        instructions: What transformation to apply (e.g. "shorten to 2 lines",
            "make tone more formal", "translate to German").
        use_brain: If true, prepend `.brain/context.md` from cwd to the system prompt.
    """
    system = (
        "You are a text polisher. The user gives you existing text and an "
        "instruction describing one targeted change. Apply ONLY that change. "
        "Preserve meaning, structure, and any content not mentioned in the "
        "instruction. Output only the polished text — no preamble, no "
        "explanation, no surrounding quotes."
    )
    composed_system = _compose_system(system, use_brain)
    prompt = f"Instruction: {instructions}\n\nText to polish:\n{text}"
    try:
        output = await chat(prompt, system=composed_system)
    except BackendError as exc:
        return f"[codebrain error] {exc}"

    ok, reason = verifier.detect_noop(text, output)
    if not ok:
        retry_prompt = (
            prompt + "\n\n" + verifier.tightened_retry_instruction(reason)
        )
        try:
            output = await chat(retry_prompt, system=composed_system)
        except BackendError as exc:
            return f"[codebrain error] {exc}"
    return output


@mcp.tool()
async def codebrain_scan_file(path: str, force: bool = False) -> str:
    """Generate or refresh the `<path>.brain` summary file for a source file.

    Reads the source at `path`, computes its SHA256, and compares to the
    existing `.brain` file's `source_hash` frontmatter. If they match and
    `force` is false, generation is skipped. Otherwise Qwen produces a new
    brain file (Purpose / Key exports / Collaborators / Gotchas /
    Conventions), the output is validated against the format spec, and on
    validation failure one retry with a sharper instruction is attempted
    before giving up. No partial or broken brain files are ever written.

    Format spec: `.spec/brain-file-format.md`.

    Args:
        path: Path to the source file to summarise.
        force: If true, regenerate even when the hash matches.
    """
    return await brain_scanner.scan_file(path, force=force)


@mcp.tool()
async def codebrain_consensus_generate(
    prompt: str,
    system: str = "",
    n: int = 3,
    use_brain: bool = True,
) -> str:
    """Generate N candidates, let Qwen pick the best, return the winner.

    Runs `prompt` N times (serial — Ollama serialises on single GPU anyway),
    then does one additional call where Qwen is shown all candidates and
    asked to return the best one verbatim. Useful for high-variance tasks
    where a single shot drifts but majority-vote style sampling tightens
    quality at the cost of N+1 inference calls.

    Args:
        prompt: The task description or content request.
        system: Optional system message to steer tone / format / constraints.
        n: Number of candidates to generate (default 3, clamped to [2, 5]).
        use_brain: If true, prepend `.brain/context.md` to the system prompt.
    """
    n = max(2, min(5, n))
    composed_system = _compose_system(system, use_brain)

    candidates: list[str] = []
    for i in range(n):
        try:
            candidates.append(await chat(prompt, system=composed_system))
        except BackendError as exc:
            return f"[codebrain error] candidate {i} failed: {exc}"

    judge_system = (
        "You pick the single best candidate output for a user's task. "
        "Criteria in priority order: correctness, matches the instruction, "
        "clarity, concision. Output ONLY the chosen candidate's text — no "
        "preamble, no explanation, no 'Candidate N:' prefix, no quotes."
    )
    body = "\n\n".join(
        f"--- Candidate {i + 1} ---\n{c}" for i, c in enumerate(candidates)
    )
    judge_prompt = (
        f"Original task:\n{prompt}\n\n"
        f"Candidates:\n\n{body}\n\n"
        "Return the single best candidate verbatim."
    )
    try:
        return await chat(judge_prompt, system=judge_system)
    except BackendError as exc:
        return f"[codebrain error] judge call failed: {exc}"


@mcp.tool()
async def codebrain_generate_verified(
    prompt: str,
    system: str = "",
    min_words: int | None = None,
    max_words: int | None = None,
    must_match: str | None = None,
    max_retries: int = 2,
    use_brain: bool = True,
) -> str:
    """Generate with verifier loop — enforces word limits and regex schemas.

    Runs `codebrain_generate`, then checks the output against the requested
    constraints. On failure, retries with a tightened instruction that
    names the specific problem. Gives up after `max_retries` attempts and
    returns the last output with a `[codebrain warning] ...` prefix.

    Args:
        prompt: The task description or content request.
        system: Optional system message to steer tone / format / constraints.
        min_words: Minimum output word count (None = unbounded).
        max_words: Maximum output word count (None = unbounded).
        must_match: Regex pattern the output must match (`re.search` semantics).
        max_retries: Max retry attempts on verification failure (default 2).
        use_brain: If true, prepend `.brain/context.md` to the system prompt.
    """
    composed_system = _compose_system(system, use_brain)
    current_prompt = prompt
    output = ""
    reason = ""
    for attempt in range(max_retries + 1):
        try:
            output = await chat(current_prompt, system=composed_system)
        except BackendError as exc:
            return f"[codebrain error] {exc}"
        ok, reason = verifier.run_checks(
            output,
            min_words=min_words,
            max_words=max_words,
            must_match=must_match,
        )
        if ok:
            return output
        current_prompt = (
            prompt + "\n\n" + verifier.tightened_retry_instruction(reason)
        )
    return f"[codebrain warning] verification failed after {max_retries} retries ({reason}):\n\n{output}"


@mcp.tool()
async def codebrain_init(root: str, force: bool = False) -> str:
    """Seed `.brain/context.md` for a repo — one-time setup before scanning.

    Detects the stack (python / js / ts / rust / go / java) from marker
    files, counts source-file extensions, asks Qwen for a short overview,
    and writes `.brain/context.md` with a pre-populated template. The user
    is expected to edit the `## Notes for Claude` section afterwards.
    Idempotent: existing `context.md` is not overwritten unless `force=True`.

    Args:
        root: Directory to initialise.
        force: If true, overwrite an existing `.brain/context.md`.
    """
    return await brain_init.init_repo(root, force=force)


@mcp.tool()
async def codebrain_scan_repo(
    root: str,
    force: bool = False,
    extensions: list[str] | None = None,
    exclude_dirs: list[str] | None = None,
) -> str:
    """Scan every source file under `root` and generate/refresh its `.brain` file.

    Walks the directory tree, filters by file extension, prunes excluded
    directories, and runs `codebrain_scan_file` on each match. Hash-gated:
    unchanged files skip the model call. Per-file failures do not abort the
    batch — they are reported at the end.

    Defaults:
      - extensions: .py .js .ts .tsx .jsx .java .go .rs
      - exclude_dirs: .git .venv venv node_modules __pycache__ dist build target

    Args:
        root: Directory to scan recursively.
        force: If true, regenerate every brain file even when source hash matches.
        extensions: Override default source extensions (e.g. [".py", ".rb"]).
        exclude_dirs: Override default directory-name exclusion list.
    """
    return await brain_scanner.scan_repo(
        root, force=force, extensions=extensions, exclude_dirs=exclude_dirs
    )


@mcp.tool()
async def codebrain_status() -> str:
    """Report which Ollama models are available locally.

    Call this to verify the local backend is reachable and discover
    which models the user has pulled.
    """
    try:
        models = await list_models()
    except BackendError as exc:
        return f"[codebrain error] {exc}"
    if not models:
        return "No models installed. Run `ollama pull qwen2.5-coder:14b` to add the default."
    return "Installed models:\n" + "\n".join(f"  - {m}" for m in models)


def main() -> None:
    """Entry point — run the MCP server over stdio."""
    mcp.run()


if __name__ == "__main__":
    main()
