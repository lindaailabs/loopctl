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
        fg: bool = typer.Option(False, "--fg", help="Run in the foreground (blocks until a gate)."),
        json_output: bool = typer.Option(False, "--json", help="Emit JSON instead of text."),
    ) -> None:
        """Create a task and run it up to the first human gate."""
        try:
            task_id = asyncio.run(scheduler.start(requirement, project, base))
        except FileNotFoundError as exc:
            typer.echo(f"error: {exc}", err=True)
            raise typer.Exit(1) from None
        task = scheduler.get_task(task_id)
        if json_output:
            _emit_json({"task_id": task_id, "state": task.state.value})
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
                "or `loopctl resume {task_id}` after fixing the environment."
            )
        else:
            typer.echo(f"state: {task.state.value}")

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
        for column in ("task-id", "project", "state", "age", "engine", "cost", "last-event"):
            table.add_column(column)
        for t in tasks:
            table.add_row(
                t.id,
                t.project,
                t.state.value,
                _age(t.created_at),
                t.engine,
                f"${t.cost_usd:.2f}",
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
        asyncio.run(scheduler.approve(task_id))
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
        asyncio.run(scheduler.reject(task_id, feedback))
        _echo_state(task_id, json_output, "rejected; re-planning")

    @app.command()
    def resume(
        task_id: str = typer.Argument(..., help="Task id."),
        json_output: bool = typer.Option(False, "--json", help="Emit JSON instead of text."),
    ) -> None:
        """Resume an interrupted or escalated task."""
        asyncio.run(scheduler.resume(task_id))
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
    def stats(
        json_output: bool = typer.Option(False, "--json", help="Emit JSON instead of a table."),
    ) -> None:
        """Aggregate success rate, interventions and cost."""
        summary = scheduler.stats_summary()
        if json_output:
            _emit_json(summary)
            return
        table = Table(title="Stats")
        table.add_column("metric")
        table.add_column("value")
        for key, value in summary.items():
            table.add_row(key, str(value))
        console.print(table)


def _echo_state(task_id: str, json_output: bool, message: str) -> None:
    task = scheduler.get_task(task_id)
    if json_output:
        _emit_json({"task_id": task_id, "state": task.state.value if task else None})
    else:
        typer.echo(f"{message} → task {task_id} state: {task.state.value if task else 'unknown'}")
