"""Distill a task report from the run (SPEC §6.4 template)."""

from __future__ import annotations

from loopctl.models.task import Report, Task


def distill_report(
    *,
    requirement: str,
    plan_goal: str,
    changed_files: list[str],
    test_result: str,
    feedback: str | None = None,
    distillation: str = "",
) -> Report:
    interventions = [feedback] if feedback else []
    return Report(
        summary=requirement,
        changed_files=list(changed_files),
        test_result=test_result,
        decisions=plan_goal,
        interventions=interventions,
        distillation=distillation,
    )


def render_report_markdown(report: Report, task: Task) -> str:
    """Render a Report into the SPEC §6.4 markdown template."""
    changed = "\n".join(f"- {f}" for f in report.changed_files) or "- (none)"
    interventions = "\n".join(f"- {i}" for i in report.interventions) or "- (none)"
    duration = "n/a"
    if task.created_at and task.updated_at:
        duration = f"{(task.updated_at - task.created_at).total_seconds():.0f}s"
    return (
        f"# Task {task.id}: {report.summary}\n\n"
        f"项目: {task.project}  分支: {task.branch or '-'}  引擎: {task.engine}  "
        f"时长/成本: {duration} / ${task.cost_usd:.2f}\n\n"
        "## 结论\n\n"
        f"{report.test_result or report.summary}\n\n"
        "## 改动文件\n\n"
        f"{changed}\n\n"
        "## 测试结果\n\n"
        f"{report.test_result}\n\n"
        "## 决策与偏差\n\n"
        f"{report.decisions}\n\n"
        "## 人工介入记录\n\n"
        f"{interventions}\n\n"
        "## 蒸馏\n\n"
        f"{report.distillation}\n"
    )
