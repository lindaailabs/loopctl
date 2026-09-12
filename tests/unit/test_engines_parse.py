"""Stream-json parsing test using a recorded claude output fixture."""

from __future__ import annotations

import json
from pathlib import Path

from loopctl.engines.claude_code import ClaudeCodeBackend

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "stream_sample.jsonl"


def test_accumulate_parses_text_tokens_and_cost() -> None:
    backend = ClaudeCodeBackend()
    text_parts: list[str] = []
    stats: dict[str, float] = {"tokens": 0.0, "cost": 0.0}

    for line in FIXTURE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        backend._accumulate(json.loads(line), text_parts, stats)

    combined = "\n".join(text_parts)
    assert "negative-value validation" in combined
    assert "All checks pass" in combined
    assert stats["tokens"] == 1200
    assert stats["cost"] == 0.012
