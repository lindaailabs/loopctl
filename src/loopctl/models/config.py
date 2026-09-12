"""Default limits and operational thresholds.

All upper bounds from SPEC §5.3 are centralized here so project-level
configuration can override them.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Limits:
    engine_timeout_min: float = 30.0
    fix_loop_max: int = 3
    budget_usd: float = 5.0
    heartbeat_idle_min: float = 10.0

    @classmethod
    def from_config(cls, data: dict) -> Limits:
        """Build limits from a project [limits] section, falling back to defaults."""
        return cls(
            engine_timeout_min=float(data.get("engine_timeout_min", cls.engine_timeout_min)),
            fix_loop_max=int(data.get("fix_loop_max", cls.fix_loop_max)),
            budget_usd=float(data.get("budget_usd", cls.budget_usd)),
            heartbeat_idle_min=float(data.get("heartbeat_idle_min", cls.heartbeat_idle_min)),
        )
