"""Tests for project configuration loading."""

from __future__ import annotations

from pathlib import Path

import pytest

from loopctl.config.loader import load_project


def test_load_project_from_fixture(sample_projects_root: Path) -> None:
    cfg = load_project("sample", root=sample_projects_root)
    assert cfg.slug == "sample"
    assert cfg.test_cmd == "pytest -q"
    assert cfg.limits.fix_loop_max == 2
    assert cfg.limits.budget_usd == 2.0
    # repo_path defaults to the project directory when no local override exists.
    assert cfg.repo_path is not None


def test_load_project_missing(sample_projects_root: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_project("does-not-exist", root=sample_projects_root)
