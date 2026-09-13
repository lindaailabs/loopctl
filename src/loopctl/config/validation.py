"""Fail-fast validation for a project's production runtime dependencies."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from loopctl.config import paths
from loopctl.engines import is_implemented
from loopctl.models.project import ProjectConfig


def runtime_issues(project: ProjectConfig) -> list[str]:
    """Return actionable issues that would prevent a real task from completing."""
    issues: list[str] = []
    knowledge = Path(project.knowledge_path or ".")
    if not project.spec_refs:
        issues.append("at least one spec_ref is required")
    for ref in project.spec_refs:
        if not (knowledge / ref).exists():
            issues.append(f"missing spec ref: {knowledge / ref}")

    if not is_implemented(project.engine):
        issues.append(f"engine is not implemented: {project.engine}")
    if project.engine == "fake":
        return issues

    repo = Path(project.repo_path or "")
    if not project.repo_path or not repo.is_dir():
        issues.append(f"repo_path is not a directory: {project.repo_path or '(missing)'}")
    elif not (repo / ".git").exists():
        issues.append(f"repo_path is not a git repository: {repo}")
    if not project.test_cmd.strip():
        issues.append("test_cmd is required for a real run")
    if project.engine == "claude_code" and shutil.which("claude") is None:
        issues.append("claude executable was not found on PATH")
    if shutil.which("git") is None:
        issues.append("git executable was not found on PATH")
    if project.provider == "github":
        if not project.github_repo:
            issues.append("github_repo is required for provider=github")
        if not os.environ.get("GITHUB_TOKEN"):
            issues.append("GITHUB_TOKEN is not configured")
    else:
        if project.gitlab_project_id is None or project.gitlab_project_id <= 0:
            issues.append("gitlab_project_id is required")
        if not os.environ.get("GITLAB_TOKEN"):
            issues.append("GITLAB_TOKEN is not configured")
    return issues


def require_runtime(project: ProjectConfig) -> None:
    issues = runtime_issues(project)
    if issues:
        raise RuntimeError("project is not ready:\n- " + "\n- ".join(issues))


def global_environment_issues() -> list[str]:
    """Return issues that would block loopctl from operating at all (no project)."""
    issues: list[str] = []
    if shutil.which("git") is None:
        issues.append("git executable was not found on PATH")

    data = paths.data_dir()
    try:
        data.mkdir(parents=True, exist_ok=True)
        probe = data / ".loopctl-write-test"
        probe.write_text("", encoding="utf-8")
        probe.unlink()
    except OSError as exc:
        issues.append(f"data_dir is not writable: {data} ({exc})")

    if not paths.projects_root().exists():
        issues.append(f"projects_root does not exist: {paths.projects_root()}")
    return issues
