"""GitLab integration: branch push and merge-request creation (SPEC §8 M2).

All GitLab interaction goes through the injectable ``GitLabClient`` protocol so
unit tests can drive the loop with a fake and without network access. The
production implementation uses httpx for the REST API and `git` for the push.

Failure handling: GitLab/API errors are classified as ``api_error`` and retried
with exponential backoff (SPEC §5.3) before the workflow escalates.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

import httpx


class GitLabError(Exception):
    """Raised by the GitLab client when it cannot complete its job.

    ``kind`` mirrors the SPEC §5.3 failure classes (currently ``api_error``).
    """

    def __init__(self, kind: str, message: str = "") -> None:
        super().__init__(message or kind)
        self.kind = kind


@dataclass
class MRInfo:
    url: str
    iid: int


@runtime_checkable
class GitLabClient(Protocol):
    async def push_branch(self, *, workdir: Path, branch: str, remote: str = "origin") -> None:
        """Push ``branch`` to ``remote`` (creating it on the remote if needed)."""
        ...

    async def open_mr(
        self,
        *,
        project_id: int,
        source_branch: str,
        target_branch: str,
        title: str,
        description: str,
    ) -> MRInfo:
        """Open a merge request; retried with backoff on transient API errors."""
        ...


async def _backoff(attempt: int, base: float, cap: float, sleep: Callable[[float], object]) -> None:
    delay = min(base * (2 ** max(attempt, 0)), cap)
    await sleep(delay)


class HttpGitLabClient:
    """Production GitLab client: git push + REST API MR creation with backoff."""

    name = "http_gitlab"

    def __init__(
        self,
        *,
        token: str | None = None,
        base_url: str | None = None,
        retry_max: int = 5,
        backoff_base_s: float = 2.0,
        backoff_max_s: float = 60.0,
        sleep: Callable[[float], object] = asyncio.sleep,
    ) -> None:
        self.token = token or os.environ.get("GITLAB_TOKEN")
        self.base_url = (base_url or os.environ.get("GITLAB_URL") or "https://gitlab.com").rstrip(
            "/"
        )
        self.retry_max = retry_max
        self.backoff_base_s = backoff_base_s
        self.backoff_max_s = backoff_max_s
        self._sleep = sleep

    async def push_branch(self, *, workdir: Path, branch: str, remote: str = "origin") -> None:
        last: Exception | None = None
        for attempt in range(self.retry_max):
            try:
                proc = await asyncio.create_subprocess_exec(
                    "git",
                    "push",
                    "-u",
                    remote,
                    branch,
                    cwd=str(workdir),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                _, err = await proc.communicate()
                if proc.returncode == 0:
                    return
                last = RuntimeError(
                    err.decode(errors="replace").strip() or f"git push exited {proc.returncode}"
                )
            except OSError as exc:
                last = exc
            if attempt < self.retry_max - 1:
                await _backoff(attempt, self.backoff_base_s, self.backoff_max_s, self._sleep)
        raise GitLabError("api_error", f"git push failed: {last}")

    async def open_mr(
        self,
        *,
        project_id: int,
        source_branch: str,
        target_branch: str,
        title: str,
        description: str,
    ) -> MRInfo:
        if not self.token:
            raise GitLabError("api_error", "GITLAB_TOKEN is not configured")
        url = f"{self.base_url}/api/v4/projects/{project_id}/merge_requests"
        last: object = None
        for attempt in range(self.retry_max):
            try:
                async with httpx.AsyncClient() as client:
                    resp = await client.post(
                        url,
                        json={
                            "source_branch": source_branch,
                            "target_branch": target_branch,
                            "title": title,
                            "description": description,
                        },
                        headers={"PRIVATE-TOKEN": self.token},
                        timeout=30.0,
                    )
                if resp.status_code == 201:
                    data = resp.json()
                    return MRInfo(url=data["web_url"], iid=int(data["iid"]))
                last = f"status {resp.status_code}: {resp.text[:200]}"
            except httpx.HTTPError as exc:
                last = exc
            if attempt < self.retry_max - 1:
                await _backoff(attempt, self.backoff_base_s, self.backoff_max_s, self._sleep)
        raise GitLabError("api_error", f"failed to open MR: {last}")


def assemble_mr_description(*, plan_goal: str, report_summary: str, spec_refs: list[str]) -> str:
    """Build the MR description body (SPEC §6.4 / §8 M2)."""
    refs = "\n".join(f"- {r}" for r in spec_refs) or "- (none)"
    return (
        "## Plan\n\n"
        f"{plan_goal or '(none)'}\n\n"
        "## Report\n\n"
        f"{report_summary or '(none)'}\n\n"
        "## Spec references\n\n"
        f"{refs}\n"
    )
