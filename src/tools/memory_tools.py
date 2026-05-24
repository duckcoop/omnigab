"""Memory tools: let the agent read and update persistent user preferences."""

from __future__ import annotations

from typing import Any


class MemoryReadTool:
    name = "memory_read"
    description = (
        "Read the user's stored memory (preferences, location, learned facts, "
        "custom instructions). Use when answering depends on prior preferences."
    )
    input_schema = {"type": "object", "properties": {}, "required": []}

    def __init__(self, *, memory):
        self.memory = memory

    def run(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return self.memory.get_all()


class MemoryWriteTool:
    name = "memory_write"
    description = (
        "Save a fact or preference for future conversations. Use this when the "
        "user says 'remember', 'my name is', 'I live in', etc."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["set", "remember", "forget", "clear"],
                "description": "set = key/value fact; remember = custom instruction; forget = remove by text; clear = wipe everything",
            },
            "key": {"type": "string", "description": "Required for action=set."},
            "value": {"type": "string", "description": "Required for action=set."},
            "instruction": {"type": "string", "description": "Required for action=remember or action=forget."},
        },
        "required": ["action"],
    }

    def __init__(self, *, memory):
        self.memory = memory

    def run(self, arguments: dict[str, Any]) -> dict[str, Any]:
        action = str(arguments.get("action") or "").lower()
        if action == "set":
            key = str(arguments.get("key") or "").strip()
            value = str(arguments.get("value") or "").strip()
            if not key or not value:
                return {"ok": False, "error": "set requires key and value"}
            if key in ("location", "units", "language"):
                self.memory.set(key, value)
            else:
                self.memory.learn_fact(key, value)
            return {"ok": True, "stored": {key: value}}
        if action == "remember":
            instruction = str(arguments.get("instruction") or "").strip()
            if not instruction:
                return {"ok": False, "error": "remember requires instruction"}
            self.memory.add_instruction(instruction)
            return {"ok": True, "stored": instruction}
        if action == "forget":
            instruction = str(arguments.get("instruction") or "").strip()
            removed = (self.memory.remove_instruction(instruction)
                       or self.memory.forget_fact(instruction))
            return {"ok": bool(removed), "removed": instruction}
        if action == "clear":
            self.memory.clear()
            return {"ok": True, "cleared": True}
        return {"ok": False, "error": f"unknown action: {action}"}
