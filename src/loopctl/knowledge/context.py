"""Prompt assembly.

All prompt text for the engine is composed here; `engines/` never makes business
decisions (SPEC §4.1).
"""

from __future__ import annotations


def assemble_plan_prompt(requirement: str, spec_context: str) -> str:
    return (
        "You are planning an implementation. Requirement:\n"
        f"{requirement}\n\n"
        "Relevant project spec:\n"
        f"{spec_context or '(none)'}\n\n"
        "Produce a concise plan covering: goal, estimated changed files, test plan, "
        "and risks."
    )


def assemble_exec_prompt(plan: str, spec_context: str) -> str:
    return (
        "Implement the following plan in the current repository. Make the code "
        "changes and add or adjust tests so they pass.\n\n"
        f"Plan:\n{plan}\n\n"
        f"Project spec:\n{spec_context or '(none)'}\n"
    )


def assemble_fix_prompt(plan: str, failure: str, spec_context: str) -> str:
    return (
        "The previous implementation did not pass tests. Fix the code based on the "
        "failure details without deviating from the overall plan.\n\n"
        f"Plan:\n{plan}\n\n"
        f"Test failure:\n{failure}\n\n"
        f"Project spec:\n{spec_context or '(none)'}\n"
    )
