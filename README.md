# loopctl

> LangGraph-based control plane for coding agents.

`loopctl` orchestrates coding engines (such as Claude Code) as pluggable
execution units, driving a largely unattended **requirement → GitLab MR** loop
across multiple projects. Human involvement is consolidated into two gates:
plan approval and PR review.

This repository is the **tool** (open source). Project-specific knowledge
(specs, decisions, task reports) lives in a separate, private *playbook*
repository.

## Status

Active development — MVP (v0.1). See `docs/SPEC.md` for the authoritative
specification and `docs/decisions/` for the architecture decision records.

## Quick start

```bash
# Install (uv manages the environment)
uv sync

# Show the task board (empty before any task exists)
uv run loopctl status

# List registered projects
uv run loopctl projects

# Register a new project (writes project.toml + a spec.md stub under your playbook)
uv run loopctl init my-project --repo-path /path/to/repo

# List the available execution engines
uv run loopctl engines
```

Machine-specific configuration (repository paths, tokens, GitLab IDs) is injected
through configuration files and environment variables and is **never** committed.
See `docs/SPEC.md` §6 for the configuration model.

## Development

```bash
uv sync                  # install dependencies (including the dev group)
uvx ruff check .         # lint
uvx ruff format .        # format
uv run pytest            # run tests
```

## License

MIT — see `LICENSE`.
