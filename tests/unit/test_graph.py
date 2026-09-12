"""End-to-end workflow tests driven by a fake engine (no network, no claude)."""

from __future__ import annotations

import asyncio
from pathlib import Path

from loopctl.engines.base import EngineError, EngineResult
from loopctl.graph.workflow import Workflow
from loopctl.integrations.gitlab import GitLabError, MRInfo
from loopctl.models.project import ProjectConfig
from loopctl.models.task import TaskState


async def _noop_notify(message: str) -> None:  # pragma: no cover - test helper
    return None


class FakeEngine:
    name = "fake"

    def __init__(
        self,
        fail_with: str | None = None,
        *,
        fail_times: int = 0,
        cost_usd: float = 0.01,
        branch: str = "feature/x",
    ) -> None:
        self.fail_with = fail_with
        self.fail_times = fail_times  # number of leading calls that should fail
        self.cost_usd = cost_usd
        self.branch = branch
        self.calls = 0

    async def execute(self, ctx, prompt: str) -> EngineResult:
        self.calls += 1
        # Timed-retry mode: fail only execution attempts (skip planning = call #1).
        if self.fail_times > 0 and self.calls > 1:
            self.fail_times -= 1
            raise EngineError(self.fail_with or "engine_timeout", "boom")
        # Always-fail mode (force an escalation at the first node).
        if self.fail_with and self.fail_times == 0 and self.calls == 1:
            raise EngineError(self.fail_with, "boom")
        return EngineResult(
            success=True,
            branch=self.branch,
            changed_files=["calculator.py"],
            stdout_summary="implemented the change",
            tokens=100,
            cost_usd=self.cost_usd,
            duration_s=1.0,
        )


class FakeGitLab:
    name = "fake_gitlab"
    push_calls = 0
    mr_calls = 0
    fail_mr_with: str | None = None

    def __init__(self, *, fail_mr_with: str | None = None) -> None:
        self.fail_mr_with = fail_mr_with

    async def push_branch(self, *, workdir, branch, remote="origin") -> None:
        FakeGitLab.push_calls += 1

    async def open_mr(
        self, *, project_id, source_branch, target_branch, title, description
    ) -> MRInfo:
        FakeGitLab.mr_calls += 1
        if self.fail_mr_with:
            raise GitLabError(self.fail_mr_with, "boom")
        return MRInfo(
            url=f"https://gl/-/merge_requests/{FakeGitLab.mr_calls}", iid=FakeGitLab.mr_calls
        )


def _wf(
    tmp_data_dir: Path,
    *,
    test_cmd: str = 'python -c "pass"',
    engine=None,
    gitlab=None,
    fix_loop_max: int = 3,
    budget_usd: float = 5.0,
    exec_retry_max: int = 1,
):
    cfg = ProjectConfig(
        slug="sample",
        test_cmd=test_cmd,
        repo_path=str(tmp_data_dir),
        gitlab_project_id=123,
        spec_refs=["spec.md"],
    )
    cfg.limits.fix_loop_max = fix_loop_max
    cfg.limits.budget_usd = budget_usd
    cfg.limits.exec_retry_max = exec_retry_max
    eng = engine or FakeEngine()
    gl = gitlab or FakeGitLab()
    wf = Workflow(
        project=cfg,
        data_dir=tmp_data_dir,
        db_path=tmp_data_dir / "db.sqlite",
        engine=eng,
        notifier=_noop_notify,
        gitlab=gl,
    )
    return wf, eng, gl


def test_full_loop_reaches_done(tmp_data_dir) -> None:
    wf, eng, _ = _wf(tmp_data_dir)

    async def go():
        tid = await wf.start("add negative argument validation", None)
        assert wf.store.get(tid).state is TaskState.awaiting_plan_approval
        await wf.approve(tid)
        assert wf.store.get(tid).state is TaskState.awaiting_pr_review
        await wf.approve(tid)  # pr gate -> done
        return tid

    tid = asyncio.run(go())
    task = wf.store.get(tid)
    assert task.state is TaskState.done
    assert task.mr_url is not None
    reports = list((tmp_data_dir / "reports").glob(f"*/{tid}-report.md"))
    assert len(reports) == 1
    assert eng.calls >= 2  # planning + executing


