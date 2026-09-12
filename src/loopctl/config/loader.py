"""Load and merge project configuration.

project.toml (committed, machine-agnostic) is merged with a local override file
(~/.loopctl/projects/<slug>.local.toml) that carries machine-specific fields such
as repo_path. The resulting ProjectConfig never contains hard-coded absolute
paths from source control.

`write_project` creates that committed project.toml (plus a spec.md stub and an
empty decisions/ directory) so `loopctl init` can register a project without
hand-editing TOML.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

from loopctl.config.paths import local_projects_dir
from loopctl.engines import ENGINE_REGISTRY
from loopctl.models.config import Limits
from loopctl.models.project import SLUG_RE, ProjectConfig


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
        knowledge_path=str(toml_path.parent),
    )

    if cfg.engine not in ENGINE_REGISTRY:
        raise ValueError(
            f"project '{cfg.slug}' uses unknown engine '{cfg.engine}'; "
            f"known engines: {', '.join(sorted(ENGINE_REGISTRY))}"
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


def write_project(
    slug: str,
    *,
    display_name: str | None = None,
    engine: str = "claude_code",
    git_remote: str = "",
    gitlab_project_id: int | None = None,
    default_branch: str = "main",
    test_cmd: str = "",
    spec_refs: list[str] | None = None,
    repo_path: str | None = None,
    root: Path | None = None,
    local_dir: Path | None = None,
    force: bool = False,
) -> dict[str, Path]:
    """Register a project: write project.toml (+ spec.md stub, decisions/).

    Returns the paths written. Raises ``FileExistsError`` if project.toml already
    exists and ``force`` is false; ``ValueError`` on an invalid slug or engine.
    """
    if not SLUG_RE.match(slug):
        raise ValueError(f"invalid slug '{slug}': must match {SLUG_RE.pattern}")
    if engine not in ENGINE_REGISTRY:
        raise ValueError(
            f"unknown engine '{engine}'; known engines: {', '.join(sorted(ENGINE_REGISTRY))}"
        )

    root = root or Path.cwd() / "playbook" / "projects"
    local_dir = local_dir or local_projects_dir()
    proj_dir = root / slug
    toml_path = proj_dir / "project.toml"
    if toml_path.exists() and not force:
        raise FileExistsError(f"{toml_path} already exists (use --force to overwrite)")

    proj_dir.mkdir(parents=True, exist_ok=True)
    spec_refs = spec_refs or ["spec.md"]
    toml_path.write_text(
        _render_project_toml(
            slug=slug,
            display_name=display_name or slug,
            engine=engine,
            git_remote=git_remote,
            gitlab_project_id=gitlab_project_id,
            default_branch=default_branch,
            test_cmd=test_cmd,
            spec_refs=spec_refs,
        ),
        encoding="utf-8",
    )

    spec_path = proj_dir / "spec.md"
    if not spec_path.exists():
        spec_path.write_text(
            _SPEC_TEMPLATE.format(display_name=display_name or slug, slug=slug),
            encoding="utf-8",
        )
    (proj_dir / "decisions").mkdir(exist_ok=True)

    created: dict[str, Path] = {"project_toml": toml_path, "spec": spec_path}
    if repo_path:
        local_dir.mkdir(parents=True, exist_ok=True)
        local_toml = local_dir / f"{slug}.local.toml"
        local_toml.write_text(f'repo_path = "{repo_path}"\n', encoding="utf-8")
        created["local_toml"] = local_toml
    return created


def _render_project_toml(
    *,
    slug: str,
    display_name: str,
    engine: str,
    git_remote: str,
    gitlab_project_id: int | None,
    default_branch: str,
    test_cmd: str,
    spec_refs: list[str],
) -> str:
    lines = [
        f'slug = "{slug}"',
        f'display_name = "{display_name}"',
        f'engine = "{engine}"',
    ]
    if git_remote:
        lines.append(f'git_remote = "{git_remote}"')
    if gitlab_project_id is not None:
        lines.append(f"gitlab_project_id = {gitlab_project_id}")
    lines.append(f'default_branch = "{default_branch}"')
    if test_cmd:
        lines.append(f'test_cmd = "{test_cmd}"')
    refs = ", ".join(f'"{r}"' for r in spec_refs)
    lines.append(f"spec_refs = [{refs}]")
    lines.append("")
    lines.append("[limits]")
    limits = Limits()
    lines.append(f"engine_timeout_min = {limits.engine_timeout_min}")
    lines.append(f"fix_loop_max = {limits.fix_loop_max}")
    lines.append(f"budget_usd = {limits.budget_usd}")
    return "\n".join(lines) + "\n"


_SPEC_TEMPLATE = """# Spec: {display_name}

Project slug: `{slug}`.

This file is the authoritative, machine-readable knowledge for this project. It is
loaded into the engine prompt via `spec_refs` in `project.toml` (see `docs/SPEC.md`
§6). Document stable facts here: conventions, constraints, forbidden patterns, and
decisions. Task reports are distilled into `decisions/` and this file over time.

## Conventions

- (fill in)

## Constraints / forbidden

- (fill in)
"""
