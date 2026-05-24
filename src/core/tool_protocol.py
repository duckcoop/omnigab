"""Shared types for the agent tool-calling protocol.

A Tool is anything with a `name`, a `description`, a JSON-schema-ish
`input_schema`, and a `run(arguments)` method that returns a
JSON-serialisable result. Built-in tools live in `src/tools/`; user
skills are adapted into Tools by `tools/skill_adapter.py` so the LLM
sees one unified catalog.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass
class ToolCall:
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolResult:
    name: str
    ok: bool
    output: Any  # must be JSON-serialisable
    error: str | None = None


@runtime_checkable
class Tool(Protocol):
    name: str
    description: str
    input_schema: dict[str, Any]

    def run(self, arguments: dict[str, Any]) -> Any: ...


@dataclass
class BasicTool:
    """Concrete Tool implementation usable as a base for built-ins."""

    name: str
    description: str
    input_schema: dict[str, Any]
    handler: Any = None  # Callable[[dict], Any]

    def run(self, arguments: dict[str, Any]) -> Any:
        if self.handler is None:
            raise NotImplementedError(f"Tool {self.name} has no handler")
        return self.handler(arguments)
