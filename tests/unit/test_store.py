"""Tests for the task store, trace and stats persistence."""

from __future__ import annotations

from loopctl.models.task import Task
from loopctl.store.db import TaskStore
from loopctl.store.stats import aggregate, append_stat


def test_task_store_roundtrip(tmp_data_dir) -> None:
    store = TaskStore(tmp_data_dir / "loopctl.db")
    task = Task(id="t1", project="sample", requirement="do something")
    store.save(task)
    got = store.get("t1")
    assert got is not None and got.id == "t1"
    assert len(store.list_all()) == 1
    store.close()


def test_stats_append_and_aggregate(tmp_data_dir) -> None:
    stats_path = tmp_data_dir / "stats.jsonl"
    append_stat(
        stats_path,
        {
            "outcome": "done",
            "auto_to_mr": True,
            "interventions": 0,
            "fix_loops": 1,
            "tokens": 100,
            "cost_usd": 0.5,
        },
    )
    result = aggregate(stats_path)
    assert result["total"] == 1
    assert result["done"] == 1
    assert result["cost_usd"] == 0.5
    assert result["success_rate"] == 1.0
