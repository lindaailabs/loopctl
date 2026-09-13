"""Tests for the GitHub integration (no real network)."""

from __future__ import annotations

import asyncio
import pathlib
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from loopctl.config.validation import runtime_issues
from loopctl.integrations.github import (
    DryRunGitHubClient,
    GitHubError,
    HttpGitHubClient,
    MRInfo,
    _backoff,
)
from loopctl.models.project import ProjectConfig


def test_backoff_bounds() -> None:
    async def go() -> list[float]:
        slept: list[float] = []
        sleep = AsyncMock(side_effect=lambda d: slept.append(d))
        await _backoff(0, 2.0, 60.0, sleep)
        await _backoff(5, 2.0, 60.0, sleep)
        return slept

    slept = asyncio.run(go())
    assert slept[0] == 2.0
    assert slept[1] == 60.0  # capped


def test_open_pr_success() -> None:
    async def go() -> MRInfo:
        resp = httpx.Response(201, json={"html_url": "https://github.com/o/r/pull/1", "number": 1})
        fake = AsyncMock()
        fake.__aenter__.return_value.post.return_value = resp
        with patch("loopctl.integrations.github.httpx.AsyncClient", return_value=fake):
            client = HttpGitHubClient(token="t", base_url="https://gh", retry_max=1)
            return await client.open_mr(
                repo="o/r",
                source_branch="b",
                target_branch="main",
                title="t",
                description="d",
            )

    mr = asyncio.run(go())
    assert isinstance(mr, MRInfo)
    assert mr.url == "https://github.com/o/r/pull/1" and mr.iid == 1


def test_open_pr_retries_then_succeeds() -> None:
    async def go() -> tuple[MRInfo, int]:
        resp = httpx.Response(201, json={"html_url": "u", "number": 9})
        fake = AsyncMock()
        fake.__aenter__.return_value.post.side_effect = [
            httpx.ConnectError("boom"),
            httpx.ConnectError("boom"),
            resp,
        ]
        sleep = AsyncMock()
        with patch("loopctl.integrations.github.httpx.AsyncClient", return_value=fake):
            client = HttpGitHubClient(token="t", base_url="https://gh", retry_max=3, sleep=sleep)
            mr = await client.open_mr(
                repo="o/r",
                source_branch="b",
                target_branch="main",
                title="t",
                description="d",
            )
        return mr, fake.__aenter__.return_value.post.call_count

    mr, calls = asyncio.run(go())
    assert mr.iid == 9
    assert calls == 3


def test_open_pr_exhausted_raises() -> None:
    async def go() -> None:
        fake = AsyncMock()
        fake.__aenter__.return_value.post.side_effect = httpx.ConnectError("boom")
        sleep = AsyncMock()
        with patch("loopctl.integrations.github.httpx.AsyncClient", return_value=fake):
            client = HttpGitHubClient(token="t", base_url="https://gh", retry_max=2, sleep=sleep)
            await client.open_mr(
                repo="o/r",
                source_branch="b",
                target_branch="main",
                title="t",
                description="d",
            )

    with pytest.raises(GitHubError) as exc:
        asyncio.run(go())
    assert exc.value.kind == "api_error"


def test_open_pr_requires_token() -> None:
    async def go() -> None:
        client = HttpGitHubClient(token=None, retry_max=1)
        await client.open_mr(
            repo="o/r",
            source_branch="b",
            target_branch="main",
            title="t",
            description="d",
        )

    with pytest.raises(GitHubError):
        asyncio.run(go())


def test_push_branch_failure_raises() -> None:
    async def go() -> None:
        proc = AsyncMock()
        proc.communicate.return_value = (b"", b"rejected")
        proc.returncode = 1
        with patch("loopctl.integrations.github.asyncio.create_subprocess_exec", return_value=proc):
            client = HttpGitHubClient(retry_max=1)
            await client.push_branch(workdir=pathlib.Path("."), branch="b")

    with pytest.raises(GitHubError):
        asyncio.run(go())


def test_dry_run_returns_url() -> None:
    async def go() -> MRInfo:
        return await DryRunGitHubClient().open_mr(
            repo="o/r",
            source_branch="b",
            target_branch="main",
            title="t",
            description="d",
        )

    mr = asyncio.run(go())
    assert mr.url.startswith("dry-run://pull/")


def test_validation_requires_github_credentials() -> None:
    cfg = ProjectConfig(
        slug="gh",
        engine="claude_code",
        provider="github",
        github_repo="o/r",
        repo_path="/tmp/gh",
        test_cmd="true",
        spec_refs=["spec.md"],
    )
    issues = runtime_issues(cfg)
    assert any("github_repo" not in i for i in issues)  # repo is set
    assert any("GITHUB_TOKEN" in i for i in issues)  # token missing

    cfg2 = ProjectConfig(
        slug="gh",
        engine="claude_code",
        provider="github",
        repo_path="/tmp/gh",
        test_cmd="true",
        spec_refs=["spec.md"],
    )
    issues2 = runtime_issues(cfg2)
    assert any("github_repo is required" in i for i in issues2)
