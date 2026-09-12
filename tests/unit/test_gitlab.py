"""Tests for the GitLab integration (no real network)."""

from __future__ import annotations

import asyncio
import pathlib
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from loopctl.integrations.gitlab import (
    GitLabError,
    HttpGitLabClient,
    MRInfo,
    _backoff,
    assemble_mr_description,
)


def test_assemble_mr_description() -> None:
    body = assemble_mr_description(
        plan_goal="goal", report_summary="summary", spec_refs=["spec.md", "decisions/"]
    )
    assert "goal" in body and "summary" in body and "spec.md" in body


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


def test_open_mr_success() -> None:
    async def go() -> MRInfo:
        resp = httpx.Response(201, json={"web_url": "https://gl/-/merge_requests/1", "iid": 1})
        fake = AsyncMock()
        fake.__aenter__.return_value.post.return_value = resp
        with patch("loopctl.integrations.gitlab.httpx.AsyncClient", return_value=fake):
            client = HttpGitLabClient(token="t", base_url="https://gl", retry_max=1)
            return await client.open_mr(
                project_id=1, source_branch="b", target_branch="main", title="t", description="d"
            )

    mr = asyncio.run(go())
    assert isinstance(mr, MRInfo)
    assert mr.url == "https://gl/-/merge_requests/1" and mr.iid == 1


def test_open_mr_retries_then_succeeds() -> None:
    async def go() -> tuple[MRInfo, int]:
        resp = httpx.Response(201, json={"web_url": "u", "iid": 9})
        fake = AsyncMock()
        fake.__aenter__.return_value.post.side_effect = [
            httpx.ConnectError("boom"),
            httpx.ConnectError("boom"),
            resp,
        ]
        sleep = AsyncMock()
        with patch("loopctl.integrations.gitlab.httpx.AsyncClient", return_value=fake):
            client = HttpGitLabClient(token="t", base_url="https://gl", retry_max=3, sleep=sleep)
            mr = await client.open_mr(
                project_id=1, source_branch="b", target_branch="main", title="t", description="d"
            )
        return mr, fake.__aenter__.return_value.post.call_count

    mr, calls = asyncio.run(go())
    assert mr.iid == 9
    assert calls == 3


def test_open_mr_exhausted_raises() -> None:
    async def go() -> None:
        fake = AsyncMock()
        fake.__aenter__.return_value.post.side_effect = httpx.ConnectError("boom")
        sleep = AsyncMock()
        with patch("loopctl.integrations.gitlab.httpx.AsyncClient", return_value=fake):
            client = HttpGitLabClient(token="t", base_url="https://gl", retry_max=2, sleep=sleep)
            await client.open_mr(
                project_id=1, source_branch="b", target_branch="main", title="t", description="d"
            )

    with pytest.raises(GitLabError) as exc:
        asyncio.run(go())
    assert exc.value.kind == "api_error"


def test_push_branch_failure_raises() -> None:
    async def go() -> None:
        proc = AsyncMock()
        proc.communicate.return_value = (b"", b"rejected")
        proc.returncode = 1
        with patch("loopctl.integrations.gitlab.asyncio.create_subprocess_exec", return_value=proc):
            client = HttpGitLabClient(retry_max=1)
            await client.push_branch(workdir=pathlib.Path("."), branch="b")

    with pytest.raises(GitLabError):
        asyncio.run(go())
