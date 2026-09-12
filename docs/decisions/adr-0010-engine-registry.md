# ADR-0010: Engine registry and declared-but-unimplemented backends

- Status: accepted (M4)
- Date: 2026-09-12

## Context

M0–M3 wired a single engine (`claude_code`) directly into the workflow: when no
engine was injected for tests, `Workflow` always fell back to `ClaudeCodeBackend()`,
ignoring the project's `engine = "..."` string in `project.toml`. That made the
`engine` field decorative and meant `loopctl init` / `load_project` could not
validate it. SPEC §1.2 also defers `codex` / `openhands` engines to a later phase
but still needs them to be *nameable* today.

## Decision

1. Introduce `engines/registry.py` mapping engine name → backend class
   (`ENGINE_REGISTRY`), with `get_engine(name)` and `register_engine(...)`.
2. `Workflow` resolves `project.engine` through the registry when no engine is
   injected (`engine or get_engine(self.project.engine)`). Injected engines (tests,
   supervisor factory) take precedence.
3. Register `claude_code` (implemented) and `fake` (a safe no-op dry-run backend).
4. Declare `codex` / `openhands` as stubs: present in the registry, but their
   `execute` raises `NotImplementedError` pointing at SPEC §1.2. They remain
   unimplemented by design.
5. `load_project` and `loopctl init` validate the engine name against the registry
   and reject unknown engines with a helpful message.

## Consequences

- The `engine` field in `project.toml` is now meaningful and validated end-to-end.
- New engines can be added by `register_engine` without touching `Workflow`.
- `codex` / `openhands` are discoverable via `loopctl engines` but fail loudly if
  used before they are implemented, avoiding silent "decorative" configuration.
