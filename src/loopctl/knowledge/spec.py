"""Explicit spec reference loading (no retrieval; SPEC §1.2)."""

from __future__ import annotations

from pathlib import Path


def load_spec(project_dir: Path, spec_refs: list[str]) -> str:
    """Load the spec references listed in project.toml and concatenate them.

    Each ref is relative to the project directory (the playbook projects/<slug>/
    folder in production). Directories are expanded to their markdown files.
    """
    chunks: list[str] = []
    for ref in spec_refs:
        path = project_dir / ref
        if path.is_dir():
            for doc in sorted(path.rglob("*.md")):
                rel = doc.relative_to(project_dir)
                chunks.append(f"# {rel}\n\n{doc.read_text(encoding='utf-8')}")
        elif path.exists():
            chunks.append(f"# {ref}\n\n{path.read_text(encoding='utf-8')}")
    return "\n\n".join(chunks)
