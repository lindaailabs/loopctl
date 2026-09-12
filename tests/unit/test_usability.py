"""Regression tests for fail-fast runtime and safe workspace handling."""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

from loopctl.config.validation import runtime_issues
from loopctl.engines.base import EngineResult
from loopctl.graph.workflow import Workflow
from loopctl.integrations.gitlab import MRInfo
from loopctl.models.project import ProjectConfig
from loopctl.models.task import TaskState


async def _noop_notify(message: str) -> None:
    return None


class FakeEngine:
    name = "fake"

    async def execute(self, ctx, prompt: str) -> EngineResult:
        return EngineResult(success=True, stdout_summary="ok", branch="feature/fake")


class FakeGitLab:
    async def push_branch(self, **kwargs) -> None:
        return None

    async def open_mr(self, **kwargs) -> MRInfo:
        return MRInfo(url="https://gitlab.test/mr/1", iid=1)


def test_fake_runtime_allows_explicit_dry_run(tmp_path: Path) -> None:
    spec = tmp_path / "spec.md"
    spec.write_text("knowledge", encoding="utf-8")
    cfg = ProjectConfig(
        slug="demo",
        engine="fake",
        knowledge_path=str(tmp_path),
        spec_refs=["spec.md"],
    )
    assert runtime_issues(cfg) == []


def test_real_runtime_reports_missing_prerequisites(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("GITLAB_TOKEN", raising=False)
    cfg = ProjectConfig(slug="demo", engine="claude_code", repo_path=str(tmp_path))
    issues = runtime_issues(cfg)
    assert any("git repository" in issue for issue in issues)
    assert "test_cmd is required for a real run" in issues
    assert "gitlab_project_id is required" in issues
    assert "GITLAB_TOKEN is not configured" in issues


def test_false_engine_result_escalates(tmp_data_dir: Path) -> None:
    class FalseEngine(FakeEngine):
        async def execute(self, ctx, prompt: str) -> EngineResult:
            return EngineResult(success=False, stdout_summary="command failed")

    cfg = ProjectConfig(slug="sample", engine="fake", repo_path=str(tmp_data_dir))
    wf = Workflow(
        project=cfg,
        data_dir=tmp_data_dir,
        db_path=tmp_data_dir / "db.sqlite",
        engine=FalseEngine(),
        notifier=_noop_notify,
        gitlab=FakeGitLab(),
    )
    task_id = asyncio.run(wf.start("do work"))
    task = wf.store.get(task_id)
    assert task is not None
    assert task.state is TaskState.escalated
    assert task.failure_class == "engine_error"


def test_claude_engine_prepares_task_branch(tmp_data_dir: Path) -> None:
    repo = tmp_data_dir / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True)
    (repo / "README.md").write_text("seed", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=test",
            "-c",
            "user.email=test@example.com",
            "commit",
            "-m",
            "seed",
        ],
        cwd=repo,
        check=True,
        capture_output=True,
    )

    class ClaudeLikeFake(FakeEngine):
        name = "claude_code"

    cfg = ProjectConfig(
        slug="sample",
        engine="claude_code",
        repo_path=str(repo),
        test_cmd='python -c "pass"',
    )
    wf = Workflow(
        project=cfg,
        data_dir=tmp_data_dir,
        db_path=tmp_data_dir / "db.sqlite",
        engine=ClaudeLikeFake(),
        notifier=_noop_notify,
        gitlab=FakeGitLab(),
    )
    task_id = asyncio.run(wf.start("do work"))
    task = wf.store.get(task_id)
    assert task is not None
    assert task.state is TaskState.awaiting_plan_approval
    assert task.branch == f"loopctl/{task_id}"
    branch = subprocess.run(
        ["git", "branch", "--show-current"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert branch == task.branch
