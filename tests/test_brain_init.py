"""Unit tests for the one-shot repo initialiser."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from codebrain import brain_init as bi


# ---------- extension counting ----------


def test_count_extensions_filters_and_counts(tmp_path: Path):
    (tmp_path / "a.py").write_text("", encoding="utf-8")
    (tmp_path / "b.py").write_text("", encoding="utf-8")
    (tmp_path / "c.ts").write_text("", encoding="utf-8")
    (tmp_path / "d.md").write_text("", encoding="utf-8")  # not a source ext
    counts = bi.count_extensions(tmp_path)
    assert counts[".py"] == 2
    assert counts[".ts"] == 1
    assert ".md" not in counts


def test_count_extensions_prunes_excluded_dirs(tmp_path: Path):
    (tmp_path / "keep.py").write_text("", encoding="utf-8")
    (tmp_path / ".venv").mkdir()
    (tmp_path / ".venv" / "nope.py").write_text("", encoding="utf-8")
    counts = bi.count_extensions(tmp_path)
    assert counts[".py"] == 1


# ---------- marker detection ----------


def test_detect_markers_finds_pyproject(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text("", encoding="utf-8")
    assert "pyproject.toml" in bi.detect_markers(tmp_path)


def test_detect_markers_finds_multiple(tmp_path: Path):
    (tmp_path / "package.json").write_text("{}", encoding="utf-8")
    (tmp_path / "tsconfig.json").write_text("{}", encoding="utf-8")
    markers = bi.detect_markers(tmp_path)
    assert "package.json" in markers
    assert "tsconfig.json" in markers


def test_detect_markers_empty_when_none_present(tmp_path: Path):
    (tmp_path / "random.txt").write_text("", encoding="utf-8")
    assert bi.detect_markers(tmp_path) == []


# ---------- stack inference ----------


def test_infer_stacks_python():
    assert bi.infer_stacks(["pyproject.toml"]) == ["python"]


def test_infer_stacks_typescript_and_javascript():
    stacks = bi.infer_stacks(["package.json", "tsconfig.json"])
    assert "javascript" in stacks
    assert "typescript" in stacks


def test_infer_stacks_empty_when_no_markers():
    assert bi.infer_stacks([]) == []


# ---------- top-level dirs ----------


def test_list_top_level_dirs_filters_hidden_and_excluded(tmp_path: Path):
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / ".git").mkdir()
    (tmp_path / "node_modules").mkdir()
    dirs = bi.list_top_level_dirs(tmp_path)
    assert dirs == ["src", "tests"]


# ---------- context.md builder ----------


def test_build_context_md_contains_all_sections():
    content = bi.build_context_md(
        project_name="myproj",
        overview="A project that does stuff.",
        stacks=["python"],
        markers=["pyproject.toml"],
        top_extensions=[(".py", 10), (".md", 2)],
        total_source_files=12,
        generated_at="2026-04-19T00:00:00Z",
    )
    assert "# myproj — project context" in content
    assert "## Overview" in content
    assert "## Stack" in content
    assert "## Top extensions" in content
    assert "## Notes for Claude" in content
    assert "A project that does stuff." in content
    assert "`.py` — 10 files" in content


def test_build_context_md_handles_empty_markers():
    content = bi.build_context_md(
        project_name="myproj",
        overview="ov",
        stacks=[],
        markers=[],
        top_extensions=[],
        total_source_files=0,
        generated_at="2026-04-19T00:00:00Z",
    )
    assert "_unknown_" in content
    assert "_None._" in content


# ---------- init_repo orchestrator ----------


@pytest.mark.asyncio
async def test_init_repo_errors_on_missing_root(tmp_path: Path):
    result = await bi.init_repo(str(tmp_path / "nope"))
    assert result.startswith("[codebrain error]")
    assert "not found" in result


@pytest.mark.asyncio
async def test_init_repo_errors_when_root_is_file(tmp_path: Path):
    f = tmp_path / "x.py"
    f.write_text("", encoding="utf-8")
    result = await bi.init_repo(str(f))
    assert result.startswith("[codebrain error]")
    assert "not a directory" in result


@pytest.mark.asyncio
async def test_init_repo_writes_context_md(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text("", encoding="utf-8")
    (tmp_path / "main.py").write_text("print('hi')", encoding="utf-8")

    async def fake_chat(prompt, system="", **kwargs):
        return "A Python project for doing things."

    with patch.object(bi, "chat", side_effect=fake_chat):
        result = await bi.init_repo(str(tmp_path))

    assert "Initialized" in result
    context = tmp_path / ".brain" / "context.md"
    assert context.exists()
    text = context.read_text(encoding="utf-8")
    assert "A Python project for doing things." in text
    assert "pyproject.toml" in text
    assert "## Notes for Claude" in text


@pytest.mark.asyncio
async def test_init_repo_is_idempotent_without_force(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text("", encoding="utf-8")
    brain_dir = tmp_path / ".brain"
    brain_dir.mkdir()
    existing = brain_dir / "context.md"
    existing.write_text("ORIGINAL CONTENT", encoding="utf-8")

    async def fake_chat(prompt, system="", **kwargs):
        pytest.fail("chat should not be called when context.md already exists")

    with patch.object(bi, "chat", side_effect=fake_chat):
        result = await bi.init_repo(str(tmp_path))

    assert "already initialized" in result
    assert existing.read_text(encoding="utf-8") == "ORIGINAL CONTENT"


@pytest.mark.asyncio
async def test_init_repo_force_overwrites(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text("", encoding="utf-8")
    brain_dir = tmp_path / ".brain"
    brain_dir.mkdir()
    existing = brain_dir / "context.md"
    existing.write_text("STALE", encoding="utf-8")

    async def fake_chat(prompt, system="", **kwargs):
        return "Fresh overview."

    with patch.object(bi, "chat", side_effect=fake_chat):
        result = await bi.init_repo(str(tmp_path), force=True)

    assert "Initialized" in result
    assert "Fresh overview." in existing.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_init_repo_falls_back_when_ollama_down(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text("", encoding="utf-8")
    (tmp_path / "a.py").write_text("", encoding="utf-8")

    async def fake_chat(prompt, system="", **kwargs):
        raise bi.BackendError("ollama down")

    with patch.object(bi, "chat", side_effect=fake_chat):
        result = await bi.init_repo(str(tmp_path))

    assert "Initialized" in result
    context = (tmp_path / ".brain" / "context.md").read_text(encoding="utf-8")
    assert "python project" in context.lower()
