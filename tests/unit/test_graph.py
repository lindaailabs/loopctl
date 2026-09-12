"""End-to-end workflow tests driven by a fake engine (no network, no claude)."""

from __future__ import annotations

import asyncio
from pathlib import Path

from loopctl.engines.base import EngineError, EngineResult
from loopctl.graph.workflow import Workflow
from loopctl.models.project import ProjectConfig
from loopctl.models.task import TaskState


async def _noop_notify(message: str) -> None:  # pragma: no cover - test helper
    return None


class FakeEngine:
    name = "fake"

    def __init__(self, fail_with: str | None = None) -> None:
        self.fail_with = fail_with
        self.calls = 0

    async def execute(self, ctx, prompt: str) -> EngineResult:
        self.calls += 1
        if self.fail_with:
            raise EngineError(self.fail_with, "boom")
        return EngineResult(
            success=True,
            branch="feature/x",
            changed_files=["calculator.py"],
            stdout_summary="implemented the change",
            tokens=100,
            cost_usd=0.01,
            duration_s=1.0,
        )


def _wf(
    tmp_data_dir: Path,
    *,
    test_cmd: str = 'python -c "pass"',
    engine=None,
    fix_loop_max: int = 3,
):
    cfg = ProjectConfig(slug="sample", test_cmd=test_cmd, repo_path=str(tmp_data_dir))
    cfg.limits.fix_loop_max = fix_loop_max
    eng = engine or FakeEngine()
    wf = Workflow(
        project=cfg,
        data_dir=tmp_data_dir,
        db_path=tmp_data_dir / "db.sqlite",
        engine=eng,
        notifier=_noop_notify,
    )
    return wf, eng


def test_full_loop_reaches_done(tmp_data_dir) -> None:
    wf, eng = _wf(tmp_data_dir)

    async def go():
        tid = await wf.start("add negative argument validation", None)
        assert wf.store.get(tid).state is TaskState.awaiting_plan_approval
        await wf.approve(tid)
        return tid

    tid = asyncio.run(go())
    task = wf.store.get(tid)
    assert task.state is TaskState.done
    assert (tmp_data_dir / "reports" / f"{tid}.md").exists()
    assert eng.calls >= 2  # planning + executing


def test_reject_returns_to_gate(tmp_data_dir) -> None:
    wf, _ = _wf(tmp_data_dir)

    async def go():
        tid = await wf.start("do something", None)
        await wf.reject(tid, "use a different approach")
        return tid

    tid = asyncio.run(go())
    task = wf.store.get(tid)
    assert task.state is TaskState.awaiting_plan_approval
    assert task.feedback == "use a different approach"


def test_engine_error_escalates(tmp_data_dir) -> None:
    wf, _ = _wf(tmp_data_dir, engine=FakeEngine(fail_with="engine_timeout"))

    async def go():
        tid = await wf.start("do something", None)
        await wf.approve(tid)
        return tid

    tid = asyncio.run(go())
    task = wf.store.get(tid)
    assert task.state is TaskState.escalated
    assert task.failure_class == "engine_timeout"


def test_fixing_loop_reaches_done(tmp_data_dir) -> None:
    counter = tmp_data_dir / "counter.txt"
    script = tmp_data_dir / "fail_twice.py"
    script.write_text(
        "import pathlib, sys\n"
        "p = pathlib.Path(sys.argv[1])\n"
        "n = int(p.read_text()) if p.exists() else 0\n"
        "p.write_text(str(n + 1))\n"
        "sys.exit(0 if n >= 1 else 1)\n",
        encoding="utf-8",
    )
    test_cmd = f'python "{script}" "{counter}"'
    wf, _ = _wf(tmp_data_dir, test_cmd=test_cmd)

    async def go():
        tid = await wf.start("do something", None)
        await wf.approve(tid)
        return tid

    tid = asyncio.run(go())
    task = wf.store.get(tid)
    assert task.state is TaskState.done
    assert task.fix_loops >= 1


def test_resume_from_gate_reaches_done(tmp_data_dir) -> None:
    wf, _ = _wf(tmp_data_dir)

    async def go():
        tid = await wf.start("do something", None)
        await wf.resume(tid)  # resume at the gate behaves like approve
        return tid

    tid = asyncio.run(go())
    assert wf.store.get(tid).state is TaskState.done
