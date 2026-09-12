"""Default limits and operational thresholds.

All upper bounds from SPEC §5.3 are centralized here so project-level
configuration can override them.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Limits:
    # Engine execution bounds (SPEC §5.3).
    engine_timeout_min: float = 30.0
    fix_loop_max: int = 3
    budget_usd: float = 5.0
    heartbeat_idle_min: float = 10.0
    # Reliability: retries and backoff (SPEC §5.3).
    exec_retry_max: int = 1  # engine_timeout retries before escalation
    mr_api_retry_max: int = 5  # api_error retries when talking to GitLab
    backoff_base_s: float = 2.0
    backoff_max_s: float = 60.0

    @classmethod
    def from_config(cls, data: dict) -> Limits:
        """Build limits from a project [limits] section, falling back to defaults."""
        return cls(
            engine_timeout_min=float(data.get("engine_timeout_min", cls.engine_timeout_min)),
            fix_loop_max=int(data.get("fix_loop_max", cls.fix_loop_max)),
            budget_usd=float(data.get("budget_usd", cls.budget_usd)),
            heartbeat_idle_min=float(data.get("heartbeat_idle_min", cls.heartbeat_idle_min)),
            exec_retry_max=int(data.get("exec_retry_max", cls.exec_retry_max)),
            mr_api_retry_max=int(data.get("mr_api_retry_max", cls.mr_api_retry_max)),
            backoff_base_s=float(data.get("backoff_base_s", cls.backoff_base_s)),
            backoff_max_s=float(data.get("backoff_max_s", cls.backoff_max_s)),
        )
