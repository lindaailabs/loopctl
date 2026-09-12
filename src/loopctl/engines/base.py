"""Engine abstraction — the single source of truth for multi-engine support.

`engines/` performs only process lifecycle, stream parsing, timeout and heartbeat
detection. All prompt assembly happens in `knowledge/`; `engines/` makes no
business decisions (SPEC §4.1).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, runtime_checkable


class EngineError(Exception):
    """Raised by a backend when execution fails in a classified way.

    `kind` matches the failure classes in SPEC §5.3:
    ``engine_timeout`` | ``agent_stuck``.
    """

    def __init__(self, kind: str, message: str = "") -> None:
        super().__init__(message or kind)
        self.kind = kind


@dataclass
class EngineContext:
    workdir: Path
    requirement: str
    plan: str
    spec_context: str
    timeout_min: float = 30.0
    budget_usd: float = 5.0
    heartbeat_idle_min: float = 10.0


@dataclass
class EngineResult:
    success: bool
    branch: str | None = None
    changed_files: list[str] = field(default_factory=list)
    stdout_summary: str = ""
    tokens: int = 0
    cost_usd: float = 0.0
    duration_s: float = 0.0


@runtime_checkable
class EngineBackend(Protocol):
    name: str

    async def execute(self, ctx: EngineContext, prompt: str) -> EngineResult:
        """Run one execution step and return its result."""
        ...
