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
import re
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
from loopctl.integrations.github import (
    DryRunGitHubClient,
    GitHubClient,
    GitHubError,
    HttpGitHubClient,
)
from loopctl.integrations.gitlab import (
    DryRunGitLabClient,
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
        github: GitHubClient | None = None,
        runs_dir: Path | None = None,
    ) -> None:
        self.project = project
        self.data_dir = data_dir
        self.db_path = db_path
        self.engine: EngineBackend = engine or get_engine(self.project.engine)
        self.notifier: Notifier = notifier or ntfy_notify
        fake = self.engine.name == "fake"
        self.gitlab: GitLabClient = gitlab or (
            DryRunGitLabClient()
            if fake
            else HttpGitLabClient(
                retry_max=project.limits.mr_api_retry_max,
                backoff_base_s=project.limits.backoff_base_s,
                backoff_max_s=project.limits.backoff_max_s,
            )
        )
        self.github: GitHubClient = github or (
            DryRunGitHubClient()
            if fake
            else HttpGitHubClient(
                retry_max=project.limits.mr_api_retry_max,
                backoff_base_s=project.limits.backoff_base_s,
                backoff_max_s=project.limits.backoff_max_s,
            )
        )
        self.runs_dir = runs_dir or (data_dir / "reports")
        self.store = TaskStore(db_path)
        self.builder = self._build()

    # ----- public API -----------------------------------------------------

    async def start(
        self,
        requirement: str,
        base_branch: str | None = None,
        *,
        branch_name: str | None = None,
    ) -> str:
        base = base_branch or self.project.default_branch
        task = Task(
            id=self._new_id(),
            project=self.project.slug,
            requirement=requirement,
            base_branch=base,
            branch_name=branch_name,
            engine=self.project.engine,
            spec=load_spec(Path(self.project.knowledge_path or "."), self.project.spec_refs),
        )
        self.store.save(task)
        self._trace(task.id).write({"state": task.state.value, "event": "created"})
        async with self._compiled(task.id) as graph:
            await graph.ainvoke({"task": task.model_dump(mode="json")}, self._config(task.id))
        return task.id

    async def run_queued(self, task_id: str) -> None:
        """Execute a previously enqueued (``queued``) task through to its first gate.

        Used by the background supervisor (SPEC §8 M3); the task already exists in the
        store with its requirement and spec populated.
        """
        task = self.store.claim_queued(task_id)
        if task is None:
            return
        self._trace(task.id).write({"state": task.state.value, "event": "dequeued"})
        async with self._compiled(task_id) as graph:
            await graph.ainvoke({"task": task.model_dump(mode="json")}, self._config(task_id))

    async def approve(self, task_id: str) -> None:
        await self._resume(task_id, {"action": "approve"})

    async def reject(self, task_id: str, feedback: str) -> None:
        await self._resume(task_id, {"action": "reject", "feedback": feedback})

    async def resume(self, task_id: str) -> None:
        async with self._compiled(task_id) as graph:
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
            await graph.ainvoke({"task": task.model_dump(mode="json")}, config)

    async def _resume(self, task_id: str, payload: dict) -> None:
        async with self._compiled(task_id) as graph:
            await graph.ainvoke(Command(resume=payload), self._config(task_id))

    # ----- node implementations -------------------------------------------

    async def clarifying(self, state: dict) -> dict:
        task = self._task(state)
        task.state = TaskState.clarifying
        self._persist(task, "clarifying: no ambiguities, proceed")
        try:
            await self._prepare_workspace(task)
        except EngineError as exc:
            return self._fail(task, exc.kind)
        return {"task": task.model_dump(mode="json")}

    async def planning(self, state: dict) -> dict:
        task = self._task(state)
        task.state = TaskState.planning
        self._persist(task, "planning")
        prompt = assemble_plan_prompt(task.requirement, task.spec)
        try:
            result = await self.engine.execute(self._ctx(task, ""), prompt)
        except EngineError as exc:
            return self._fail(task, exc.kind)
        if not result.success:
            return self._fail(task, "engine_error")
        task.plan = Plan(goal=result.stdout_summary or "plan", changed_files=result.changed_files)
        task.tokens += result.tokens
        task.cost_usd += result.cost_usd
        if task.cost_usd > self._limits().budget_usd:
            return self._fail(task, "budget_exceeded")
        self._persist(task, "plan generated")
        return {"task": task.model_dump(mode="json")}

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
        return {"task": task.model_dump(mode="json")}

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
                return {"task": task.model_dump(mode="json")}
            return self._fail(task, exc.kind)
        if not result.success:
            return self._fail(task, "engine_error")
        task.branch = task.branch or result.branch
        task.changed_files = result.changed_files
        task.tokens += result.tokens
        task.cost_usd += result.cost_usd
        if task.cost_usd > self._limits().budget_usd:
            return self._fail(task, "budget_exceeded")
        self._persist(task, "executing complete")
        return {"task": task.model_dump(mode="json")}

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
        return {"task": task.model_dump(mode="json")}

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
                return {"task": task.model_dump(mode="json")}
            return self._fail(task, exc.kind)
        if not result.success:
            return self._fail(task, "engine_error")
        task.tokens += result.tokens
        task.cost_usd += result.cost_usd
        task.changed_files = result.changed_files or task.changed_files
        if task.cost_usd > self._limits().budget_usd:
            return self._fail(task, "budget_exceeded")
        task.state = TaskState.fixing
        self._persist(task, "fix applied")
        return {"task": task.model_dump(mode="json")}

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
        report_path = self._write_report(task, report)
        task.state = TaskState.creating_mr
        if report_path is None:
            event = "report unavailable; opening MR"
        elif report_path.is_relative_to(self.runs_dir):
            event = f"report ready: {report_path}"
        else:
            event = f"playbook write failed; report staged locally: {report_path}"
            await self.notifier(f"[loopctl] task {task.id} report was staged at {report_path}")
        self._persist(task, event)
        return {"task": task.model_dump(mode="json")}

    async def creating_mr(self, state: dict) -> dict:
        task = self._task(state)
        task.state = TaskState.creating_mr
        self._persist(task, "creating_mr")
        branch = task.branch or f"loopctl/{task.id}"
        if self.engine.name == "claude_code" and branch == task.base_branch:
            return self._fail(task, "environment_error")
        plan_goal = task.plan.goal if task.plan else ""
        summary = task.report.summary if task.report else task.requirement
        description = assemble_mr_description(
            plan_goal=plan_goal, report_summary=summary, spec_refs=self.project.spec_refs
        )
        title = f"[loopctl] {task.requirement[:60]}"
        workdir = Path(self.project.repo_path or ".")
        try:
            await self._commit_engine_changes(
                task, workdir, f"[loopctl] {task.id}: {task.requirement[:60]}"
            )
            if self.project.provider == "github":
                await self.github.push_branch(workdir=workdir, branch=branch, remote="origin")
                mr = await self.github.open_mr(
                    repo=self.project.github_repo or "",
                    source_branch=branch,
                    target_branch=task.base_branch,
                    title=title,
                    description=description,
                )
            else:
                await self.gitlab.push_branch(workdir=workdir, branch=branch, remote="origin")
                mr = await self.gitlab.open_mr(
                    project_id=self.project.gitlab_project_id or 0,
                    source_branch=branch,
                    target_branch=task.base_branch,
                    title=title,
                    description=description,
                )
        except (EngineError, GitLabError, GitHubError) as exc:
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
        return {"task": task.model_dump(mode="json")}

    async def escalated(self, state: dict) -> dict:
        task = self._task(state)
        if task.report is None:
            task.report = distill_report(
                requirement=task.requirement,
                plan_goal=task.plan.goal if task.plan else "",
                changed_files=task.changed_files,
                test_result=f"escalated: {task.failure_class}",
                feedback=task.feedback,
            )
            self._write_report(task, task.report)
        self._persist(task, f"escalated: {task.failure_class}")
        self._append_stat(task, "escalated")
        await self.notifier(f"[loopctl] task {task.id} escalated ({task.failure_class})")
        return {"task": task.model_dump(mode="json")}

    # ----- routing --------------------------------------------------------

    def _route_after_gate(self, state: dict) -> str:
        task = self._task(state)
        return "planning" if task.feedback else "executing"

    def _route_after_clarifying(self, state: dict) -> str:
        task = self._task(state)
        return "escalated" if task.state is TaskState.escalated else "planning"

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
        graph.add_conditional_edges(
            "clarifying",
            self._route_after_clarifying,
            {"planning": "planning", "escalated": "escalated"},
        )
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
    async def _compiled(self, task_id: str):
        checkpoint_path = self.data_dir / "checkpoints" / f"{task_id}.sqlite"
        async with get_checkpointer(checkpoint_path) as saver:
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
        return {"task": task.model_dump(mode="json")}

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

    async def _prepare_workspace(self, task: Task) -> None:
        """Create a protected per-task branch before an editing-capable engine runs."""
        if self.engine.name != "claude_code":
            return
        workdir = Path(self.project.repo_path or ".")
        if not workdir.is_dir() or not (workdir / ".git").exists():
            raise EngineError("environment_error", f"not a git repository: {workdir}")
        status = await self._git_output(workdir, "status", "--porcelain")
        if status.strip():
            raise EngineError("environment_error", "working tree is not clean")
        branch = task.branch or self._task_branch_name(task)
        exists = await self._git_ok(workdir, "show-ref", "--verify", f"refs/heads/{branch}")
        args = ("switch", branch) if exists else ("switch", "-c", branch, task.base_branch)
        if not await self._git_ok(workdir, *args):
            raise EngineError("environment_error", f"cannot switch to task branch {branch}")
        task.branch = branch
        self._persist(task, f"workspace ready on {branch}")

    def _task_branch_name(self, task: Task) -> str:
        source = task.branch_name or task.requirement
        label = re.sub(r"[^A-Za-z0-9]+", "_", source).strip("_").lower()
        if not label or not re.search(r"[A-Za-z]", label):
            raise EngineError(
                "environment_error",
                "an English branch label is required; pass --branch-name <english_name>",
            )
        label = label[:60].rstrip("_")
        timestamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S")
        return f"{label}_{timestamp}"

    async def _git_ok(self, workdir: Path, *args: str) -> bool:
        proc = await asyncio.create_subprocess_exec(
            "git",
            *args,
            cwd=str(workdir),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()
        return proc.returncode == 0

    async def _git_output(self, workdir: Path, *args: str) -> str:
        proc = await asyncio.create_subprocess_exec(
            "git",
            *args,
            cwd=str(workdir),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        out, err = await proc.communicate()
        if proc.returncode != 0:
            raise EngineError("environment_error", err.decode(errors="replace").strip())
        return out.decode(errors="replace")

    async def _commit_engine_changes(self, task: Task, workdir: Path, message: str) -> None:
        """Commit only the files the editing engine reported changing."""
        if self.engine.name != "claude_code":
            return
        await self._git_commit(workdir, message, task.changed_files)

    async def _git_commit(self, workdir: Path, message: str, changed_files: list[str]) -> None:
        """Stage reported working-tree changes and commit them on the current branch.

        The coding agent (claude) produces file edits but frequently omits the
        commit, which would make the MR identical to base. We commit here so the
        pushed branch actually diverges. The path list comes from git status after
        the engine run, which avoids sweeping unrelated runtime/user changes into
        the MR.
        """
        if not changed_files:
            if (await self._git_output(workdir, "status", "--porcelain")).strip():
                raise EngineError(
                    "environment_error",
                    "working tree changed but the engine did not report changed files",
                )
            return
        if not await self._git_ok(workdir, "add", "--", *changed_files):
            raise EngineError("environment_error", "git add failed")
        proc = await asyncio.create_subprocess_exec(
            "git",
            "-C",
            str(workdir),
            "diff",
            "--cached",
            "--quiet",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.communicate()
        if proc.returncode == 0:
            # Nothing staged: nothing to commit.
            return
        commit = await asyncio.create_subprocess_exec(
            "git",
            "-C",
            str(workdir),
            "commit",
            "--no-gpg-sign",
            "-m",
            message,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, err = await commit.communicate()
        if commit.returncode != 0:
            raise EngineError(
                "environment_error", f"git commit failed: {err.decode(errors='replace').strip()}"
            )

    def _write_report(self, task: Task, report: Any) -> Path | None:
        markdown = render_report_markdown(report, task)
        day = datetime.now().astimezone().date().isoformat()
        try:
            day_dir = self.runs_dir / day
            day_dir.mkdir(parents=True, exist_ok=True)
            report_path = day_dir / f"{task.id}-report.md"
            report_path.write_text(markdown, encoding="utf-8")
            self._append_report_index(task, report_path, day)
            return report_path
        except OSError:
            try:
                fallback = self.data_dir / "reports" / f"{task.id}-report.md"
                fallback.parent.mkdir(parents=True, exist_ok=True)
                fallback.write_text(markdown, encoding="utf-8")
                return fallback
            except OSError:
                return None

    def _append_report_index(self, task: Task, report_path: Path, day: str) -> None:
        summary_path = self.runs_dir / "summary.md"
        if not summary_path.exists():
            summary_path.write_text("# runs summary\n\n", encoding="utf-8")
        outcome = task.failure_class or "completed"
        rel = report_path.relative_to(self.runs_dir).as_posix()
        entry = f"- {day} [{outcome}] {task.project} {task.id} — {task.requirement} → {rel}\n"
        with summary_path.open("a", encoding="utf-8") as summary:
            summary.write(entry)

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
    github: GitHubClient | None = None,
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
        github=github,
    )
