"""Shared pytest fixtures for loopctl tests."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))


@pytest.fixture
def tmp_data_dir(tmp_path, monkeypatch) -> Path:
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setenv("LOOPCTL_DATA_DIR", str(data))
    return data


@pytest.fixture
def sample_projects_root() -> Path:
    return REPO_ROOT / "tests" / "fixtures"
