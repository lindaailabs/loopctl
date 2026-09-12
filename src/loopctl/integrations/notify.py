"""Notification delivery via ntfy (single HTTP POST; SPEC §7).

The notifier is injected into the workflow so unit tests can supply a stub and
avoid network access.
"""

from __future__ import annotations

import os
from typing import Protocol

import httpx


class Notifier(Protocol):
    async def __call__(self, message: str) -> None: ...


async def ntfy_notify(message: str, *, url: str | None = None) -> None:
    target = url or os.environ.get("NTFY_URL")
    if not target:
        return
    async with httpx.AsyncClient() as client:
        await client.post(target, content=message)


async def noop_notify(message: str) -> None:  # pragma: no cover - test helper
    """Drop notifications; used when no NTFY_URL is configured or in tests."""
    return
