"""Execution engine abstraction layer."""

from loopctl.engines.base import (
    EngineBackend,
    EngineContext,
    EngineError,
    EngineResult,
)
from loopctl.engines.claude_code import ClaudeCodeBackend
from loopctl.engines.registry import (
    ENGINE_REGISTRY,
    UnknownEngineError,
    get_engine,
    is_implemented,
    register_engine,
)
from loopctl.engines.stubs import CodexBackend, FakeBackend, OpenHandsBackend

__all__ = [
    "EngineBackend",
    "EngineContext",
    "EngineError",
    "EngineResult",
    "ClaudeCodeBackend",
    "FakeBackend",
    "CodexBackend",
    "OpenHandsBackend",
    "ENGINE_REGISTRY",
    "UnknownEngineError",
    "get_engine",
    "is_implemented",
    "register_engine",
]
