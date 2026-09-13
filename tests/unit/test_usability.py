"""Regression tests for fail-fast runtime and safe workspace handling."""

from __future__ import annotations

import asyncio
import re
import subprocess
from pathlib import Path

import pytest

from loopctl.config.validation import runtime_issues
from loopctl.engines.base import EngineError, EngineResult
from loopctl.graph.workflow import Workflow
from loopctl.integrations.gitlab import MRInfo
from loopctl.models.project import ProjectConfig
from loopctl.models.task import Task, TaskState


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


def _init_repo(repo: Path) -> None:
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "master"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "test"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    (repo / "README.md").write_text("seed", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "seed"], cwd=repo, check=True, capture_output=True)


def _claude_workflow(tmp_data_dir: Path, repo: Path) -> Workflow:
    class ClaudeLikeFake(FakeEngine):
        name = "claude_code"

    cfg = ProjectConfig(
        slug="sample",
        engine="claude_code",
        repo_path=str(repo),
        default_branch="master",
        test_cmd='python -c "pass"',
    )
    return Workflow(
        project=cfg,
        data_dir=tmp_data_dir,
        db_path=tmp_data_dir / "db.sqlite",
        engine=ClaudeLikeFake(),
        notifier=_noop_notify,
        gitlab=FakeGitLab(),
    )


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
    _init_repo(repo)
    wf = _claude_workflow(tmp_data_dir, repo)
    task_id = asyncio.run(wf.start("增加负数校验", branch_name="negative_argument_validation"))
    task = wf.store.get(task_id)
    assert task is not None
    assert task.state is TaskState.awaiting_plan_approval
    assert task.branch is not None
    assert re.fullmatch(r"negative_argument_validation_\d{8}_\d{6}", task.branch)
    assert task.base_branch == "master"
    branch = subprocess.run(
        ["git", "branch", "--show-current"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert branch == task.branch


def test_git_commit_stages_only_reported_files(tmp_data_dir: Path) -> None:
    repo = tmp_data_dir / "repo"
    _init_repo(repo)
    wf = _claude_workflow(tmp_data_dir, repo)

    (repo / "reported.txt").write_text("include me", encoding="utf-8")
    (repo / "side-effect.txt").write_text("leave me alone", encoding="utf-8")
    asyncio.run(wf._git_commit(repo, "reported change", ["reported.txt"]))

    committed = subprocess.run(
        ["git", "show", "--name-only", "--format=", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    status = subprocess.run(
        ["git", "status", "--porcelain", "--", "side-effect.txt"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert committed == ["reported.txt"]
    assert status == "?? side-effect.txt"


def test_git_commit_refuses_unreported_dirty_tree(tmp_data_dir: Path) -> None:
    repo = tmp_data_dir / "repo"
    _init_repo(repo)
    wf = _claude_workflow(tmp_data_dir, repo)
    (repo / "unreported.txt").write_text("dirty", encoding="utf-8")

    with pytest.raises(EngineError) as exc:
        asyncio.run(wf._git_commit(repo, "should not commit", []))
    assert exc.value.kind == "environment_error"


def test_english_requirement_generates_branch_label(tmp_data_dir: Path) -> None:
    cfg = ProjectConfig(slug="sample", engine="fake")
    wf = Workflow(
        project=cfg,
        data_dir=tmp_data_dir,
        db_path=tmp_data_dir / "db.sqlite",
        engine=FakeEngine(),
        notifier=_noop_notify,
        gitlab=FakeGitLab(),
    )
    task = Task(id="sample-1", project="sample", requirement="Add negative argument validation")
    branch = wf._task_branch_name(task)
    assert re.fullmatch(r"add_negative_argument_validation_\d{8}_\d{6}", branch)
