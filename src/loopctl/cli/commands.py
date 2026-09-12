"""Command definitions.

M0 implemented `status`/`projects` against empty data. M1 adds the full loop:
`run`/`approve`/`reject`/`report`/`watch`/`stats`/`resume`.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from typing import Any

import typer
from rich.console import Console
from rich.table import Table

from loopctl import scheduler
from loopctl.models.task import TaskState

console = Console()


def _emit_json(payload: dict[str, Any]) -> None:
    typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))


def _age(task_created: datetime) -> str:
    delta = datetime.now(UTC) - task_created
    mins = int(delta.total_seconds() // 60)
    return f"{mins}m" if mins < 60 else f"{mins // 60}h{mins % 60}m"


def register_commands(app: typer.Typer) -> None:
    @app.command()
    def run(
        requirement: str = typer.Argument(..., help="Natural-language requirement."),
        project: str = typer.Option(..., "--project", "-p", help="Registered project slug."),
        base: str = typer.Option(None, "--base", help="Base branch to branch from."),
        branch_name: str = typer.Option(
            None,
            "--branch-name",
            help="English branch label; required when the requirement has no English words.",
        ),
        fg: bool = typer.Option(
            False,
            "--fg",
            help="Run in foreground (block until first gate).",
        ),
        json_output: bool = typer.Option(False, "--json", help="Emit JSON instead of text."),
    ) -> None:
        """Create a task. Without --fg it is queued for the background supervisor (SPEC §8 M3)."""
        if fg:
            try:
                task_id = asyncio.run(
                    scheduler.start(requirement, project, base, branch_name=branch_name)
                )
            except (FileNotFoundError, RuntimeError, ValueError) as exc:
                typer.echo(f"error: {exc}", err=True)
                raise typer.Exit(1) from None
            task = scheduler.get_task(task_id)
            if json_output:
                _emit_json({"task_id": task_id, "state": task.state.value if task else None})
                return
            typer.echo(f"created task {task_id}")
            if task is None:
                return
            if task.state is TaskState.awaiting_plan_approval:
                if task.plan:
                    typer.echo(f"plan:\n{task.plan.goal}")
                typer.echo(
                    "awaiting plan approval — run `loopctl approve <id>` or "
                    "`loopctl reject <id> --feedback <text>`"
                )
            elif task.state is TaskState.escalated:
                typer.echo(
                    f"task escalated ({task.failure_class}); check `loopctl report {task_id}` "
                    f"or `loopctl resume {task_id}` after fixing the environment."
                )
            else:
                typer.echo(f"state: {task.state.value}")
            return

        try:
            task_id = scheduler.enqueue(requirement, project, base, branch_name=branch_name)
        except (FileNotFoundError, RuntimeError, ValueError) as exc:
            typer.echo(f"error: {exc}", err=True)
            raise typer.Exit(1) from None
        if json_output:
            _emit_json({"task_id": task_id, "state": "queued"})
            return
        typer.echo(f"queued task {task_id}")
        typer.echo("run `loopctl serve` to execute (or `loopctl run ... --fg` for foreground)")

    @app.command()
    def status(
        json_output: bool = typer.Option(False, "--json", help="Emit JSON instead of a table."),
    ) -> None:
        """Show a board of all tasks."""
        tasks = scheduler.list_tasks()
        if json_output:
            _emit_json(
                {
                    "tasks": [
                        {
                            "id": t.id,
                            "project": t.project,
                            "state": t.state.value,
                            "age": _age(t.created_at),
                            "engine": t.engine,
                            "cost_usd": t.cost_usd,
                            "last_event": t.last_event,
                        }
                        for t in tasks
                    ]
                }
            )
            return
        table = Table(title="Tasks")
        for column in ("task-id", "project", "state", "age", "engine", "cost", "mr", "last-event"):
            table.add_column(column)
        for t in tasks:
            table.add_row(
                t.id,
                t.project,
                t.state.value,
                _age(t.created_at),
                t.engine,
                f"${t.cost_usd:.2f}",
                t.mr_url or "-",
                t.last_event,
            )
        console.print(table)

    @app.command()
    def projects(
        json_output: bool = typer.Option(False, "--json", help="Emit JSON instead of a table."),
    ) -> None:
        """List registered projects."""
        projects_list = scheduler.list_projects()
        if json_output:
            _emit_json({"projects": projects_list})
            return
        table = Table(title="Projects")
        for column in ("slug", "display_name", "engine"):
            table.add_column(column)
        for p in projects_list:
            table.add_row(p["slug"], p["display_name"], p["engine"])
        console.print(table)

    @app.command()
    def approve(
        task_id: str = typer.Argument(..., help="Task id."),
        json_output: bool = typer.Option(False, "--json", help="Emit JSON instead of text."),
    ) -> None:
        """Approve the plan and continue execution."""
        try:
            asyncio.run(scheduler.approve(task_id))
        except (FileNotFoundError, RuntimeError, ValueError) as exc:
            typer.echo(f"error: {exc}", err=True)
            raise typer.Exit(1) from None
        _echo_state(task_id, json_output, "approved; continuing")

    @app.command()
    def reject(
        task_id: str = typer.Argument(..., help="Task id."),
        feedback: str = typer.Option(
            ..., "--feedback", help="Feedback injected back into planning."
        ),
        json_output: bool = typer.Option(False, "--json", help="Emit JSON instead of text."),
    ) -> None:
        """Reject the plan and send feedback back to planning."""
        try:
            asyncio.run(scheduler.reject(task_id, feedback))
        except (FileNotFoundError, RuntimeError, ValueError) as exc:
            typer.echo(f"error: {exc}", err=True)
            raise typer.Exit(1) from None
        _echo_state(task_id, json_output, "rejected; re-planning")

    @app.command()
    def resume(
        task_id: str = typer.Argument(..., help="Task id."),
        json_output: bool = typer.Option(False, "--json", help="Emit JSON instead of text."),
    ) -> None:
        """Resume an interrupted or escalated task."""
        try:
            asyncio.run(scheduler.resume(task_id))
        except (FileNotFoundError, RuntimeError, ValueError) as exc:
            typer.echo(f"error: {exc}", err=True)
            raise typer.Exit(1) from None
        _echo_state(task_id, json_output, "resumed")

    @app.command()
    def report(
        task_id: str = typer.Argument(..., help="Task id."),
        json_output: bool = typer.Option(False, "--json", help="Emit JSON instead of text."),
    ) -> None:
        """Show the task's distilled report."""
        md = scheduler.report_markdown(task_id)
        if md is None:
            typer.echo("no report available yet", err=True)
            raise typer.Exit(1)
        if json_output:
            _emit_json({"report": md})
        else:
            typer.echo(md)

    @app.command()
    def mr(
        task_id: str = typer.Argument(..., help="Task id."),
        json_output: bool = typer.Option(False, "--json", help="Emit JSON instead of text."),
    ) -> None:
        """Show the GitLab merge request URL for a task."""
        url = scheduler.mr_url(task_id)
        if url is None:
            typer.echo("no MR available yet", err=True)
            raise typer.Exit(1)
        if json_output:
            _emit_json({"task_id": task_id, "mr_url": url})
        else:
            typer.echo(url)

    @app.command()
    def watch(task_id: str = typer.Argument(..., help="Task id.")) -> None:
        """Follow the task's event trace (prints recorded events)."""
        from loopctl.config import paths

        trace = paths.data_dir() / "traces" / f"{task_id}.jsonl"
        if not trace.exists():
            typer.echo("no trace available", err=True)
            raise typer.Exit(1)
        for line in trace.read_text(encoding="utf-8").splitlines():
            typer.echo(line)

    @app.command()
    def serve(
        concurrency: int = typer.Option(
            2, "--concurrency", help="Max concurrent tasks across projects."
        ),
        watch: bool = typer.Option(False, "--watch", help="Keep running and poll for new tasks."),
        json_output: bool = typer.Option(False, "--json", help="Emit JSON instead of text."),
    ) -> None:
        """Run the background supervisor: execute queued tasks (SPEC §8 M3)."""
        try:
            executed = scheduler.serve(concurrency=concurrency, watch=watch)
        except (FileNotFoundError, RuntimeError, ValueError) as exc:
            typer.echo(f"error: {exc}", err=True)
            raise typer.Exit(1) from None
        if json_output:
            _emit_json({"executed": executed})
        else:
            typer.echo(f"supervisor finished; executed {executed} task(s)")

    @app.command()
    def stats(
        json_output: bool = typer.Option(False, "--json", help="Emit JSON instead of a table."),
    ) -> None:
        """Aggregate success rate, interventions, cost and per-project breakdown."""
        summary = scheduler.stats_summary()
        if json_output:
            _emit_json(summary)
            return
        table = Table(title="Stats")
        table.add_column("metric")
        table.add_column("value")
        for key in ("total", "done", "escalated", "failed", "auto_to_mr", "success_rate"):
            if key in summary:
                table.add_row(key, str(summary[key]))
        table.add_row("avg_duration_s", str(summary.get("avg_duration_s", 0.0)))
        table.add_row("avg_cost_usd", str(summary.get("avg_cost_usd", 0.0)))
        table.add_row("interventions", str(summary.get("interventions", 0)))
        table.add_row("fix_loops", str(summary.get("fix_loops", 0)))
        table.add_row("tokens", str(summary.get("tokens", 0)))
        table.add_row("cost_usd", str(summary.get("cost_usd", 0.0)))
        console.print(table)
        by_project = summary.get("by_project") or {}
        if by_project:
            pt = Table(title="By project")
            for column in ("project", "total", "done", "escalated", "failed", "success_rate"):
                pt.add_column(column)
            for slug, counts in sorted(by_project.items()):
                pt.add_row(
                    slug,
                    str(counts.get("total", 0)),
                    str(counts.get("done", 0)),
                    str(counts.get("escalated", 0)),
                    str(counts.get("failed", 0)),
                    str(counts.get("success_rate", 0.0)),
                )
            console.print(pt)

    @app.command()
    def doctor(
        project: str | None = typer.Option(
            None, "--project", "-p", help="Registered project slug. Omit for a global check."
        ),
        json_output: bool = typer.Option(False, "--json", help="Emit JSON instead of text."),
    ) -> None:
        """Check environment (no --project) or a project's runtime prerequisites."""
        try:
            result = scheduler.doctor(project)
        except (FileNotFoundError, ValueError) as exc:
            typer.echo(f"error: {exc}", err=True)
            raise typer.Exit(1) from None
        if json_output:
            _emit_json(result)
            return
        if result.get("scope") == "global":
            if result["ready"]:
                typer.echo("environment ready")
            else:
                typer.echo("environment is not ready:", err=True)
                for issue in result["issues"]:
                    typer.echo(f"  - {issue}", err=True)
        elif result["ready"]:
            typer.echo(f"project '{project}' is ready")
        else:
            typer.echo(f"project '{project}' is not ready:", err=True)
            for issue in result["issues"]:
                typer.echo(f"  - {issue}", err=True)
        if not result["ready"]:
            raise typer.Exit(1)

    @app.command()
    def init(
        slug: str = typer.Argument(..., help="Project slug (alphanumeric, [A-Za-z0-9_-])."),
        display_name: str = typer.Option("", "--display-name", "-n", help="Human-readable name."),
        engine: str = typer.Option(
            "claude_code", "--engine", "-e", help="Engine name (see `loopctl engines`)."
        ),
        git_remote: str = typer.Option("", "--git-remote", help="Git remote URL."),
        gitlab_project_id: int | None = typer.Option(
            None, "--gitlab-project-id", help="GitLab project id."
        ),
        default_branch: str = typer.Option("main", "--default-branch", help="Base branch."),
        test_cmd: str = typer.Option("", "--test-cmd", help="Command that runs the test suite."),
        spec_refs: list[str] = typer.Option(  # noqa: B008
            (), "--spec-refs", help="Repeatable spec refs (relative to project dir)."
        ),
        repo_path: str = typer.Option(
            None, "--repo-path", help="Machine-local repo path (written to the local override)."
        ),
        force: bool = typer.Option(False, "--force", help="Overwrite an existing project.toml."),
        json_output: bool = typer.Option(False, "--json", help="Emit JSON instead of text."),
    ) -> None:
        """Register a project: write project.toml (+ a spec.md stub, decisions/)."""
        from loopctl.config import paths
        from loopctl.config.loader import write_project

        try:
            created = write_project(
                slug,
                display_name=display_name,
                engine=engine,
                git_remote=git_remote,
                gitlab_project_id=gitlab_project_id,
                default_branch=default_branch,
                test_cmd=test_cmd,
                spec_refs=spec_refs or None,
                repo_path=repo_path,
                root=paths.projects_root(),
                local_dir=paths.local_projects_dir(),
                force=force,
            )
        except (FileExistsError, ValueError) as exc:
            typer.echo(f"error: {exc}", err=True)
            raise typer.Exit(1) from None
        if json_output:
            _emit_json({"slug": slug, "created": {k: str(v) for k, v in created.items()}})
            return
        typer.echo(f"registered project '{slug}'")
        for key, value in created.items():
            typer.echo(f"  wrote {key}: {value}")
        typer.echo(f'next: loopctl run "<requirement>" --project {slug}')

    @app.command()
    def engines(
        json_output: bool = typer.Option(False, "--json", help="Emit JSON instead of text."),
    ) -> None:
        """List registered execution engines and whether each is implemented."""
        from loopctl.engines import ENGINE_REGISTRY, is_implemented

        if json_output:
            _emit_json(
                {
                    "engines": [
                        {"name": name, "implemented": is_implemented(name)}
                        for name in sorted(ENGINE_REGISTRY)
                    ]
                }
            )
            return
        for name in sorted(ENGINE_REGISTRY):
            tag = "implemented" if is_implemented(name) else "stub (not implemented)"
            typer.echo(f"{name}\t{tag}")


def _echo_state(task_id: str, json_output: bool, message: str) -> None:
    task = scheduler.get_task(task_id)
    if json_output:
        _emit_json({"task_id": task_id, "state": task.state.value if task else None})
    else:
        typer.echo(f"{message} → task {task_id} state: {task.state.value if task else 'unknown'}")
