"""Load and merge project configuration.

project.toml (committed, machine-agnostic) is merged with a local override file
(~/.loopctl/projects/<slug>.local.toml) that carries machine-specific fields such
as repo_path. The resulting ProjectConfig never contains hard-coded absolute
paths from source control.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

from loopctl.config.paths import local_projects_dir
from loopctl.models.config import Limits
from loopctl.models.project import ProjectConfig


def _read_toml(path: Path) -> dict:
    with path.open("rb") as f:
        return tomllib.load(f)


def _resolve_project_toml(slug: str, root: Path) -> Path:
    direct = root / slug / "project.toml"
    if direct.exists():
        return direct
    # Fallback: scan subdirectories for a project.toml whose slug matches.
    if root.exists():
        for candidate in sorted(root.iterdir()):
            if candidate.is_dir():
                toml_path = candidate / "project.toml"
                if toml_path.exists():
                    try:
                        data = _read_toml(toml_path)
                    except tomllib.TOMLDecodeError:
                        continue
                    if data.get("slug") == slug:
                        return toml_path
    raise FileNotFoundError(f"project config for '{slug}' not found under {root}")


def load_project(
    slug: str,
    *,
    root: Path | None = None,
    local_dir: Path | None = None,
) -> ProjectConfig:
    root = root or Path.cwd() / "playbook" / "projects"
    local_dir = local_dir or local_projects_dir()
    toml_path = _resolve_project_toml(slug, root)
    data = _read_toml(toml_path)

    cfg = ProjectConfig(
        slug=data["slug"],
        display_name=data.get("display_name", data["slug"]),
        engine=data.get("engine", "claude_code"),
        git_remote=data.get("git_remote", ""),
        gitlab_project_id=data.get("gitlab_project_id"),
        default_branch=data.get("default_branch", "main"),
        test_cmd=data.get("test_cmd", ""),
        spec_refs=list(data.get("spec_refs", [])),
        limits=Limits.from_config(data.get("limits", {})),
    )

    local_toml = local_dir / f"{slug}.local.toml"
    if local_toml.exists():
        local = _read_toml(local_toml)
        cfg.repo_path = local.get("repo_path")

    if cfg.repo_path is None:
        # Default to the directory that holds project.toml; in production the
        # real repo path should be supplied via the local override.
        cfg.repo_path = str(toml_path.parent)

    return cfg
