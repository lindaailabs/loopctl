"""GitHub integration: branch push and pull-request creation (provider=github).

Mirrors ``gitlab.py``: all GitHub interaction goes through the injectable
``GitHubClient`` protocol so unit tests can drive the loop with a fake and
without network access. The production implementation uses httpx for the REST
API and `git` for the push.

Failure handling: GitHub/API errors are classified as ``api_error`` and retried
with exponential backoff (SPEC §5.3) before the workflow escalates.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Callable
from pathlib import Path
from typing import Protocol, runtime_checkable

import httpx

from loopctl.integrations.gitlab import MRInfo, _backoff


class GitHubError(Exception):
    """Raised by the GitHub client when it cannot complete its job.

    ``kind`` mirrors the SPEC §5.3 failure classes (currently ``api_error``).
    """

    def __init__(self, kind: str, message: str = "") -> None:
        super().__init__(message or kind)
        self.kind = kind


@runtime_checkable
class GitHubClient(Protocol):
    async def push_branch(self, *, workdir: Path, branch: str, remote: str = "origin") -> None:
        """Push ``branch`` to ``remote`` (creating it on the remote if needed)."""
        ...

    async def open_mr(
        self,
        *,
        repo: str,
        source_branch: str,
        target_branch: str,
        title: str,
        description: str,
    ) -> MRInfo:
        """Open a pull request; retried with backoff on transient API errors."""
        ...


class HttpGitHubClient:
    """Production GitHub client: git push + REST API PR creation with backoff."""

    name = "http_github"

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
        self.token = token or os.environ.get("GITHUB_TOKEN")
        self.base_url = (
            base_url or os.environ.get("GITHUB_API_URL") or "https://api.github.com"
        ).rstrip("/")
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
        raise GitHubError("api_error", f"git push failed: {last}")

    async def open_mr(
        self,
        *,
        repo: str,
        source_branch: str,
        target_branch: str,
        title: str,
        description: str,
    ) -> MRInfo:
        if not self.token:
            raise GitHubError("api_error", "GITHUB_TOKEN is not configured")
        if not repo:
            raise GitHubError("api_error", "github_repo is not configured")
        url = f"{self.base_url}/repos/{repo}/pulls"
        last: object = None
        for attempt in range(self.retry_max):
            try:
                async with httpx.AsyncClient() as client:
                    resp = await client.post(
                        url,
                        json={
                            "title": title,
                            "body": description,
                            "head": source_branch,
                            "base": target_branch,
                        },
                        headers={"Authorization": f"Bearer {self.token}"},
                        timeout=30.0,
                    )
                if resp.status_code in (200, 201):
                    data = resp.json()
                    return MRInfo(url=data["html_url"], iid=int(data["number"]))
                last = f"status {resp.status_code}: {resp.text[:200]}"
            except httpx.HTTPError as exc:
                last = exc
            if attempt < self.retry_max - 1:
                await _backoff(attempt, self.backoff_base_s, self.backoff_max_s, self._sleep)
        raise GitHubError("api_error", f"failed to open PR: {last}")


class DryRunGitHubClient:
    """No-op GitHub integration paired with the explicit fake engine."""

    name = "dry_run_github"

    async def push_branch(self, *, workdir: Path, branch: str, remote: str = "origin") -> None:
        return None

    async def open_mr(
        self,
        *,
        repo: str,
        source_branch: str,
        target_branch: str,
        title: str,
        description: str,
    ) -> MRInfo:
        return MRInfo(url=f"dry-run://pull/{source_branch}", iid=0)
