"""Integration tests for verifier-loop and consensus tools at the MCP server layer."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from codebrain import server
from codebrain.backend import BackendError


@pytest.mark.asyncio
async def test_polish_retries_on_noop():
    responses = iter(["Hello world", "Salutations, earth"])

    async def fake_chat(prompt, system="", **kwargs):
        return next(responses)

    with patch.object(server, "chat", side_effect=fake_chat):
        result = await server.codebrain_polish(
            text="Hello world", instructions="be fancier"
        )

    assert result == "Salutations, earth"


@pytest.mark.asyncio
async def test_polish_returns_first_output_when_meaningfully_different():
    async def fake_chat(prompt, system="", **kwargs):
        return "Hey there, planet"

    with patch.object(server, "chat", side_effect=fake_chat):
        result = await server.codebrain_polish(
            text="Hello world", instructions="be casual"
        )

    assert result == "Hey there, planet"


@pytest.mark.asyncio
async def test_generate_verified_returns_first_valid_output():
    async def fake_chat(prompt, system="", **kwargs):
        return "one two three four five"

    with patch.object(server, "chat", side_effect=fake_chat):
        result = await server.codebrain_generate_verified(
            prompt="count", min_words=3, max_words=10
        )

    assert result == "one two three four five"


@pytest.mark.asyncio
async def test_generate_verified_retries_on_word_limit_violation():
    responses = iter(
        ["way too many words here breaks the limit for sure", "one two"]
    )

    async def fake_chat(prompt, system="", **kwargs):
        return next(responses)

    with patch.object(server, "chat", side_effect=fake_chat):
        result = await server.codebrain_generate_verified(
            prompt="count briefly", max_words=3, max_retries=2
        )

    assert result == "one two"


@pytest.mark.asyncio
async def test_generate_verified_gives_up_after_max_retries():
    async def fake_chat(prompt, system="", **kwargs):
        return "way too many words here to fit the tight limit"

    with patch.object(server, "chat", side_effect=fake_chat):
        result = await server.codebrain_generate_verified(
            prompt="x", max_words=2, max_retries=1
        )

    assert result.startswith("[codebrain warning]")
    assert "verification failed" in result


@pytest.mark.asyncio
async def test_generate_verified_surfaces_backend_error():
    async def fake_chat(prompt, system="", **kwargs):
        raise BackendError("ollama down")

    with patch.object(server, "chat", side_effect=fake_chat):
        result = await server.codebrain_generate_verified(prompt="x")

    assert result.startswith("[codebrain error]")


@pytest.mark.asyncio
async def test_consensus_generate_picks_via_judge_call():
    outputs = iter(["draft A", "draft B", "draft C", "draft B"])

    async def fake_chat(prompt, system="", **kwargs):
        return next(outputs)

    with patch.object(server, "chat", side_effect=fake_chat):
        result = await server.codebrain_consensus_generate(prompt="x", n=3)

    assert result == "draft B"


@pytest.mark.asyncio
async def test_consensus_clamps_n_to_range():
    call_count = {"n": 0}

    async def fake_chat(prompt, system="", **kwargs):
        call_count["n"] += 1
        return "x"

    with patch.object(server, "chat", side_effect=fake_chat):
        await server.codebrain_consensus_generate(prompt="p", n=99)

    assert call_count["n"] == 6  # 5 candidates + 1 judge call


@pytest.mark.asyncio
async def test_consensus_surfaces_candidate_failure():
    responses = iter(["ok", BackendError("down")])

    async def fake_chat(prompt, system="", **kwargs):
        r = next(responses)
        if isinstance(r, BackendError):
            raise r
        return r

    with patch.object(server, "chat", side_effect=fake_chat):
        result = await server.codebrain_consensus_generate(prompt="p", n=2)

    assert result.startswith("[codebrain error]")
