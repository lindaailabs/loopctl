"""Tests for the global environment self-check (`loopctl doctor` with no --project)."""

from __future__ import annotations

from loopctl import scheduler
from loopctl.config.validation import global_environment_issues


def test_global_report_structure(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("LOOPCTL_PROJECTS_ROOT", str(tmp_path / "projects"))
    monkeypatch.setenv("LOOPCTL_DATA_DIR", str(tmp_path / "data"))
    report = scheduler.doctor(None)
    assert report["scope"] == "global"
    assert isinstance(report["ready"], bool)
    assert isinstance(report["issues"], list)
    assert set(report["tools"]) == {"claude", "git", "uv"}
    assert "data_dir" in report["paths"]


def test_global_environment_clean_when_root_exists(tmp_path, monkeypatch) -> None:
    (tmp_path / "projects").mkdir()
    monkeypatch.setenv("LOOPCTL_PROJECTS_ROOT", str(tmp_path / "projects"))
    monkeypatch.setenv("LOOPCTL_DATA_DIR", str(tmp_path / "data"))
    assert global_environment_issues() == []


def test_global_environment_flags_missing_root(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("LOOPCTL_PROJECTS_ROOT", str(tmp_path / "nope" / "projects"))
    monkeypatch.setenv("LOOPCTL_DATA_DIR", str(tmp_path / "data"))
    issues = global_environment_issues()
    assert any("projects_root" in i for i in issues)