def test_reject_returns_to_gate(tmp_data_dir) -> None:
    wf, _, _ = _wf(tmp_data_dir)

    async def go():
        tid = await wf.start("do something", None)
        await wf.reject(tid, "use a different approach")
        return tid

    tid = asyncio.run(go())
    task = wf.store.get(tid)
    assert task.state is TaskState.awaiting_plan_approval
    assert task.feedback == "use a different approach"


def test_engine_error_escalates(tmp_data_dir) -> None:
    wf, _, _ = _wf(tmp_data_dir, engine=FakeEngine(fail_with="engine_timeout"))

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
    wf, _, _ = _wf(tmp_data_dir, test_cmd=test_cmd)

    async def go():
        tid = await wf.start("do something", None)
        await wf.approve(tid)
        return tid

    tid = asyncio.run(go())
    task = wf.store.get(tid)
    assert task.state is TaskState.awaiting_pr_review
    asyncio.run(wf.approve(tid))  # pr gate -> done
    assert wf.store.get(tid).state is TaskState.done
    assert task.fix_loops >= 1


def test_resume_from_gate_reaches_done(tmp_data_dir) -> None:
    wf, _, _ = _wf(tmp_data_dir)

    async def go():
        tid = await wf.start("do something", None)
        await wf.resume(tid)  # resume at the plan gate behaves like approve
        assert wf.store.get(tid).state is TaskState.awaiting_pr_review
        await wf.resume(tid)  # resume at the pr gate -> done
        return tid

    tid = asyncio.run(go())
    assert wf.store.get(tid).state is TaskState.done


def test_full_loop_records_stats_auto_to_mr(tmp_data_dir) -> None:
    wf, _, _ = _wf(tmp_data_dir)

    async def go():
        tid = await wf.start("do something", None)
        await wf.approve(tid)
        await wf.approve(tid)
        return tid

    asyncio.run(go())
    stats = (tmp_data_dir / "stats.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(stats) == 1
    import json

    row = json.loads(stats[0])
    assert row["outcome"] == "done"
    assert row["auto_to_mr"] is True


def test_api_error_escalates(tmp_data_dir) -> None:
    wf, _, _ = _wf(tmp_data_dir, gitlab=FakeGitLab(fail_mr_with="api_error"))

    async def go():
        tid = await wf.start("do something", None)
        await wf.approve(tid)  # runs the loop; MR creation fails -> escalated
        return tid

    tid = asyncio.run(go())
    task = wf.store.get(tid)
    assert task.state is TaskState.escalated
    assert task.failure_class == "api_error"


def test_budget_exceeded_escalates(tmp_data_dir) -> None:
    wf, _, _ = _wf(tmp_data_dir, engine=FakeEngine(cost_usd=100.0), budget_usd=5.0)

    async def go():
        tid = await wf.start("do something", None)
        await wf.approve(tid)
        return tid

    tid = asyncio.run(go())
    task = wf.store.get(tid)
    assert task.state is TaskState.escalated
    assert task.failure_class == "budget_exceeded"


def test_engine_timeout_retries_then_succeeds(tmp_data_dir) -> None:
    wf, eng, _ = _wf(tmp_data_dir, engine=FakeEngine("engine_timeout", fail_times=1))

    async def go():
        tid = await wf.start("do something", None)
        await wf.approve(tid)
        await wf.approve(tid)
        return tid

    tid = asyncio.run(go())
    task = wf.store.get(tid)
    assert task.state is TaskState.done
    assert task.exec_retries == 1
    assert eng.calls >= 3  # planning + exec(fail) + exec(ok)


def test_engine_timeout_retry_exhausted(tmp_data_dir) -> None:
    wf, _, _ = _wf(
        tmp_data_dir, engine=FakeEngine("engine_timeout", fail_times=99), exec_retry_max=1
    )

    async def go():
        tid = await wf.start("do something", None)
        await wf.approve(tid)
        return tid

    tid = asyncio.run(go())
    task = wf.store.get(tid)
    assert task.state is TaskState.escalated
    assert task.failure_class == "engine_timeout"
