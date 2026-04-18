"""MCP server — exposes CodeBrain tools to Claude Code via stdio."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from .backend import BackendError, chat, list_models

mcp = FastMCP("codebrain")


@mcp.tool()
async def codebrain_generate(prompt: str, system: str = "") -> str:
    """Delegate a generation task to the local Qwen-Coder model via Ollama.

    Use this for bulk or routine work where a 14B local model is good enough:
    generating event templates, headlines, company descriptions, UI polish
    drafts, boilerplate, or repetitive transformations. The response is
    returned as raw text — review before applying.

    Args:
        prompt: The task description or content request.
        system: Optional system message to steer tone / format / constraints.
    """
    try:
        return await chat(prompt, system=system)
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
