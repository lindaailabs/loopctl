"""Scheduler: high-level orchestration over the workflow.

Kept thin on purpose (SPEC §4 dependency order: cli → scheduler → graph). It
loads project configuration, constructs a `Workflow`, and exposes async entry
points that the CLI drives via `asyncio.run`.
"""

from __future__ import annotations

import asyncio
import shutil
import sys
from pathlib import Path
from typing import Any

from loopctl.config import paths
from loopctl.config.loader import load_project
from loopctl.config.validation import require_runtime, runtime_issues
from loopctl.graph.workflow import Workflow
from loopctl.integrations.github import GitHubClient
from loopctl.integrations.gitlab import GitLabClient
from loopctl.knowledge.spec import load_spec
from loopctl.models.task import Task, TaskState
from loopctl.scheduler.runner import Supervisor, new_task_id
from loopctl.store.db import TaskStore
from loopctl.store.stats import aggregate


def _db_path() -> Path:
    return paths.data_dir() / "loopctl.db"


def build(
    project_slug: str,
    *,
    engine=None,
    notifier=None,
    gitlab: GitLabClient | None = None,
    github: GitHubClient | None = None,
) -> Workflow:
    cfg = load_project(project_slug, root=paths.projects_root())
    if engine is None and gitlab is None and github is None:
        require_runtime(cfg)
    return Workflow(
        project=cfg,
        data_dir=paths.data_dir(),
        db_path=_db_path(),
        engine=engine,
        notifier=notifier,
        gitlab=gitlab,
        github=github,
        runs_dir=paths.runs_root(),
    )


def _workflow_for_task(
    task_id: str,
    *,
    engine=None,
    notifier=None,
    gitlab: GitLabClient | None = None,
    github: GitHubClient | None = None,
) -> Workflow:
    with TaskStore(_db_path()) as store:
        task = store.get(task_id)
    if task is None:
        raise ValueError(f"unknown task: {task_id}")
    return build(task.project, engine=engine, notifier=notifier, gitlab=gitlab, github=github)


async def start(
    requirement: str,
    project_slug: str,
    base: str | None = None,
    *,
    branch_name: str | None = None,
    engine=None,
    notifier=None,
    gitlab: GitLabClient | None = None,
    github: GitHubClient | None = None,
) -> str:
    return await build(
        project_slug, engine=engine, notifier=notifier, gitlab=gitlab, github=github
    ).start(requirement, base, branch_name=branch_name)


def enqueue(
    requirement: str,
    project_slug: str,
    base: str | None = None,
    *,
    branch_name: str | None = None,
) -> str:
    """Register a task in the ``queued`` state for the background supervisor (SPEC §8 M3)."""
    cfg = load_project(project_slug, root=paths.projects_root())
    require_runtime(cfg)
    task = Task(
        id=new_task_id(cfg.slug),
        project=cfg.slug,
        requirement=requirement,
        base_branch=base or cfg.default_branch,
        branch_name=branch_name,
        engine=cfg.engine,
        state=TaskState.queued,
        spec=load_spec(Path(cfg.knowledge_path or "."), cfg.spec_refs),
    )
    with TaskStore(_db_path()) as store:
        store.save(task)
    return task.id


def serve(*, concurrency: int = 2, watch: bool = False) -> int:
    """Run the background supervisor until the queue is idle (or forever when watching)."""
    sup = Supervisor(concurrency=concurrency)
    return asyncio.run(sup.serve(stop_when_idle=not watch))


async def approve(
    task_id: str,
    *,
    engine=None,
    notifier=None,
    gitlab: GitLabClient | None = None,
    github: GitHubClient | None = None,
) -> None:
    task = get_task(task_id)
    if task is None:
        raise ValueError(f"unknown task: {task_id}")
    if task.state not in {TaskState.awaiting_plan_approval, TaskState.awaiting_pr_review}:
        raise ValueError(f"task {task_id} cannot be approved from state {task.state.value}")
    await _workflow_for_task(
        task_id, engine=engine, notifier=notifier, gitlab=gitlab, github=github
    ).approve(task_id)


async def reject(
    task_id: str,
    feedback: str,
    *,
    engine=None,
    notifier=None,
    gitlab: GitLabClient | None = None,
    github: GitHubClient | None = None,
) -> None:
    task = get_task(task_id)
    if task is None:
        raise ValueError(f"unknown task: {task_id}")
    if task.state is not TaskState.awaiting_plan_approval:
        raise ValueError(f"task {task_id} cannot be rejected from state {task.state.value}")
    await _workflow_for_task(
        task_id, engine=engine, notifier=notifier, gitlab=gitlab, github=github
    ).reject(task_id, feedback)


async def resume(
    task_id: str,
    *,
    engine=None,
    notifier=None,
    gitlab: GitLabClient | None = None,
    github: GitHubClient | None = None,
) -> None:
    task = get_task(task_id)
    if task is None:
        raise ValueError(f"unknown task: {task_id}")
    if task.state not in {
        TaskState.awaiting_plan_approval,
        TaskState.awaiting_pr_review,
        TaskState.escalated,
    }:
        raise ValueError(f"task {task_id} cannot be resumed from state {task.state.value}")
    await _workflow_for_task(
        task_id, engine=engine, notifier=notifier, gitlab=gitlab, github=github
    ).resume(task_id)


def list_tasks() -> list[Task]:
    with TaskStore(_db_path()) as store:
        return store.list_all()


def get_task(task_id: str) -> Task | None:
    with TaskStore(_db_path()) as store:
        return store.get(task_id)


def mr_url(task_id: str) -> str | None:
    task = get_task(task_id)
    return task.mr_url if task else None


def report_markdown(task_id: str) -> str | None:
    task = get_task(task_id)
    if task is None or task.report is None:
        return None
    from loopctl.knowledge.report import render_report_markdown

    return render_report_markdown(task.report, task)


def stats_summary() -> dict[str, Any]:
    return aggregate(paths.data_dir() / "stats.jsonl")


def list_projects() -> list[dict[str, str]]:
    root = paths.projects_root()
    out: list[dict[str, str]] = []
    if not root.exists():
        return out
    for directory in sorted(root.iterdir()):
        if directory.is_dir() and (directory / "project.toml").exists():
            try:
                cfg = load_project(directory.name, root=root)
            except Exception:
                continue
            out.append({"slug": cfg.slug, "display_name": cfg.display_name, "engine": cfg.engine})
    return out


def doctor(project_slug: str | None = None) -> dict[str, Any]:
    if project_slug is None:
        return _environment_report()
    cfg = load_project(project_slug, root=paths.projects_root())
    issues = runtime_issues(cfg)
    return {
        "project": cfg.slug,
        "ready": not issues,
        "issues": issues,
        "repo_path": cfg.repo_path,
        "knowledge_path": cfg.knowledge_path,
        "runs_root": str(paths.runs_root()),
    }


def _environment_report() -> dict[str, Any]:
    from loopctl.config.validation import global_environment_issues

    issues = global_environment_issues()
    return {
        "scope": "global",
        "ready": not issues,
        "issues": issues,
        "python": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        "tools": {
            "claude": shutil.which("claude") is not None,
            "git": shutil.which("git") is not None,
            "uv": shutil.which("uv") is not None,
        },
        "paths": {
            "data_dir": str(paths.data_dir()),
            "projects_root": str(paths.projects_root()),
            "runs_root": str(paths.runs_root()),
        },
    }
