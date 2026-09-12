"""Minimal smoke tests so CI is green before feature tests land in M1."""

from __future__ import annotations

from loopctl import __version__
from loopctl.cli.app import app


def test_version() -> None:
    assert __version__ == "0.1.0"


def test_app_instantiable() -> None:
    assert app is not None
    assert app.info.name == "loopctl"
