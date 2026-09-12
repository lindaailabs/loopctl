"""Task, plan and report domain models."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class TaskState(StrEnum):
    queued = "queued"
    clarifying = "clarifying"
    planning = "planning"
    awaiting_plan_approval = "awaiting_plan_approval"
    executing = "executing"
    testing = "testing"
    fixing = "fixing"
    reporting = "reporting"
    creating_mr = "creating_mr"  # M2
    awaiting_pr_review = "awaiting_pr_review"  # M2
    done = "done"
    failed = "failed"
    escalated = "escalated"
    cancelled = "cancelled"

    @property
    def is_terminal(self) -> bool:
        return self in {
            TaskState.done,
            TaskState.failed,
            TaskState.escalated,
            TaskState.cancelled,
        }


class Plan(BaseModel):
    goal: str = ""
    changed_files: list[str] = Field(default_factory=list)
    test_plan: str = ""
    risks: str = ""


class Report(BaseModel):
    summary: str = ""
    changed_files: list[str] = Field(default_factory=list)
    test_result: str = ""
    decisions: str = ""
    interventions: list[str] = Field(default_factory=list)
    distillation: str = ""


class Task(BaseModel):
    id: str
    project: str
    requirement: str
    state: TaskState = TaskState.queued
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    base_branch: str = "main"
    branch_name: str | None = None
    branch: str | None = None
    engine: str = "claude_code"
    plan: Plan | None = None
    report: Report | None = None
    feedback: str | None = None
    fix_loops: int = 0
    exec_retries: int = 0  # engine_timeout retries already attempted
    pending_retry: bool = False  # transient: re-enter the current node once
    mr_attempts: int = 0  # api_error retries already attempted (GitLab)
    tokens: int = 0
    cost_usd: float = 0.0
    last_event: str = ""
    failure_class: str | None = None
    spec: str = ""
    changed_files: list[str] = Field(default_factory=list)
    test_failure: str | None = None
    mr_url: str | None = None  # set once a GitLab MR is opened (M2)
