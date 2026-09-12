"""Project configuration model, mapped from project.toml + local override."""

from __future__ import annotations

import re

from pydantic import BaseModel, Field, field_validator

from loopctl.models.config import Limits

# Slugs are machine-readable identifiers used in paths and task ids. They must
# start with an alphanumeric char and contain only [A-Za-z0-9_-].
SLUG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")


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

    @field_validator("slug")
    @classmethod
    def _check_slug(cls, value: str) -> str:
        if not SLUG_RE.match(value):
            raise ValueError(f"invalid slug '{value}': must match {SLUG_RE.pattern}")
        return value
