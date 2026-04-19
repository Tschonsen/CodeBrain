"""Unit tests for the brain-file scanner."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from codebrain import brain_scanner as bs


FAKE_SECTIONS = (
    "## Purpose\n\nDoes things.\n\n"
    "## Key exports\n\n- `foo` — does foo.\n\n"
    "## Collaborators\n\n- `other.py` — calls `foo`.\n\n"
    "## Gotchas\n\n_None._\n\n"
    "## Conventions\n\n- Async style.\n"
)


# ---------- hash helper ----------


def test_compute_source_hash_is_deterministic():
    h1 = bs.compute_source_hash(b"hello world")
    h2 = bs.compute_source_hash(b"hello world")
    assert h1 == h2
    assert h1.startswith("sha256:")
    assert len(h1) == len("sha256:") + 64


def test_compute_source_hash_differs_on_content_change():
    assert bs.compute_source_hash(b"hello") != bs.compute_source_hash(b"world")


# ---------- frontmatter parser ----------


def test_parse_existing_brain_returns_none_for_missing_file(tmp_path: Path):
    assert bs.parse_existing_brain(tmp_path / "absent.brain") is None


def test_parse_existing_brain_returns_none_for_no_frontmatter(tmp_path: Path):
    brain = tmp_path / "f.brain"
    brain.write_text("## Purpose\nJust body.\n", encoding="utf-8")
    assert bs.parse_existing_brain(brain) is None


def test_parse_existing_brain_returns_frontmatter_dict(tmp_path: Path):
    brain = tmp_path / "f.brain"
    brain.write_text(
        "---\nsource: a/b.py\nsource_hash: sha256:abc\n---\n## Purpose\nBody.\n",
        encoding="utf-8",
    )
    fm = bs.parse_existing_brain(brain)
    assert fm == {"source": "a/b.py", "source_hash": "sha256:abc"}


def test_parse_existing_brain_returns_none_for_broken_yaml(tmp_path: Path):
    brain = tmp_path / "f.brain"
    brain.write_text(
        "---\nthis is: :: not yaml:::\n---\n## Purpose\n",
        encoding="utf-8",
    )
    assert bs.parse_existing_brain(brain) is None


# ---------- validator ----------

GOOD_BRAIN = """---
source: x.py
source_hash: sha256:000
source_mtime: 2026-04-19T00:00:00Z
model: qwen2.5-coder:14b
generated_at: 2026-04-19T00:00:00Z
---

## Purpose

Does things.

## Key exports

- `foo` — does foo.

## Collaborators

- `other.py` — calls `foo`.

## Gotchas

_None._

## Conventions

