"""Tests for `loopctl init` project registration (write_project)."""

from __future__ import annotations

from pathlib import Path

import pytest

from loopctl.config.loader import write_project


def _toml(path: Path) -> dict:
    import tomllib

    return tomllib.loads(path.read_text(encoding="utf-8"))


def test_write_project_creates_toml_spec_and_decisions(tmp_path: Path) -> None:
    root = tmp_path / "playbook" / "projects"
    created = write_project(
        "billing",
        display_name="Billing Service",
        engine="claude_code",
        git_remote="git@gl:billing.git",
        gitlab_project_id=123,
        test_cmd="pytest -q",
        root=root,
        local_dir=tmp_path / "local",
    )
    assert (root / "billing" / "project.toml").exists()
    assert (root / "billing" / "spec.md").exists()
    assert (root / "billing" / "decisions").is_dir()

    data = _toml(created["project_toml"])
    assert data["slug"] == "billing"
    assert data["engine"] == "claude_code"
    assert data["gitlab_project_id"] == 123
    assert data["spec_refs"] == ["spec.md"]
    assert data["limits"]["budget_usd"] == 5.0


def test_write_project_refuses_overwrite_without_force(tmp_path: Path) -> None:
    root = tmp_path / "playbook" / "projects"
    write_project("billing", root=root, local_dir=tmp_path / "local")
    with pytest.raises(FileExistsError):
        write_project("billing", root=root, local_dir=tmp_path / "local")
    # Force overwrites cleanly.
    write_project("billing", root=root, local_dir=tmp_path / "local", force=True)


def test_write_project_writes_local_override(tmp_path: Path) -> None:
    root = tmp_path / "playbook" / "projects"
    local = tmp_path / "local"
    created = write_project("billing", root=root, local_dir=local, repo_path="/srv/billing")
    assert "local_toml" in created
    assert (local / "billing.local.toml").read_text(
        encoding="utf-8"
    ).strip() == 'repo_path = "/srv/billing"'


def test_write_project_rejects_bad_slug(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        write_project("Bad Slug!", root=tmp_path / "p", local_dir=tmp_path / "l")


def test_write_project_rejects_unknown_engine(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        write_project(
            "billing", engine="does-not-exist", root=tmp_path / "p", local_dir=tmp_path / "l"
        )
