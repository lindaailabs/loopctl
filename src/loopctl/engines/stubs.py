"""Engine backend stubs (ADR-0010).

`claude_code` is the only fully implemented backend (see `claude_code.py`).
The remaining backends declared here follow SPEC §1.2:

* ``fake`` — a working, no-op backend used for dry runs and demos. It never
  touches the network or the `claude` binary, so it is safe to run anywhere.
* ``codex`` / ``openhands`` — declared but not implemented. SPEC §1.2 explicitly
  defers these engines to a later phase; attempting to use one raises
  ``NotImplementedError`` with a pointer to the decision.
"""

from __future__ import annotations

from loopctl.engines.base import EngineBackend, EngineContext, EngineResult


class FakeBackend(EngineBackend):
    """No-op backend for dry runs / demos (no network, no subprocess)."""

    _implemented = True
    name = "fake"

    async def execute(self, ctx: EngineContext, prompt: str) -> EngineResult:
        return EngineResult(
            success=True,
            branch="feature/fake",
            changed_files=[],
            stdout_summary="[fake engine] no-op success",
            tokens=0,
            cost_usd=0.0,
            duration_s=0.0,
        )


class _StubBackend(EngineBackend):
    """Placeholder for an engine that is declared but not implemented (SPEC §1.2)."""

    _implemented = False
    name = "stub"

    async def execute(self, ctx: EngineContext, prompt: str) -> EngineResult:
        raise NotImplementedError(
            f"engine '{self.name}' is declared but not implemented; see SPEC §1.2"
        )


class CodexBackend(_StubBackend):
    name = "codex"


class OpenHandsBackend(_StubBackend):
    name = "openhands"
