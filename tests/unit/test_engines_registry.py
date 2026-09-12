"""Tests for the engine registry and backend stubs (ADR-0010)."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from loopctl.engines import (
    ENGINE_REGISTRY,
    CodexBackend,
    FakeBackend,
    OpenHandsBackend,
    UnknownEngineError,
    get_engine,
    is_implemented,
)
from loopctl.engines.base import EngineContext


def test_registry_lists_known_engines() -> None:
    for name in ("claude_code", "fake", "codex", "openhands"):
        assert name in ENGINE_REGISTRY


def test_get_engine_builds_instance() -> None:
    assert isinstance(get_engine("claude_code"), ENGINE_REGISTRY["claude_code"])
    assert isinstance(get_engine("fake"), FakeBackend)


def test_get_engine_unknown_raises() -> None:
    with pytest.raises(UnknownEngineError):
        get_engine("nope")


def test_is_implemented() -> None:
    assert is_implemented("claude_code")
    assert is_implemented("fake")
    assert not is_implemented("codex")
    assert not is_implemented("openhands")
    assert not is_implemented("nope")


def test_fake_backend_succeeds() -> None:
    async def go() -> None:
        result = await FakeBackend().execute(
            EngineContext(workdir=Path("."), requirement="x", plan="", spec_context=""),
            "prompt",
        )
        assert result.success
        assert result.branch == "feature/fake"

    asyncio.run(go())


def test_stub_backends_not_implemented() -> None:
    async def go() -> None:
        with pytest.raises(NotImplementedError):
            await CodexBackend().execute(
                EngineContext(workdir=Path("."), requirement="x", plan="", spec_context=""),
                "prompt",
            )
        with pytest.raises(NotImplementedError):
            await OpenHandsBackend().execute(
                EngineContext(workdir=Path("."), requirement="x", plan="", spec_context=""),
                "prompt",
            )

    asyncio.run(go())
