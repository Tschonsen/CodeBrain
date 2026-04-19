"""MCP server — exposes CodeBrain tools to Claude Code via stdio."""

from __future__ import annotations

from pathlib import Path

from mcp.server.fastmcp import FastMCP

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
        return await chat(prompt, system=composed_system)
    except BackendError as exc:
        return f"[codebrain error] {exc}"


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
