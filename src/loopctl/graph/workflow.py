"""LangGraph workflow: the requirement → MR local loop.

Pipeline: clarifying → planning → plan gate (interrupt) → executing → testing
→ (fixing ⇄ executing, ≤N 轮) → reporting → creating_mr → pr gate (interrupt)
→ done. Failure classes from SPEC §5.3 are detected and routed to `escalated`
with the right `failure_class` (engine_timeout, agent_stuck, test_failure,
api_error, budget_exceeded, agent_limit).

The workflow is engine- and gitlab-agnostic: the engine, notifier and gitlab
client are injected so unit tests can drive the loop with fakes and no network.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from loopctl.config.loader import load_project
from loopctl.engines import get_engine
from loopctl.engines.base import EngineBackend, EngineContext, EngineError
from loopctl.graph.state import GraphState
from loopctl.integrations.gitlab import (
    GitLabClient,
    GitLabError,
    HttpGitLabClient,
    assemble_mr_description,
)
from loopctl.integrations.notify import Notifier, ntfy_notify
from loopctl.knowledge import (
    assemble_exec_prompt,
    assemble_fix_prompt,
    assemble_plan_prompt,
    distill_report,
    load_spec,
    render_report_markdown,
)
from loopctl.models.config import Limits
from loopctl.models.project import ProjectConfig
from loopctl.models.task import Plan, Task, TaskState
from loopctl.store.db import TaskStore, get_checkpointer
from loopctl.store.stats import append_stat
from loopctl.store.trace import TraceWriter


class Workflow:
    def __init__(
        self,
        *,
        project: ProjectConfig,
        data_dir: Path,
        db_path: Path,
        engine: EngineBackend | None = None,
        notifier: Notifier | None = None,
        gitlab: GitLabClient | None = None,
    ) -> None:
        self.project = project
        self.data_dir = data_dir
        self.db_path = db_path
        self.engine: EngineBackend = engine or get_engine(self.project.engine)
        self.notifier: Notifier = notifier or ntfy_notify
        self.gitlab: GitLabClient = gitlab or HttpGitLabClient()
        self.store = TaskStore(db_path)
        self.checkpoint_path = self.data_dir / "checkpoints.sqlite"
        self.builder = self._build()

    # ----- public API -----------------------------------------------------

    async def start(self, requirement: str, base_branch: str | None = None) -> str:
        base = base_branch or self.project.default_branch
        task = Task(
            id=self._new_id(),
            project=self.project.slug,
            requirement=requirement,
            base_branch=base,
            engine=self.project.engine,
            spec=load_spec(Path(self.project.repo_path or "."), self.project.spec_refs),
        )
        self.store.save(task)
        self._trace(task.id).write({"state": task.state.value, "event": "created"})
        async with self._compiled() as graph:
            await graph.ainvoke({"task": task.model_dump()}, self._config(task.id))
        return task.id

    async def run_queued(self, task_id: str) -> None:
        """Execute a previously enqueued (``queued``) task through to its first gate.

        Used by the background supervisor (SPEC §8 M3); the task already exists in the
        store with its requirement and spec populated.
        """
        task = self.store.get(task_id)
        if task is None:
            raise ValueError(f"unknown task: {task_id}")
        task.state = TaskState.clarifying
        self._persist(task, "dequeued")
        async with self._compiled() as graph:
            await graph.ainvoke({"task": task.model_dump()}, self._config(task_id))

    async def approve(self, task_id: str) -> None:
        await self._resume(task_id, {"action": "approve"})

    async def reject(self, task_id: str, feedback: str) -> None:
        await self._resume(task_id, {"action": "reject", "feedback": feedback})

    async def resume(self, task_id: str) -> None:
        async with self._compiled() as graph:
            config = self._config(task_id)
            snapshot = await graph.aget_state(config)
            if snapshot.next:  # paused at an interrupt (plan or pr gate)
                await graph.ainvoke(Command(resume={"action": "approve"}), config)
                return
            task = self.store.get(task_id)
            if task is None:
                raise ValueError(f"unknown task: {task_id}")
            if task.state is TaskState.escalated:
                task.state = TaskState.executing
                task.failure_class = None
                self.store.save(task)
            # Continue from the last checkpoint (e.g. after a Ctrl-C mid-node).
            await graph.ainvoke({"task": task.model_dump()}, config)

    async def _resume(self, task_id: str, payload: dict) -> None:
        async with self._compiled() as graph:
            await graph.ainvoke(Command(resume=payload), self._config(task_id))

    # ----- node implementations -------------------------------------------

    async def clarifying(self, state: dict) -> dict:
        task = self._task(state)
        task.state = TaskState.clarifying
        self._persist(task, "clarifying: no ambiguities, proceed")
        return {"task": task.model_dump()}

    async def planning(self, state: dict) -> dict:
        task = self._task(state)
        task.state = TaskState.planning
        self._persist(task, "planning")
        prompt = assemble_plan_prompt(task.requirement, task.spec)
        try:
            result = await self.engine.execute(self._ctx(task, ""), prompt)
        except EngineError as exc:
            return self._fail(task, exc.kind)
        task.plan = Plan(goal=result.stdout_summary or "plan", changed_files=result.changed_files)
        task.tokens += result.tokens
        task.cost_usd += result.cost_usd
        if task.cost_usd > self._limits().budget_usd:
            return self._fail(task, "budget_exceeded")
        self._persist(task, "plan generated")
        return {"task": task.model_dump()}

    async def plan_gate(self, state: dict) -> dict:
        task = self._task(state)
        task.state = TaskState.awaiting_plan_approval
        self._persist(task, "awaiting plan approval")
        await self.notifier(f"[loopctl] task {task.id} awaits plan approval")
        payload = interrupt({"type": "plan_approval", "plan": task.plan.goal if task.plan else ""})
        action = payload.get("action") if isinstance(payload, dict) else None
        if action == "reject":
            task.feedback = payload.get("feedback")
        else:
            task.feedback = None
        self._persist(task, f"plan gate resolved: {action}")
        return {"task": task.model_dump()}

    async def executing(self, state: dict) -> dict:
        task = self._task(state)
        task.pending_retry = False
        task.state = TaskState.executing
        self._persist(task, "executing")
        plan_goal = task.plan.goal if task.plan else ""
        prompt = assemble_exec_prompt(plan_goal, task.spec)
        try:
            result = await self.engine.execute(self._ctx(task, plan_goal), prompt)
        except EngineError as exc:
            if exc.kind == "engine_timeout" and task.exec_retries < self._limits().exec_retry_max:
                task.exec_retries += 1
                task.pending_retry = True
                self._persist(task, f"engine_timeout retry {task.exec_retries}")
                return {"task": task.model_dump()}
            return self._fail(task, exc.kind)
        task.branch = result.branch or task.branch
        task.changed_files = result.changed_files
        task.tokens += result.tokens
        task.cost_usd += result.cost_usd
        if task.cost_usd > self._limits().budget_usd:
            return self._fail(task, "budget_exceeded")
        self._persist(task, "executing complete")
        return {"task": task.model_dump()}

    async def testing(self, state: dict) -> dict:
        task = self._task(state)
        task.state = TaskState.testing
        self._persist(task, "testing")
        passed, output = await self._run_tests()
        if passed:
            task.state = TaskState.reporting
            self._persist(task, "tests passed")
        else:
            task.test_failure = output
            task.state = TaskState.fixing
            self._persist(task, "tests failed")
        return {"task": task.model_dump()}

    async def fixing(self, state: dict) -> dict:
        task = self._task(state)
        task.fix_loops += 1
        task.pending_retry = False
        self._persist(task, f"fixing loop {task.fix_loops}")
        if task.fix_loops > self._limits().fix_loop_max:
            return self._fail(task, "test_failure")
        plan_goal = task.plan.goal if task.plan else ""
        prompt = assemble_fix_prompt(plan_goal, task.test_failure or "", task.spec)
        try:
            result = await self.engine.execute(self._ctx(task, plan_goal), prompt)
        except EngineError as exc:
            if exc.kind == "engine_timeout" and task.exec_retries < self._limits().exec_retry_max:
                task.exec_retries += 1
                task.pending_retry = True
                self._persist(task, f"engine_timeout retry {task.exec_retries}")
                return {"task": task.model_dump()}
            return self._fail(task, exc.kind)
        task.tokens += result.tokens
        task.cost_usd += result.cost_usd
        task.changed_files = result.changed_files or task.changed_files
        if task.cost_usd > self._limits().budget_usd:
            return self._fail(task, "budget_exceeded")
        task.state = TaskState.fixing
        self._persist(task, "fix applied")
        return {"task": task.model_dump()}

    async def reporting(self, state: dict) -> dict:
        task = self._task(state)
        task.state = TaskState.reporting
        self._persist(task, "reporting")
        report = distill_report(
            requirement=task.requirement,
            plan_goal=task.plan.goal if task.plan else "",
            changed_files=task.changed_files,
            test_result="passed",
            feedback=task.feedback,
        )
        task.report = report
        self._write_report(task, report)
        task.state = TaskState.creating_mr
        self._persist(task, "report ready, opening MR")
        return {"task": task.model_dump()}

    async def creating_mr(self, state: dict) -> dict:
        task = self._task(state)
        task.state = TaskState.creating_mr
        self._persist(task, "creating_mr")
        branch = task.branch or f"loopctl/{task.id}"
        plan_goal = task.plan.goal if task.plan else ""
        summary = task.report.summary if task.report else task.requirement
        description = assemble_mr_description(
            plan_goal=plan_goal, report_summary=summary, spec_refs=self.project.spec_refs
        )
        title = f"[loopctl] {task.requirement[:60]}"
        try:
            await self.gitlab.push_branch(
                workdir=Path(self.project.repo_path or "."), branch=branch, remote="origin"
            )
            mr = await self.gitlab.open_mr(
                project_id=self.project.gitlab_project_id or 0,
                source_branch=branch,
                target_branch=task.base_branch,
                title=title,
                description=description,
            )
        except GitLabError as exc:
            return self._fail(task, exc.kind)
        task.mr_url = mr.url
        task.state = TaskState.awaiting_pr_review
        self._persist(task, f"mr opened: {mr.url}")
        await self.notifier(f"[loopctl] task {task.id} MR ready for review: {mr.url}")
        interrupt({"type": "pr_review", "mr_url": mr.url})
        # Resumed by a human after reviewing the MR.
        task.state = TaskState.done
        self._append_stat(task, "done")
        self._persist(task, "done")
        return {"task": task.model_dump()}

    async def escalated(self, state: dict) -> dict:
        task = self._task(state)
        self._persist(task, f"escalated: {task.failure_class}")
        self._append_stat(task, "escalated")
        await self.notifier(f"[loopctl] task {task.id} escalated ({task.failure_class})")
        return {"task": task.model_dump()}

    # ----- routing --------------------------------------------------------

    def _route_after_gate(self, state: dict) -> str:
        task = self._task(state)
        return "planning" if task.feedback else "executing"

    def _route_after_plan(self, state: dict) -> str:
        task = self._task(state)
        return "escalated" if task.state is TaskState.escalated else "plan_gate"

    def _route_after_exec(self, state: dict) -> str:
        task = self._task(state)
        if task.state is TaskState.escalated:
            return "escalated"
        if task.pending_retry:
            return "executing"
        return "testing"

    def _route_after_test(self, state: dict) -> str:
        task = self._task(state)
        return "reporting" if task.state is TaskState.reporting else "fixing"

    def _route_after_fix(self, state: dict) -> str:
        task = self._task(state)
        if task.state is TaskState.escalated:
            return "escalated"
        if task.pending_retry:
            return "fixing"
        return "testing"

    def _route_after_mr(self, state: dict) -> str:
        task = self._task(state)
        return "escalated" if task.state is TaskState.escalated else "end"

    # ----- helpers --------------------------------------------------------

    def _build(self):
        graph = StateGraph(GraphState)
        graph.add_node("clarifying", self.clarifying)
        graph.add_node("planning", self.planning)
        graph.add_node("plan_gate", self.plan_gate)
        graph.add_node("executing", self.executing)
        graph.add_node("testing", self.testing)
        graph.add_node("fixing", self.fixing)
        graph.add_node("reporting", self.reporting)
        graph.add_node("creating_mr", self.creating_mr)
        graph.add_node("escalated", self.escalated)

        graph.add_edge(START, "clarifying")
        graph.add_edge("clarifying", "planning")
        graph.add_conditional_edges(
            "planning", self._route_after_plan, {"plan_gate": "plan_gate", "escalated": "escalated"}
        )
        graph.add_conditional_edges(
            "plan_gate", self._route_after_gate, {"planning": "planning", "executing": "executing"}
        )
        graph.add_conditional_edges(
            "executing",
            self._route_after_exec,
            {"testing": "testing", "escalated": "escalated", "executing": "executing"},
        )
        graph.add_conditional_edges(
            "testing", self._route_after_test, {"reporting": "reporting", "fixing": "fixing"}
        )
        graph.add_conditional_edges(
            "fixing",
            self._route_after_fix,
            {"testing": "testing", "escalated": "escalated", "fixing": "fixing"},
        )
        graph.add_edge("reporting", "creating_mr")
        graph.add_conditional_edges(
            "creating_mr", self._route_after_mr, {"escalated": "escalated", "end": END}
        )
        graph.add_edge("escalated", END)
        return graph

    @asynccontextmanager
    async def _compiled(self):
        async with get_checkpointer(self.checkpoint_path) as saver:
            yield self.builder.compile(checkpointer=saver)

    def _config(self, task_id: str) -> dict:
        return {"configurable": {"thread_id": task_id}}

    def _limits(self) -> Limits:
        return self.project.limits

    def _task(self, state: dict) -> Task:
        return Task.model_validate(state["task"])

    def _trace(self, task_id: str) -> TraceWriter:
        return TraceWriter(self.data_dir / "traces", task_id)

    def _persist(self, task: Task, event: str) -> None:
        task.updated_at = datetime.now(UTC)
        task.last_event = event
        self.store.save(task)
        self._trace(task.id).write({"state": task.state.value, "event": event})

    def _ctx(self, task: Task, plan: str) -> EngineContext:
        limits: Limits = self._limits()
        return EngineContext(
            workdir=Path(self.project.repo_path or "."),
            requirement=task.requirement,
            plan=plan,
            spec_context=task.spec,
            timeout_min=limits.engine_timeout_min,
            budget_usd=limits.budget_usd,
            heartbeat_idle_min=limits.heartbeat_idle_min,
        )

    def _fail(self, task: Task, kind: str) -> dict:
        task.state = TaskState.escalated
        task.failure_class = kind
        return {"task": task.model_dump()}

    async def _run_tests(self) -> tuple[bool, str]:
        if not self.project.test_cmd:
            return True, ""
        proc = await asyncio.create_subprocess_shell(
            self.project.test_cmd,
            cwd=str(self.project.repo_path or "."),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        out, _ = await proc.communicate()
        return proc.returncode == 0, out.decode(errors="replace")

    def _write_report(self, task: Task, report: Any) -> None:
        reports_dir = self.data_dir / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        (reports_dir / f"{task.id}.md").write_text(
            render_report_markdown(report, task), encoding="utf-8"
        )

    def _append_stat(self, task: Task, outcome: str) -> None:
        append_stat(
            self.data_dir / "stats.jsonl",
            {
                "task_id": task.id,
                "project": task.project,
                "outcome": outcome,
                "auto_to_mr": task.mr_url is not None,
                "interventions": 1 if task.feedback else 0,
                "intervention_reasons": ["plan_rejected"] if task.feedback else [],
                "fix_loops": task.fix_loops,
                "tokens": task.tokens,
                "cost_usd": round(task.cost_usd, 4),
                "duration_s": int((task.updated_at - task.created_at).total_seconds()),
                "failure_class": task.failure_class,
            },
        )

    def _new_id(self) -> str:
        return f"{self.project.slug}-{uuid4().hex[:8]}"


def build_workflow(
    project_slug: str,
    *,
    data_dir: Path,
    db_path: Path,
    projects_root: Path | None = None,
    engine: EngineBackend | None = None,
    notifier: Notifier | None = None,
    gitlab: GitLabClient | None = None,
) -> Workflow:
    """Construct a Workflow, loading the project configuration from disk."""
    cfg = load_project(project_slug, root=projects_root)
    return Workflow(
        project=cfg,
        data_dir=data_dir,
        db_path=db_path,
        engine=engine,
        notifier=notifier,
        gitlab=gitlab,
    )
