"""Per-file `.brain` summariser — Phase 2.5 core.

Given a source path, generate (or refresh) a `<source>.brain` file that
describes the source's purpose, exports, collaborators, gotchas, and
conventions. Language-agnostic: Qwen reads the source as plain text.

Skip-gate is content-hash based: when the existing brain file's
`source_hash` frontmatter matches the current SHA256 of the source,
the brain is considered up-to-date and no generation is run.

Format spec: `.spec/brain-file-format.md`.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import os
import re
from collections.abc import Iterator
from importlib.resources import files
from pathlib import Path

import yaml

from .backend import DEFAULT_MODEL, BackendError, chat

MIN_SOURCE_CHARS = 10

DEFAULT_SOURCE_EXTENSIONS = frozenset(
    {".py", ".js", ".ts", ".tsx", ".jsx", ".java", ".go", ".rs"}
)
DEFAULT_EXCLUDE_DIRS = frozenset(
    {".git", ".venv", "venv", "node_modules", "__pycache__", "dist", "build", "target"}
)

SECTION_HEADERS = (
    "## Purpose",
    "## Key exports",
    "## Collaborators",
    "## Gotchas",
    "## Conventions",
)
REQUIRED_FRONTMATTER_KEYS = frozenset(
    {"source", "source_hash", "source_mtime", "model", "generated_at"}
)
FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)
WRAPPER_FENCE_RE = re.compile(r"\A\s*```\w*\s*\n(.*?)\n```\s*\Z", re.DOTALL)


def strip_wrapper_fences(text: str) -> str:
    """Strip a surrounding ```...``` fence when the whole output is wrapped.

    Qwen sometimes wraps its brain-file output in ```markdown ... ``` despite
    being told not to — that would break the frontmatter regex (anchored on
    ``\\A---``). This normaliser is tolerant of that quirk.
    """
    m = WRAPPER_FENCE_RE.match(text)
    if not m:
        return text
    inner = m.group(1)
    if not inner.endswith("\n"):
        inner += "\n"
    return inner


def compute_source_hash(content: bytes) -> str:
    """Return `sha256:<hex>` digest of raw file bytes."""
    return "sha256:" + hashlib.sha256(content).hexdigest()


REPO_ROOT_MARKERS = (".git", "pyproject.toml")


def find_repo_root(source: Path) -> Path | None:
    """Walk up from `source` looking for a repo-root marker (`.git` or `pyproject.toml`)."""
    for parent in source.resolve().parents:
        for marker in REPO_ROOT_MARKERS:
            if (parent / marker).exists():
                return parent
    return None


def resolve_display_path(source: Path, repo_root: Path | None = None) -> str:
    """Return a repo-relative POSIX path when `source` lives under the repo root.

    Root discovery order: explicit `repo_root`, then walk-up from `source`
    looking for `.git` or `pyproject.toml`, then CWD as last resort. Falls
    back to the absolute POSIX string when `source` sits outside the root.
    Spec requires `source` in frontmatter to be repo-relative with POSIX
    separators (`.spec/brain-file-format.md` §'Frontmatter schema').
    """
    root = (repo_root or find_repo_root(source) or Path.cwd()).resolve()
    try:
        rel = source.resolve().relative_to(root)
    except ValueError:
        return str(source).replace("\\", "/")
    return rel.as_posix()


def parse_existing_brain(path: Path) -> dict | None:
    """Return the frontmatter dict, or None if file is missing / unparseable."""
    try:
        text = path.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError):
        return None
    m = FRONTMATTER_RE.match(text)
    if not m:
        return None
    try:
        data = yaml.safe_load(m.group(1))
    except yaml.YAMLError:
        return None
    return data if isinstance(data, dict) else None


VALUE_CHECKED_FRONTMATTER_KEYS = ("source", "source_hash", "model")


def validate_brain_output(
    text: str, expected: dict | None = None
) -> tuple[bool, str]:
    """Check frontmatter completeness, section presence/order/non-emptiness.

    When `expected` is given, also verify that `source`, `source_hash` and
    `model` match — Qwen sometimes ignores the "use these values exactly"
    instruction and substitutes placeholders.
    """
    m = FRONTMATTER_RE.match(text)
    if not m:
        return False, "missing or malformed frontmatter block"
    try:
        fm = yaml.safe_load(m.group(1))
    except yaml.YAMLError as exc:
        return False, f"frontmatter YAML parse error: {exc}"
    if not isinstance(fm, dict):
        return False, "frontmatter is not a YAML mapping"
    missing = REQUIRED_FRONTMATTER_KEYS - set(fm.keys())
    if missing:
        return False, f"frontmatter missing required keys: {sorted(missing)}"
    if expected is not None:
        for key in VALUE_CHECKED_FRONTMATTER_KEYS:
            if fm.get(key) != expected.get(key):
                return False, (
                    f"frontmatter {key!r} mismatch: got {fm.get(key)!r}, "
                    f"expected {expected.get(key)!r}"
                )

    positions: list[int] = []
    cursor = m.end()
    for header in SECTION_HEADERS:
        idx = text.find(header, cursor)
        if idx == -1:
            return False, f"missing or out-of-order section {header!r}"
        positions.append(idx)
        cursor = idx + len(header)

    for i, header in enumerate(SECTION_HEADERS):
        start = positions[i] + len(header)
        end = positions[i + 1] if i + 1 < len(positions) else len(text)
        body = text[start:end].strip()
        if not body:
            return False, f"section {header!r} is empty"

    return True, ""


def _load_few_shot() -> str:
    return (files("codebrain.prompts") / "brain_few_shot.md").read_text(encoding="utf-8")


def build_system_prompt(few_shot: str) -> str:
    return (
        "You summarise source files as a set of five Markdown sections for "
        "later context-efficient reading.\n\n"
        "Output exactly these five sections, in this order, each with a "
        "level-2 header: ## Purpose, ## Key exports, ## Collaborators, "
        "## Gotchas, ## Conventions. Every section must contain at least one "
        "line of text (use `_None._` if truly nothing applies).\n\n"
        "Rules:\n"
        "- Purpose: 1-2 sentences describing what the file does in the project.\n"
        "- Key exports: bullet list of top-level exports, one line each. "
        "Name only — no parens, no parameters, no type annotations.\n"
        "- Collaborators: project-internal files this one couples with, "
        "derived from the source's import statements. Skip stdlib and "
        "third-party framework imports. Do not list asset or template files.\n"
        "- Gotchas: non-obvious behaviour, invariants, lurking bugs.\n"
        "- Conventions: how the code in this file is written — async/sync "
        "style, error-handling patterns, naming conventions, typing style. "
        "Not the format of any output the file produces.\n"
        "- Empty sections: write exactly `_None._` on its own line — "
        "italicised with underscores, not a bullet. Never `None`, `- None`, "
        "or `- None.`.\n\n"
        "Here is one complete example of the expected output:\n\n"
        f"```markdown\n{few_shot}```\n\n"
        "Output ONLY the five sections starting at `## Purpose`. Do NOT "
        "output YAML frontmatter, a `---` fence, a title, or any preamble. "
        "No code fences around the output."
    )


def build_user_prompt(source_path: str, source_content: str) -> str:
    return (
        f"Summarise this source file ({source_path}):\n\n"
        f"```\n{source_content}\n```"
    )


def assemble_brain_file(sections: str, frontmatter: dict) -> str:
    """Prepend a YAML frontmatter block to the sections body and return one brain file."""
    fm_yaml = yaml.safe_dump(
        frontmatter, sort_keys=False, allow_unicode=True
    ).strip()
    body = sections.lstrip()
    if not body.endswith("\n"):
        body += "\n"
    return f"---\n{fm_yaml}\n---\n\n{body}"


def validate_sections(text: str) -> tuple[bool, str]:
    """Check that `text` contains exactly the five required sections in order, each non-empty."""
    positions: list[int] = []
    cursor = 0
    for header in SECTION_HEADERS:
        idx = text.find(header, cursor)
        if idx == -1:
            return False, f"missing or out-of-order section {header!r}"
        positions.append(idx)
        cursor = idx + len(header)

    for i, header in enumerate(SECTION_HEADERS):
        start = positions[i] + len(header)
        end = positions[i + 1] if i + 1 < len(positions) else len(text)
        body = text[start:end].strip()
        if not body:
            return False, f"section {header!r} is empty"

    return True, ""


RETRY_INSTRUCTION = (
    "Your previous output was invalid ({reason}). Produce the five sections "
    "again: ## Purpose, ## Key exports, ## Collaborators, ## Gotchas, "
    "## Conventions — in order, each with at least one non-empty line. "
    "Do not output YAML frontmatter. Output only the sections."
)


async def scan_file(
    path: str,
    force: bool = False,
    model: str | None = None,
) -> str:
    """Generate or refresh the `.brain` file for `path`.

    Returns a human-readable status line starting with `skipped`,
    `generated`, or `[codebrain error]`.
    """
    source = Path(path)
    try:
        source_bytes = source.read_bytes()
    except FileNotFoundError:
        return f"[codebrain error] source file not found: {path}"
    except OSError as exc:
        return f"[codebrain error] cannot read source {path}: {exc}"

    if len(source_bytes.strip()) < MIN_SOURCE_CHARS:
        return f"skipped (source too small): {path}"

    source_hash = compute_source_hash(source_bytes)
    brain_path = source.with_name(source.name + ".brain")

    if not force:
        existing = parse_existing_brain(brain_path)
        if existing is not None and existing.get("source_hash") == source_hash:
            return f"skipped (unchanged): {brain_path}"

    try:
        source_content = source_bytes.decode("utf-8")
    except UnicodeDecodeError:
        return f"[codebrain error] source is not UTF-8 text: {path}"

    mtime_dt = dt.datetime.fromtimestamp(source.stat().st_mtime, tz=dt.timezone.utc)
    source_mtime = mtime_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    used_model = model or DEFAULT_MODEL
    display_path = resolve_display_path(source)

    few_shot = _load_few_shot()
    system = build_system_prompt(few_shot)
    user_prompt = build_user_prompt(display_path, source_content)

    try:
        output = await chat(user_prompt, system=system)
    except BackendError as exc:
        return f"[codebrain error] {exc}"

    output = strip_wrapper_fences(output)
    ok, reason = validate_sections(output)
    if not ok:
        retry_prompt = user_prompt + "\n\n" + RETRY_INSTRUCTION.format(reason=reason)
        try:
            output = await chat(retry_prompt, system=system)
        except BackendError as exc:
            return f"[codebrain error] {exc}"
        output = strip_wrapper_fences(output)
        ok, reason = validate_sections(output)
        if not ok:
            return f"[codebrain error] validation failed after retry: {reason}"

    frontmatter = {
        "source": display_path,
        "source_hash": source_hash,
        "source_mtime": source_mtime,
        "model": used_model,
        "generated_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    brain_content = assemble_brain_file(output, frontmatter)
    brain_path.write_text(brain_content, encoding="utf-8")
    return f"generated: {brain_path}"


def _normalise_extensions(exts: list[str] | None) -> frozenset[str]:
    if exts is None:
        return DEFAULT_SOURCE_EXTENSIONS
    return frozenset(e.lower() if e.startswith(".") else f".{e.lower()}" for e in exts)


def iter_source_files(
    root: Path,
    extensions: list[str] | None = None,
    exclude_dirs: list[str] | None = None,
) -> Iterator[Path]:
    """Yield source files under `root` matching `extensions`, pruning `exclude_dirs`.

    Walks the tree with `os.walk` and mutates the dirs list in-place to prune
    excluded directories before descending. Does NOT yield `.brain` files
    (the extension whitelist takes care of that implicitly).
    """
    ext_set = _normalise_extensions(extensions)
    exclude_set = frozenset(exclude_dirs) if exclude_dirs is not None else DEFAULT_EXCLUDE_DIRS

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in exclude_set]
        for fname in filenames:
            if Path(fname).suffix.lower() in ext_set:
                yield Path(dirpath) / fname


async def scan_repo(
    root: str,
    force: bool = False,
    extensions: list[str] | None = None,
    exclude_dirs: list[str] | None = None,
) -> str:
    """Scan every source file under `root` and generate/refresh its `.brain` file.

    Hash-gated: files whose source hash matches the existing `.brain` are
    skipped without invoking the model. Use `force=True` to override.
    Per-file failures do not abort the batch — they are reported at the end.
    """
    root_path = Path(root)
    if not root_path.exists():
        return f"[codebrain error] root not found: {root}"
    if not root_path.is_dir():
        return f"[codebrain error] root is not a directory: {root}"

    generated: list[str] = []
    skipped: list[str] = []
    failed: list[tuple[str, str]] = []

    for source in iter_source_files(root_path, extensions, exclude_dirs):
        display = resolve_display_path(source)
        result = await scan_file(str(source), force=force)
        if result.startswith("generated:"):
            generated.append(display)
        elif result.startswith("skipped"):
            skipped.append(display)
        else:
            failed.append((display, result))

    total = len(generated) + len(skipped) + len(failed)
    lines = [
        f"Scanned {total} files: {len(generated)} generated, "
        f"{len(skipped)} skipped, {len(failed)} failed."
    ]
    if generated:
        lines.append("\nGenerated:")
        lines.extend(f"  - {p}" for p in generated)
    if failed:
        lines.append("\nFailed:")
        lines.extend(f"  - {p} — {reason}" for p, reason in failed)
    return "\n".join(lines)
