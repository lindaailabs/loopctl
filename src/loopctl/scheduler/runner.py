"""Background supervisor: parallel task execution with project-level mutex (SPEC §8 M3).

The supervisor drains queued tasks and runs them concurrently up to a configurable
limit across projects, while guaranteeing that tasks of the same project never run
at the same time (project-internal mutual exclusion, ADR-0008). Each task runs only
as far as its first human gate; the human then drives it to completion via
`approve`/`resume`.

The supervisor is engine/gitlab/notifier-agnostic: those are injected so it can be
exercised in tests without network or the `claude` binary.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import Callable
from uuid import uuid4

from loopctl.engines.base import EngineBackend
from loopctl.graph.workflow import Workflow
from loopctl.integrations.gitlab import GitLabClient
from loopctl.integrations.notify import Notifier
from loopctl.models.task import Task, TaskState


class Supervisor:
    def __init__(
        self,
        *,
        concurrency: int = 2,
        build: Callable[..., Workflow] | None = None,
        engine: EngineBackend | None = None,
        notifier: Notifier | None = None,
        gitlab: GitLabClient | None = None,
    ) -> None:
        self.concurrency = max(1, concurrency)
        self.build = build
        self.engine = engine
        self.notifier = notifier
        self.gitlab = gitlab
        self._semaphore = asyncio.Semaphore(self.concurrency)
        self._locks: dict[str, asyncio.Lock] = {}

    def _lock_for(self, project: str) -> asyncio.Lock:
        lock = self._locks.get(project)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[project] = lock
        return lock

    def _build(self, project_slug: str) -> Workflow:
        if self.build is not None:
            return self.build(
                project_slug, engine=self.engine, notifier=self.notifier, gitlab=self.gitlab
            )
        # Fall back to a direct Workflow build when no factory was supplied.
        from loopctl.config import paths
        from loopctl.config.loader import load_project  # local import avoids cycle
        from loopctl.config.validation import require_runtime

        cfg = load_project(project_slug, root=paths.projects_root())
        require_runtime(cfg)
        return Workflow(
            project=cfg,
            data_dir=paths.data_dir(),
            db_path=paths.data_dir() / "loopctl.db",
            engine=self.engine,
            notifier=self.notifier,
            gitlab=self.gitlab,
            runs_dir=paths.runs_root(),
        )

    async def run_task(self, task_id: str) -> None:
        task = self._get_task(task_id)
        if task is None:
            return
        # Acquire the project lock first so a waiting same-project task does not
        # occupy a cross-project concurrency slot (ADR-0008: project-internal mutex).
        async with self._lock_for(task.project), self._semaphore:
            wf = self._build(task.project)
            await wf.run_queued(task_id)

    def _get_task(self, task_id: str) -> Task | None:
        from loopctl.config import paths
        from loopctl.store.db import TaskStore

        with TaskStore(paths.data_dir() / "loopctl.db") as store:
            return store.get(task_id)

    async def serve(self, *, stop_when_idle: bool = True, poll_s: float = 1.0) -> int:
        """Run queued tasks until idle (or forever in watch mode).

        Returns the number of tasks executed.
        """
        executed = 0
        while True:
            queued = [t for t in self._list_tasks() if t.state is TaskState.queued]
            if not queued:
                if stop_when_idle:
                    return executed
                await asyncio.sleep(poll_s)
                continue
            executed += len(queued)
            by_project: dict[str, list[Task]] = defaultdict(list)
            for task in queued:
                by_project[task.project].append(task)
            workflows = {project: self._build(project) for project in by_project}

            async def run_project(workflow: Workflow, tasks: list[Task]) -> None:
                for task in tasks:
                    async with self._semaphore:
                        await workflow.run_queued(task.id)

            await asyncio.gather(
                *(run_project(workflows[project], tasks) for project, tasks in by_project.items())
            )
            if not stop_when_idle:
                await asyncio.sleep(poll_s)

    def _list_tasks(self) -> list[Task]:
        from loopctl.config import paths
        from loopctl.store.db import TaskStore

        with TaskStore(paths.data_dir() / "loopctl.db") as store:
            return store.list_all()


def new_task_id(slug: str) -> str:
    return f"{slug}-{uuid4().hex[:8]}"
