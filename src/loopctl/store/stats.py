"""Append-only stats.jsonl and aggregation for the `stats` command."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any


def append_stat(stats_path: Path, record: dict[str, Any]) -> None:
    """Upsert one stats record keyed by ``task_id`` (SPEC §6.2: one row per task).

    Re-reading and rewriting keeps the file append-style (one JSON object per line)
    while guaranteeing a single row per task even when a task escalates and is later
    resumed to a terminal state.
    """
    stats_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"ts": time.time(), **record}
    rows: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    if stats_path.exists():
        with stats_path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    parsed = json.loads(line)
                except json.JSONDecodeError:
                    continue
                tid = parsed.get("task_id")
                if tid not in rows:
                    order.append(tid)
                rows[tid] = parsed
    tid = payload.get("task_id")
    if tid not in rows:
        order.append(tid)
    rows[tid] = payload
    with stats_path.open("w", encoding="utf-8") as f:
        for key in order:
            f.write(json.dumps(rows[key], ensure_ascii=False) + "\n")


def aggregate(stats_path: Path) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    if stats_path.exists():
        with stats_path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    rows.append(json.loads(line))

    total = len(rows)
    outcomes = [r.get("outcome") for r in rows]
    done = outcomes.count("done")
    escalated = outcomes.count("escalated")
    failed = outcomes.count("failed")

    auto_to_mr = sum(1 for r in rows if r.get("auto_to_mr"))
    interventions = sum(int(r.get("interventions", 0)) for r in rows)
    fix_loops = sum(int(r.get("fix_loops", 0)) for r in rows)
    tokens = sum(int(r.get("tokens", 0)) for r in rows)
    cost = round(sum(float(r.get("cost_usd", 0.0)) for r in rows), 2)

    by_project: dict[str, dict[str, int]] = {}
    for r in rows:
        slug = r.get("project", "?")
        bucket = by_project.setdefault(slug, {"total": 0, "done": 0, "escalated": 0, "failed": 0})
        bucket["total"] += 1
        outcome = r.get("outcome")
        if outcome == "done":
            bucket["done"] += 1
        elif outcome == "escalated":
            bucket["escalated"] += 1
        elif outcome == "failed":
            bucket["failed"] += 1

    return {
        "total": total,
        "done": done,
        "escalated": escalated,
        "failed": failed,
        "auto_to_mr": auto_to_mr,
        "interventions": interventions,
        "fix_loops": fix_loops,
        "tokens": tokens,
        "cost_usd": cost,
        "success_rate": round(done / total, 3) if total else 0.0,
        "by_project": by_project,
    }
