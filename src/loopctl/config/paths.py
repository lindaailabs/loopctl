"""Machine-local path resolution.

These locations are resolved from environment variables so the same code runs on
any machine (Windows or macOS) without committing absolute paths.
"""

from __future__ import annotations

import os
from pathlib import Path


def data_dir() -> Path:
    """Directory for runtime data (checkpoints, traces, stats). Gitignored."""
    env = os.environ.get("LOOPCTL_DATA_DIR")
    return Path(env) if env else (Path.cwd() / "data")


def projects_root() -> Path:
    """Root directory containing per-slug project registrations.

    Set LOOPCTL_PROJECTS_ROOT to point at your playbook's projects/ folder, or a
    fixtures directory during development.
    """
    env = os.environ.get("LOOPCTL_PROJECTS_ROOT")
    return Path(env) if env else (playbook_root() / "projects")


def local_projects_dir() -> Path:
    """Directory for machine-local override files (~/.loopctl/projects)."""
    env = os.environ.get("LOOPCTL_LOCAL_PROJECTS_DIR")
    return Path(env) if env else (Path.home() / ".loopctl" / "projects")


def playbook_root() -> Path:
    """Root of the private knowledge repository."""
    env = os.environ.get("LOOPCTL_PLAYBOOK_ROOT")
    if env:
        return Path(env)
    sibling = Path.cwd().parent / "playbook"
    return sibling if sibling.is_dir() else (Path.cwd() / "playbook")


def runs_root() -> Path:
    """Directory for reviewable task reports in the private playbook."""
    env = os.environ.get("LOOPCTL_RUNS_ROOT")
    if env:
        return Path(env)
    projects_env = os.environ.get("LOOPCTL_PROJECTS_ROOT")
    if projects_env:
        projects = Path(projects_env)
        return projects.parent / "runs" if projects.name == "projects" else projects / "runs"
    return playbook_root() / "runs"
