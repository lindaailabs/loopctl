"""Engine registry: maps engine name -> backend class (ADR-0010).

Centralizing engine discovery here means a project's ``engine = "..."`` string in
``project.toml`` resolves to a concrete backend at runtime, and `loopctl init`
/ `load_project` can validate the name without hard-coding the list.
"""

from __future__ import annotations

from loopctl.engines.base import EngineBackend
from loopctl.engines.claude_code import ClaudeCodeBackend
from loopctl.engines.stubs import CodexBackend, FakeBackend, OpenHandsBackend

ENGINE_REGISTRY: dict[str, type[EngineBackend]] = {
    "claude_code": ClaudeCodeBackend,
    "fake": FakeBackend,
    "codex": CodexBackend,
    "openhands": OpenHandsBackend,
}


class UnknownEngineError(ValueError):
    """Raised when a project references an engine name not present in the registry."""


def register_engine(name: str, cls: type[EngineBackend]) -> None:
    """Register (or override) an engine backend by name."""
    ENGINE_REGISTRY[name] = cls


def get_engine(name: str, **kwargs: object) -> EngineBackend:
    """Return an instance of the backend registered under ``name``."""
    cls = ENGINE_REGISTRY.get(name)
    if cls is None:
        raise UnknownEngineError(
            f"unknown engine '{name}'; known engines: {', '.join(sorted(ENGINE_REGISTRY))}"
        )
    return cls(**kwargs)


def is_implemented(name: str) -> bool:
    """Whether the registered backend is runnable (vs. a declared stub)."""
    cls = ENGINE_REGISTRY.get(name)
    if cls is None:
        return False
    return bool(getattr(cls, "_implemented", True))
