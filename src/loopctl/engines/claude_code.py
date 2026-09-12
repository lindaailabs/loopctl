"""Claude Code engine backend.

Drives the `claude` CLI in headless mode (`claude -p`) with stream-json output.
Responsible for process lifecycle, stream parsing, timeout and heartbeat detection.
All prompt text is supplied by the caller (see `knowledge/`).
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

from loopctl.engines.base import EngineContext, EngineError, EngineResult


class ClaudeCodeBackend:
    name = "claude_code"

    def __init__(self, binary: str = "claude") -> None:
        self.binary = binary

    async def execute(self, ctx: EngineContext, prompt: str) -> EngineResult:
        cmd = [
            self.binary,
            "-p",
            prompt,
            "--output-format",
            "stream-json",
            "--verbose",
        ]
        start = time.monotonic()
        last_output = [start]
        exceeded: dict[str, str] = {}

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=str(ctx.workdir),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except OSError as exc:
            raise EngineError("api_error", f"failed to launch {self.binary}: {exc}") from exc

        text_parts: list[str] = []
        stats: dict[str, float] = {"tokens": 0.0, "cost": 0.0}

        async def _watchdog() -> None:
            while proc.returncode is None:
                await asyncio.sleep(2)
                now = time.monotonic()
                if now - last_output[0] > ctx.heartbeat_idle_min * 60:
                    exceeded["kind"] = "agent_stuck"
                    proc.kill()
                    return
                if now - start > ctx.timeout_min * 60:
                    exceeded["kind"] = "engine_timeout"
                    proc.kill()
                    return

        watchdog = asyncio.create_task(_watchdog())
        assert proc.stdout is not None
        try:
            async for raw in proc.stdout:
                last_output[0] = time.monotonic()
                line = raw.decode("utf-8", "replace").strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    continue
                self._accumulate(msg, text_parts, stats)
            await proc.wait()
        finally:
            if not watchdog.done():
                watchdog.cancel()
            else:
                await watchdog

        if exceeded:
            raise EngineError(exceeded["kind"], "claude subprocess timed out")

        summary = "\n".join(text_parts).strip()
        branch = await self._git_branch(ctx.workdir)
        changed = await self._git_changed(ctx.workdir)
        return EngineResult(
            success=proc.returncode == 0,
            branch=branch,
            changed_files=changed,
            stdout_summary=summary[-2000:],
            tokens=int(stats["tokens"]),
            cost_usd=round(float(stats["cost"]), 4),
            duration_s=round(time.monotonic() - start, 2),
        )

    @staticmethod
    def _accumulate(msg: dict, text_parts: list[str], stats: dict[str, float]) -> None:
        t = msg.get("type")
        if t == "result":
            content = msg.get("result") or msg.get("content")
            if content:
                text_parts.append(str(content))
            usage = msg.get("usage") or {}
            stats["tokens"] += int(usage.get("total_tokens", 0) or 0)
            stats["cost"] += float(msg.get("total_cost_usd", 0.0) or 0.0)
        elif t == "assistant":
            for block in msg.get("message", {}).get("content", []) or []:
                if isinstance(block, dict) and block.get("type") == "text":
                    text_parts.append(block.get("text", ""))

    async def _git_branch(self, workdir: Path) -> str | None:
        try:
            proc = await asyncio.create_subprocess_exec(
                "git",
                "-C",
                str(workdir),
                "rev-parse",
                "--abbrev-ref",
                "HEAD",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            out, _ = await proc.communicate()
            return out.decode().strip() or None
        except (OSError, ValueError):
            return None

    async def _git_changed(self, workdir: Path) -> list[str]:
        try:
            proc = await asyncio.create_subprocess_exec(
                "git",
                "-C",
                str(workdir),
                "diff",
                "--name-only",
                "HEAD",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            out, _ = await proc.communicate()
            return [ln for ln in out.decode().splitlines() if ln.strip()]
        except (OSError, ValueError):
            return []
