"""Tests for the enriched stats aggregation (M4-lite)."""

from __future__ import annotations

from pathlib import Path

from loopctl.store.stats import aggregate, append_stat


def test_aggregate_enriches_totals_and_per_project(tmp_data_dir: Path) -> None:
    stats_path = tmp_data_dir / "stats.jsonl"
    append_stat(
        stats_path,
        {
            "task_id": "a-1",
            "project": "alpha",
            "outcome": "done",
            "auto_to_mr": True,
            "interventions": 0,
            "fix_loops": 1,
            "tokens": 100,
            "cost_usd": 0.5,
            "duration_s": 100,
            "failure_class": None,
        },
    )
    append_stat(
        stats_path,
        {
            "task_id": "a-2",
            "project": "alpha",
            "outcome": "escalated",
            "auto_to_mr": False,
            "interventions": 1,
            "fix_loops": 0,
            "tokens": 50,
            "cost_usd": 0.25,
            "duration_s": 50,
            "failure_class": "engine_timeout",
        },
    )
    append_stat(
        stats_path,
        {
            "task_id": "b-1",
            "project": "beta",
            "outcome": "done",
            "auto_to_mr": True,
            "interventions": 0,
            "fix_loops": 0,
            "tokens": 200,
            "cost_usd": 1.0,
            "duration_s": 200,
            "failure_class": None,
        },
    )

    result = aggregate(stats_path)
    assert result["total"] == 3
    assert result["done"] == 2
    assert result["escalated"] == 1
    assert result["avg_duration_s"] == 116.7  # (100+50+200)/3
    assert result["avg_cost_usd"] == round(1.75 / 3, 4)
    assert result["success_rate"] == round(2 / 3, 3)

    alpha = result["by_project"]["alpha"]
    assert alpha["total"] == 2
    assert alpha["done"] == 1
    assert alpha["escalated"] == 1
    assert alpha["success_rate"] == 0.5
    assert alpha["avg_cost_usd"] == round(0.75 / 2, 4)

    beta = result["by_project"]["beta"]
    assert beta["success_rate"] == 1.0
    assert beta["avg_duration_s"] == 200.0


def test_aggregate_empty_is_safe(tmp_data_dir: Path) -> None:
    result = aggregate(tmp_data_dir / "stats.jsonl")
    assert result["total"] == 0
    assert result["avg_duration_s"] == 0.0
    assert result["success_rate"] == 0.0
