"""Tests for the M3 background supervisor: parallel execution + project mutex."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from loopctl.engines.base import EngineResult
from loopctl.graph.workflow import Workflow
from loopctl.integrations.gitlab import MRInfo
from loopctl.models.task import TaskState
from loopctl.scheduler import enqueue
from loopctl.scheduler.runner import Supervisor


async def _noop_notify(message: str) -> None:  # pragma: no cover
    return None


class FakeGitLab:
    name = "fake_gitlab"

    async def push_branch(self, *, workdir: Path, branch: str, remote: str = "origin") -> None:
        return None

    async def open_mr(
        self, *, project_id, source_branch, target_branch, title, description
    ) -> MRInfo:
        return MRInfo(url="https://gl/-/merge_requests/1", iid=1)


class RecEngine:
    """Records overlap so we can assert cross-project parallelism and project mutex."""

    name = "rec"

    def __init__(self, shared: dict) -> None:
        self.shared = shared
        self.active = 0
        self.max_active = 0

    async def execute(self, ctx: Any, prompt: str) -> EngineResult:
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        self.shared["n"] += 1
        self.shared["max"] = max(self.shared["max"], self.shared["n"])
        if self.shared["n"] >= 2:
            self.shared["release"].set()
        await asyncio.wait_for(self.shared["release"].wait(), timeout=2)
        self.active -= 1
        self.shared["n"] -= 1
        return EngineResult(
            success=True,
            branch="feature/x",
            changed_files=[],
            stdout_summary="ok",
            tokens=1,
            cost_usd=0.0,
            duration_s=0.0,
        )


def _write_project(root: Path, slug: str) -> None:
    (root / slug).mkdir(parents=True, exist_ok=True)
    (root / slug / "project.toml").write_text(
        f'slug = "{slug}"\n'
        f'display_name = "{slug}"\n'
        f'engine = "fake"\n'
        f'default_branch = "main"\n'
        f'test_cmd = "python -c \\"pass\\""\n',
        encoding="utf-8",
    )

    with (root / slug / "project.toml").open("a", encoding="utf-8") as config:
        config.write('spec_refs = ["spec.md"]\n')
    (root / slug / "spec.md").write_text(f"SPEC FOR {slug}", encoding="utf-8")


def _make_build(projects_root: Path, data_dir: Path, engines: dict, gitlab: FakeGitLab) -> Any:
    from loopctl.config.loader import load_project

    def build(
        slug: str, *, engine: Any = None, notifier: Any = None, gitlab: Any = None
    ) -> Workflow:
        cfg = load_project(slug, root=projects_root)
        cfg.repo_path = str(data_dir)
        return Workflow(
            project=cfg,
            data_dir=data_dir,
            db_path=data_dir / "loopctl.db",
            engine=engines[slug],
            notifier=_noop_notify,
            gitlab=gitlab,
        )

    return build


def test_supervisor_parallel_and_project_mutex(monkeypatch: Any, tmp_path: Path) -> None:
    projects_root = tmp_path / "projects"
    data_dir = tmp_path / "data"
    _write_project(projects_root, "A")
    _write_project(projects_root, "B")
    monkeypatch.setenv("LOOPCTL_PROJECTS_ROOT", str(projects_root))
    monkeypatch.setenv("LOOPCTL_DATA_DIR", str(data_dir))

    shared: dict[str, Any] = {"n": 0, "max": 0, "release": asyncio.Event()}
    engines = {"A": RecEngine(shared), "B": RecEngine(shared)}
    gitlab = FakeGitLab()
    build = _make_build(projects_root, data_dir, engines, gitlab)

    t_a1 = enqueue("A task one", "A")
    t_a2 = enqueue("A task two", "A")
    t_b = enqueue("B task one", "B")

    async def go() -> int:
        sup = Supervisor(concurrency=2, build=build, engine=None, gitlab=gitlab)
        return await sup.serve(stop_when_idle=True)

    executed = asyncio.run(go())

    assert executed == 3
    from loopctl.store.db import TaskStore

    for tid in (t_a1, t_a2, t_b):
        task = TaskStore(data_dir / "loopctl.db").get(tid)
        assert task is not None
        assert task.state is TaskState.awaiting_plan_approval
        assert task.spec == f"# spec.md\n\nSPEC FOR {task.project}"
    # Cross-project parallelism observed (A and B overlapped at least once).
    assert shared["max"] >= 2
    # Project-internal mutex: no project ever had two tasks active at once.
    assert engines["A"].max_active <= 1
    assert engines["B"].max_active <= 1


def test_serve_drains_queue(monkeypatch: Any, tmp_path: Path) -> None:
    projects_root = tmp_path / "projects"
    data_dir = tmp_path / "data"
    _write_project(projects_root, "A")
    monkeypatch.setenv("LOOPCTL_PROJECTS_ROOT", str(projects_root))
    monkeypatch.setenv("LOOPCTL_DATA_DIR", str(data_dir))

    shared: dict[str, Any] = {"n": 0, "max": 0, "release": asyncio.Event()}
    shared["release"].set()
    engines = {"A": RecEngine(shared)}
    gitlab = FakeGitLab()
    build = _make_build(projects_root, data_dir, engines, gitlab)

    enqueue("q1", "A")
    enqueue("q2", "A")

    async def go() -> int:
        sup = Supervisor(concurrency=2, build=build, engine=None, gitlab=gitlab)
        return await sup.serve(stop_when_idle=True)

    assert asyncio.run(go()) == 2
