"""Project configuration model, mapped from project.toml + local override."""

from __future__ import annotations

from pydantic import BaseModel, Field

from loopctl.models.config import Limits


class ProjectConfig(BaseModel):
    slug: str
    display_name: str = ""
    engine: str = "claude_code"
    git_remote: str = ""
    gitlab_project_id: int | None = None
    default_branch: str = "main"
    test_cmd: str = ""
    spec_refs: list[str] = Field(default_factory=list)
    limits: Limits = Field(default_factory=Limits)
    # Machine-specific; only ever populated from the local override file, never
    # from the committed project.toml.
    repo_path: str | None = None