- Async style.
"""


def test_validator_accepts_valid_brain():
    ok, reason = bs.validate_brain_output(GOOD_BRAIN)
    assert ok, reason


def test_validator_rejects_missing_frontmatter():
    text = "## Purpose\nFoo.\n## Key exports\n- x\n## Collaborators\n-x\n## Gotchas\nx\n## Conventions\nx\n"
    ok, reason = bs.validate_brain_output(text)
    assert not ok
    assert "frontmatter" in reason.lower()


def test_validator_rejects_missing_required_key():
    text = GOOD_BRAIN.replace("model: qwen2.5-coder:14b\n", "")
    ok, reason = bs.validate_brain_output(text)
    assert not ok
    assert "model" in reason


def test_validator_rejects_missing_section():
    text = GOOD_BRAIN.replace("## Gotchas\n\n_None._\n\n", "")
    ok, reason = bs.validate_brain_output(text)
    assert not ok
    assert "Gotchas" in reason


def test_validator_rejects_empty_section():
    text = GOOD_BRAIN.replace("_None._", "").replace("## Gotchas\n\n\n", "## Gotchas\n\n")
    ok, reason = bs.validate_brain_output(text)
    assert not ok
    assert "Gotchas" in reason or "empty" in reason.lower()


def test_validator_accepts_matching_expected_frontmatter():
    expected = {
        "source": "x.py",
        "source_hash": "sha256:000",
        "model": "qwen2.5-coder:14b",
    }
    ok, reason = bs.validate_brain_output(GOOD_BRAIN, expected=expected)
    assert ok, reason


def test_validator_rejects_mismatched_source_hash():
    expected = {
        "source": "x.py",
        "source_hash": "sha256:deadbeef",
        "model": "qwen2.5-coder:14b",
    }
    ok, reason = bs.validate_brain_output(GOOD_BRAIN, expected=expected)
    assert not ok
    assert "source_hash" in reason


def test_validator_rejects_mismatched_source_path():
    expected = {
        "source": "y.py",
        "source_hash": "sha256:000",
        "model": "qwen2.5-coder:14b",
    }
    ok, reason = bs.validate_brain_output(GOOD_BRAIN, expected=expected)
    assert not ok
    assert "source" in reason


def test_validator_rejects_mismatched_model():
    expected = {
        "source": "x.py",
        "source_hash": "sha256:000",
        "model": "gpt-4",
    }
    ok, reason = bs.validate_brain_output(GOOD_BRAIN, expected=expected)
    assert not ok
    assert "model" in reason


def test_validator_rejects_wrong_section_order():
    swapped = GOOD_BRAIN.replace(
        "## Key exports\n\n- `foo` — does foo.\n\n## Collaborators\n\n- `other.py` — calls `foo`.",
        "## Collaborators\n\n- `other.py` — calls `foo`.\n\n## Key exports\n\n- `foo` — does foo.",
    )
    ok, reason = bs.validate_brain_output(swapped)
    assert not ok


# ---------- fence stripper ----------


def test_strip_wrapper_fences_removes_markdown_fence():
    wrapped = "```markdown\n---\nfoo: bar\n---\n## Purpose\nhi.\n```"
    stripped = bs.strip_wrapper_fences(wrapped)
    assert stripped.startswith("---\n")
    assert "```" not in stripped
    assert stripped.endswith("\n")


def test_strip_wrapper_fences_removes_plain_fence():
    wrapped = "```\n---\nfoo: bar\n---\n## Purpose\nhi.\n```"
    stripped = bs.strip_wrapper_fences(wrapped)
    assert stripped.startswith("---\n")
    assert "```" not in stripped


def test_strip_wrapper_fences_passes_through_unfenced():
    text = "---\nfoo: bar\n---\n## Purpose\nhi.\n"
    assert bs.strip_wrapper_fences(text) == text


def test_strip_wrapper_fences_leaves_half_fenced_alone():
    text = "```\n---\nfoo: bar\n---\n"
    assert bs.strip_wrapper_fences(text) == text


# ---------- display path resolver ----------


def test_resolve_display_path_returns_posix_relative_under_root(tmp_path: Path):
    src = tmp_path / "pkg" / "mod.py"
    src.parent.mkdir()
    src.write_text("pass\n", encoding="utf-8")
    assert bs.resolve_display_path(src, tmp_path) == "pkg/mod.py"


def test_resolve_display_path_falls_back_to_absolute_when_outside_root(tmp_path: Path):
    outside = tmp_path / "outside.py"
    outside.write_text("pass\n", encoding="utf-8")
    other_root = tmp_path / "root"
    other_root.mkdir()
    result = bs.resolve_display_path(outside, other_root)
    assert result.endswith("outside.py")
    assert "\\" not in result


def test_find_repo_root_finds_pyproject_in_parent(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text("", encoding="utf-8")
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    src = pkg / "mod.py"
    src.write_text("pass\n", encoding="utf-8")
    assert bs.find_repo_root(src) == tmp_path.resolve()


def test_find_repo_root_finds_git_marker(tmp_path: Path):
    (tmp_path / ".git").mkdir()
    src = tmp_path / "deep" / "nested" / "file.py"
    src.parent.mkdir(parents=True)
    src.write_text("pass\n", encoding="utf-8")
    assert bs.find_repo_root(src) == tmp_path.resolve()


def test_resolve_display_path_uses_discovery_when_no_explicit_root(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text("", encoding="utf-8")
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    src = pkg / "mod.py"
    src.write_text("pass\n", encoding="utf-8")
    assert bs.resolve_display_path(src) == "pkg/mod.py"


# ---------- prompt building ----------


def test_system_prompt_contains_few_shot_and_rules():
    system = bs.build_system_prompt("FEWSHOT_MARKER")
    assert "FEWSHOT_MARKER" in system
    assert "## Purpose" in system
    assert "## Conventions" in system


def test_system_prompt_dictates_none_form():
    system = bs.build_system_prompt("FEWSHOT")
    assert "`_None._`" in system
    assert "- None" in system  # mentioned as a forbidden form


def test_system_prompt_forbids_signatures():
    system = bs.build_system_prompt("FEWSHOT")
    assert "Name only" in system
    assert "no parens" in system
    assert "no parameters" in system


def test_system_prompt_distinguishes_code_vs_output_conventions():
    system = bs.build_system_prompt("FEWSHOT")
    assert "code in this file" in system.lower()
    assert "not the format of any output" in system.lower()


def test_system_prompt_directs_collaborators_to_import_statements():
    system = bs.build_system_prompt("FEWSHOT")
    assert "import statements" in system.lower()


def test_system_prompt_forbids_frontmatter_in_output():
    system = bs.build_system_prompt("FEWSHOT")
    assert "Do NOT" in system
    assert "YAML frontmatter" in system


def test_user_prompt_contains_source_path_and_content():
    prompt = bs.build_user_prompt(
        source_path="pkg/x.py",
        source_content="print('hi')",
    )
    assert "pkg/x.py" in prompt
    assert "print('hi')" in prompt


# ---------- assemble_brain_file ----------


def test_assemble_brain_file_prepends_frontmatter():
    frontmatter = {
        "source": "pkg/x.py",
        "source_hash": "sha256:abc",
        "source_mtime": "2026-04-19T00:00:00Z",
        "model": "qwen2.5-coder:14b",
        "generated_at": "2026-04-19T00:00:00Z",
    }
    result = bs.assemble_brain_file(FAKE_SECTIONS, frontmatter)
    assert result.startswith("---\n")
    assert "source: pkg/x.py" in result
    assert "source_hash: sha256:abc" in result
    assert "## Purpose" in result
    assert result.endswith("\n")
    ok, reason = bs.validate_brain_output(result)
    assert ok, reason


# ---------- validate_sections ----------


def test_validate_sections_accepts_valid_sections():
    ok, reason = bs.validate_sections(FAKE_SECTIONS)
    assert ok, reason


def test_validate_sections_rejects_missing_section():
    stripped = FAKE_SECTIONS.replace("## Gotchas\n\n_None._\n\n", "")
    ok, reason = bs.validate_sections(stripped)
    assert not ok
    assert "Gotchas" in reason


def test_validate_sections_rejects_empty_section():
    broken = FAKE_SECTIONS.replace("_None._", "")
    ok, reason = bs.validate_sections(broken)
    assert not ok


def test_validate_sections_rejects_wrong_order():
    swapped = FAKE_SECTIONS.replace(
        "## Key exports\n\n- `foo` — does foo.\n\n## Collaborators\n\n- `other.py` — calls `foo`.",
        "## Collaborators\n\n- `other.py` — calls `foo`.\n\n## Key exports\n\n- `foo` — does foo.",
    )
    ok, reason = bs.validate_sections(swapped)
    assert not ok


# ---------- scan_file integration (with mocked chat) ----------


@pytest.mark.asyncio
async def test_scan_file_returns_error_when_source_missing(tmp_path: Path):
    result = await bs.scan_file(str(tmp_path / "nope.py"))
    assert result.startswith("[codebrain error]")
    assert "not found" in result


@pytest.mark.asyncio
async def test_scan_file_skips_empty_source(tmp_path: Path):
    src = tmp_path / "empty.py"
    src.write_text("", encoding="utf-8")

    call_count = {"n": 0}

    async def fake_chat(prompt, system="", **kwargs):
        call_count["n"] += 1
        return GOOD_BRAIN

    with patch.object(bs, "chat", side_effect=fake_chat):
        result = await bs.scan_file(str(src))

    assert result.startswith("skipped (source too small)"), result
    assert call_count["n"] == 0
    assert not src.with_name(src.name + ".brain").exists()


@pytest.mark.asyncio
async def test_scan_file_skips_whitespace_only_source(tmp_path: Path):
    src = tmp_path / "blank.py"
    src.write_text("   \n\n\t\n", encoding="utf-8")

    async def fake_chat(prompt, system="", **kwargs):
        pytest.fail("chat should not be called for whitespace-only source")

    with patch.object(bs, "chat", side_effect=fake_chat):
        result = await bs.scan_file(str(src))

    assert result.startswith("skipped (source too small)"), result


@pytest.mark.asyncio
async def test_scan_file_processes_small_but_meaningful_source(tmp_path: Path):
    src = tmp_path / "tiny.py"
    src.write_text("from .x import y\n", encoding="utf-8")  # 17 chars

    async def fake_chat(prompt, system="", **kwargs):
        return FAKE_SECTIONS

    with patch.object(bs, "chat", side_effect=fake_chat):
        result = await bs.scan_file(str(src))

    assert result.startswith("generated:"), result


@pytest.mark.asyncio
async def test_scan_file_writes_brain_when_absent(tmp_path: Path):
    src = tmp_path / "hello.py"
    src_bytes = b"def greet(): pass\n"
    src.write_bytes(src_bytes)
    expected_hash = bs.compute_source_hash(src_bytes)

    async def fake_chat(prompt, system="", **kwargs):
        return FAKE_SECTIONS

    with patch.object(bs, "chat", side_effect=fake_chat):
        result = await bs.scan_file(str(src))

    assert result.startswith("generated:"), result
    brain = src.with_name(src.name + ".brain")
    content = brain.read_text(encoding="utf-8")
    assert content.startswith("---\n")
    assert f"source_hash: {expected_hash}" in content
    assert "## Purpose" in content
    assert "## Conventions" in content
    ok, reason = bs.validate_brain_output(content)
    assert ok, reason


@pytest.mark.asyncio
async def test_scan_file_skips_when_hash_matches(tmp_path: Path):
    src = tmp_path / "hello.py"
    src_bytes = b"def greet(): pass\n"
    src.write_bytes(src_bytes)
    expected_hash = bs.compute_source_hash(src_bytes)

    brain = src.with_name(src.name + ".brain")
    brain.write_text(
        GOOD_BRAIN.replace("sha256:000", expected_hash), encoding="utf-8"
    )

    call_count = {"n": 0}

    async def fake_chat(prompt, system="", **kwargs):
        call_count["n"] += 1
        return GOOD_BRAIN

    with patch.object(bs, "chat", side_effect=fake_chat):
        result = await bs.scan_file(str(src))

    assert result.startswith("skipped"), result
    assert call_count["n"] == 0, "chat should not be called when hash matches"


@pytest.mark.asyncio
async def test_scan_file_regenerates_when_hash_differs(tmp_path: Path):
    src = tmp_path / "hello.py"
    src.write_text("def greet(): return 1\n", encoding="utf-8")

    brain = src.with_name(src.name + ".brain")
    # existing brain with stale hash
    brain.write_text(
        GOOD_BRAIN.replace("sha256:000", "sha256:deadbeef"), encoding="utf-8"
    )

    async def fake_chat(prompt, system="", **kwargs):
        return FAKE_SECTIONS

    with patch.object(bs, "chat", side_effect=fake_chat):
        result = await bs.scan_file(str(src))

    assert result.startswith("generated:"), result


@pytest.mark.asyncio
async def test_scan_file_preserves_foreign_model_brain_under_force_false(tmp_path: Path):
    src = tmp_path / "hello.py"
    src.write_text("def greet(): pass\n", encoding="utf-8")

    brain = src.with_name(src.name + ".brain")
    brain.write_text(
        GOOD_BRAIN.replace("model: qwen2.5-coder:14b", "model: claude-inline"),
        encoding="utf-8",
    )

    async def fake_chat(prompt, system="", **kwargs):
        pytest.fail("chat must not be called when a foreign-model brain exists")

    with patch.object(bs, "chat", side_effect=fake_chat):
        result = await bs.scan_file(str(src))

    assert result.startswith("skipped (foreign-model brain preserved"), result


@pytest.mark.asyncio
async def test_scan_file_overwrites_foreign_model_brain_under_force_true(tmp_path: Path):
    src = tmp_path / "hello.py"
    src.write_text("def greet(): pass\n", encoding="utf-8")

    brain = src.with_name(src.name + ".brain")
    brain.write_text(
        GOOD_BRAIN.replace("model: qwen2.5-coder:14b", "model: claude-inline"),
        encoding="utf-8",
    )

    async def fake_chat(prompt, system="", **kwargs):
        return FAKE_SECTIONS

    with patch.object(bs, "chat", side_effect=fake_chat):
        result = await bs.scan_file(str(src), force=True)

    assert result.startswith("generated:"), result


@pytest.mark.asyncio
async def test_scan_file_force_regenerates_even_on_hash_match(tmp_path: Path):
    src = tmp_path / "hello.py"
    src_bytes = b"def greet(): pass\n"
    src.write_bytes(src_bytes)
    expected_hash = bs.compute_source_hash(src_bytes)

    brain = src.with_name(src.name + ".brain")
    brain.write_text(
        GOOD_BRAIN.replace("sha256:000", expected_hash), encoding="utf-8"
    )

    call_count = {"n": 0}

    async def fake_chat(prompt, system="", **kwargs):
        call_count["n"] += 1
        return FAKE_SECTIONS

    with patch.object(bs, "chat", side_effect=fake_chat):
        result = await bs.scan_file(str(src), force=True)

    assert result.startswith("generated:"), result
    assert call_count["n"] == 1


@pytest.mark.asyncio
async def test_scan_file_retries_on_invalid_then_succeeds(tmp_path: Path):
    src = tmp_path / "hello.py"
    src.write_text("def greet(): pass\n", encoding="utf-8")

    call_count = {"n": 0}

    async def fake_chat(prompt, system="", **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return "not a valid brain file"
        return FAKE_SECTIONS

    with patch.object(bs, "chat", side_effect=fake_chat):
        result = await bs.scan_file(str(src))

    assert result.startswith("generated:"), result


@pytest.mark.asyncio
async def test_scan_file_fails_after_two_invalid_outputs(tmp_path: Path):
    src = tmp_path / "hello.py"
    src.write_text("def greet(): pass\n", encoding="utf-8")

    async def fake_chat(prompt, system="", **kwargs):
        return "still broken"

    with patch.object(bs, "chat", side_effect=fake_chat):
        result = await bs.scan_file(str(src))

    assert result.startswith("[codebrain error]"), result
    brain = src.with_name(src.name + ".brain")
    assert not brain.exists(), "should not write broken brain"


@pytest.mark.asyncio
async def test_scan_file_accepts_fenced_output_from_model(tmp_path: Path):
    src = tmp_path / "hello.py"
    src.write_text("def greet(): pass\n", encoding="utf-8")

    async def fake_chat(prompt, system="", **kwargs):
        return f"```markdown\n{FAKE_SECTIONS}```"

    with patch.object(bs, "chat", side_effect=fake_chat):
        result = await bs.scan_file(str(src))

    assert result.startswith("generated:"), result
    brain = src.with_name(src.name + ".brain")
    content = brain.read_text(encoding="utf-8")
    assert not content.startswith("```")
    assert content.startswith("---\n")


# ---------- iter_source_files ----------


def test_iter_source_files_filters_by_default_extensions(tmp_path: Path):
    (tmp_path / "a.py").write_text("x=1", encoding="utf-8")
    (tmp_path / "b.ts").write_text("x=1", encoding="utf-8")
    (tmp_path / "c.md").write_text("x=1", encoding="utf-8")
    (tmp_path / "d.lock").write_text("x=1", encoding="utf-8")
    names = sorted(p.name for p in bs.iter_source_files(tmp_path))
    assert names == ["a.py", "b.ts"]


def test_iter_source_files_prunes_excluded_dirs(tmp_path: Path):
    (tmp_path / "keep").mkdir()
    (tmp_path / "keep" / "a.py").write_text("x=1", encoding="utf-8")
    (tmp_path / ".venv").mkdir()
    (tmp_path / ".venv" / "b.py").write_text("x=1", encoding="utf-8")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "c.js").write_text("x=1", encoding="utf-8")
    names = sorted(p.name for p in bs.iter_source_files(tmp_path))
    assert names == ["a.py"]


def test_iter_source_files_skips_brain_files(tmp_path: Path):
    (tmp_path / "a.py").write_text("x=1", encoding="utf-8")
    (tmp_path / "a.py.brain").write_text("---\n---\n", encoding="utf-8")
    names = sorted(p.name for p in bs.iter_source_files(tmp_path))
    assert names == ["a.py"]


def test_iter_source_files_respects_custom_extensions(tmp_path: Path):
    (tmp_path / "a.py").write_text("x=1", encoding="utf-8")
    (tmp_path / "b.rb").write_text("x=1", encoding="utf-8")
    names = sorted(p.name for p in bs.iter_source_files(tmp_path, extensions=[".rb"]))
    assert names == ["b.rb"]


# ---------- scan_repo ----------


@pytest.mark.asyncio
async def test_scan_repo_errors_on_missing_root(tmp_path: Path):
    result = await bs.scan_repo(str(tmp_path / "nope"))
    assert result.startswith("[codebrain error]")
    assert "not found" in result


@pytest.mark.asyncio
async def test_scan_repo_errors_when_root_is_file(tmp_path: Path):
    f = tmp_path / "x.py"
    f.write_text("x=1", encoding="utf-8")
    result = await bs.scan_repo(str(f))
    assert result.startswith("[codebrain error]")
    assert "not a directory" in result


@pytest.mark.asyncio
async def test_scan_repo_aggregates_generated_skipped_failed(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text("", encoding="utf-8")
    (tmp_path / "pkg").mkdir()

    # file 1: fresh → generated
    fresh = tmp_path / "pkg" / "fresh.py"
    fresh.write_text("def a(): pass\n", encoding="utf-8")

    # file 2: already has matching brain → skipped
    cached = tmp_path / "pkg" / "cached.py"
    cached_bytes = b"def b(): pass\n"
    cached.write_bytes(cached_bytes)
    cached_brain = cached.with_name(cached.name + ".brain")
    cached_brain.write_text(
        GOOD_BRAIN.replace("sha256:000", bs.compute_source_hash(cached_bytes)),
        encoding="utf-8",
    )

    # file 3: model returns junk both times → failed
    broken = tmp_path / "pkg" / "broken.py"
    broken.write_text("def c(): pass\n", encoding="utf-8")

    async def fake_chat(prompt, system="", **kwargs):
        if "broken.py" in prompt:
            return "garbage"
        return FAKE_SECTIONS

    with patch.object(bs, "chat", side_effect=fake_chat):
        result = await bs.scan_repo(str(tmp_path))

    assert "Scanned 3 files" in result
    assert "1 generated" in result
    assert "1 skipped" in result
    assert "1 failed" in result
    assert "pkg/fresh.py" in result
    assert "pkg/broken.py" in result


@pytest.mark.asyncio
async def test_scan_file_surfaces_backend_error(tmp_path: Path):
    src = tmp_path / "hello.py"
    src.write_text("def hello(): return 1\n", encoding="utf-8")

    async def fake_chat(prompt, system="", **kwargs):
        raise bs.BackendError("ollama down")

    with patch.object(bs, "chat", side_effect=fake_chat):
        result = await bs.scan_file(str(src))

    assert result.startswith("[codebrain error]")
    assert "ollama down" in result
