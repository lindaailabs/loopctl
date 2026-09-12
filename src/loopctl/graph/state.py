"""Graph state shared between workflow nodes."""

from __future__ import annotations

from typing import TypedDict


class GraphState(TypedDict):
    """The single mutable channel is the serialized Task.

    Storing one dict keeps checkpoint serialization trivial and lets every node
    re-hydrate a full `Task` via `Task.model_validate`.
    """

    task: dict
