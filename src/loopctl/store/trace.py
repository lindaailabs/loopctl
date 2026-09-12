"""Line-delimited JSON trace writer (one file per task)."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any


class TraceWriter:
    def __init__(self, traces_dir: Path, task_id: str) -> None:
        self.path = traces_dir / f"{task_id}.jsonl"
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, event: dict[str, Any]) -> None:
        record = {"ts": time.time(), **event}
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
