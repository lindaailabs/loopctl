"""SQLite-backed task store and LangGraph async checkpointer factory."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from loopctl.models.task import Task


class TaskStore:
    """Stores task records (separate table from LangGraph's checkpoint tables)."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(db_path), timeout=30)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS tasks ("
            "id TEXT PRIMARY KEY, project TEXT, state TEXT, data TEXT)"
        )
        self.conn.commit()

    def save(self, task: Task) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO tasks (id, project, state, data) VALUES (?, ?, ?, ?)",
            (task.id, task.project, task.state.value, task.model_dump_json()),
        )
        self.conn.commit()

    def get(self, task_id: str) -> Task | None:
        row = self.conn.execute("SELECT data FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if not row:
            return None
        return Task.model_validate_json(row[0])

    def list_all(self) -> list[Task]:
        rows = self.conn.execute("SELECT data FROM tasks ORDER BY id").fetchall()
        return [Task.model_validate_json(r[0]) for r in rows]

    def close(self) -> None:
        self.conn.close()


def get_checkpointer(db_path: Path) -> AsyncSqliteSaver:
    """Async LangGraph checkpointer persisted to the same SQLite file."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return AsyncSqliteSaver.from_conn_string(str(db_path))
