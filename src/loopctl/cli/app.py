"""Typer application entry point."""

from __future__ import annotations

import typer

from .commands import register_commands

app = typer.Typer(
    name="loopctl",
    help="Control plane that orchestrates coding engines through a requirement-to-MR loop.",
    no_args_is_help=True,
    add_completion=False,
)


def run() -> None:
    """Console-script entry point."""
    app()


register_commands(app)
