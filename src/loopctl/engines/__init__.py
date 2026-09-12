"""Execution engine abstraction layer."""

from loopctl.engines.base import (
    EngineBackend,
    EngineContext,
    EngineError,
    EngineResult,
)
from loopctl.engines.claude_code import ClaudeCodeBackend

__all__ = [
    "EngineBackend",
    "EngineContext",
    "EngineError",
    "EngineResult",
    "ClaudeCodeBackend",
]
