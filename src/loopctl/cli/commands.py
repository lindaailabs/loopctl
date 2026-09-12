"""Command definitions.

M0 implements `status` and `projects` against empty data so the CLI is runnable
before any store or engine exists. Remaining commands (run/approve/reject/
report/watch/stats/resume) are added in M1.
"""

from __future__ import annotations

import json
from typing import Any

import typer
from rich.console import Console
from rich.table import Table

console = Console()


def _emit_json(payload: dict[str, Any]) -> None:
    typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))


def register_commands(app: typer.Typer) -> None:
    @app.command()
    def status(
        json_output: bool = typer.Option(
            False, "--json", help="Emit machine-readable JSON instead of a table."
        ),
    ) -> None:
        """Show a board of all tasks (empty until tasks exist)."""
        tasks: list[dict[str, Any]] = []
        if json_output:
            _emit_json({"tasks": tasks})
            return
        table = Table(title="Tasks")
        for column in ("task-id", "project", "state", "age", "engine", "cost", "last-event"):
            table.add_column(column)
        console.print(table)

    @app.command()
    def projects(
        json_output: bool = typer.Option(
            False, "--json", help="Emit machine-readable JSON instead of a table."
        ),
    ) -> None:
        """List registered projects (empty until projects are registered)."""
        projects_list: list[dict[str, Any]] = []
        if json_output:
            _emit_json({"projects": projects_list})
            return
        table = Table(title="Projects")
        for column in ("slug", "display_name", "engine"):
            table.add_column(column)
        console.print(table)
