"""Knowledge layer: spec loading, prompt assembly, report distillation."""

from loopctl.knowledge.context import (
    assemble_exec_prompt,
    assemble_fix_prompt,
    assemble_plan_prompt,
)
from loopctl.knowledge.report import distill_report, render_report_markdown
from loopctl.knowledge.spec import load_spec

__all__ = [
    "assemble_exec_prompt",
    "assemble_fix_prompt",
    "assemble_plan_prompt",
    "distill_report",
    "load_spec",
    "render_report_markdown",
]
