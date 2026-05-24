"""Tool wrapper around the SQLite PersistentMemory store."""

from __future__ import annotations

from typing import Any


class PersistentMemoryTool:
    name = "persistent_memory"
    description = (
        "Read or write the user's long-term memory (SQLite-backed, survives "
        "restarts and new sessions). Use `action=remember` to save a fact, "
        "`action=search` to look one up, `action=list` to dump a category, "
        "`action=forget` to remove."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["remember", "search", "list", "forget"],
            },
            "category": {
                "type": "string",
                "enum": ["preference", "fact", "instruction", "context"],
                "description": "Type of memory. Default: fact.",
            },
            "key": {"type": "string"},
            "value": {"type": "string"},
            "term": {"type": "string", "description": "Search term for action=search"},
        },
        "required": ["action"],
    }

    def __init__(self, *, persistent_memory):
        self.pm = persistent_memory

    def run(self, arguments: dict[str, Any]) -> dict[str, Any]:
        action = str(arguments.get("action") or "").lower()
        category = str(arguments.get("category") or "fact")

        if action == "remember":
            key = str(arguments.get("key") or "").strip()
            value = str(arguments.get("value") or "").strip()
            if not key or not value:
                return {"ok": False, "error": "remember requires key and value"}
            row_id = self.pm.put(category, key, value, source="agent")
            return {"ok": True, "id": row_id, "stored": {category: {key: value}}}

        if action == "search":
            term = str(arguments.get("term") or arguments.get("key") or "").strip()
            if not term:
                return {"ok": False, "error": "search requires term"}
            rows = self.pm.search(term)
            return {"ok": True, "matches": rows, "count": len(rows)}

        if action == "list":
            rows = self.pm.list_by_category(category)
            return {"ok": True, "category": category, "rows": rows, "count": len(rows)}

        if action == "forget":
            key = arguments.get("key")
            removed = self.pm.forget(category=category if category else None, key=key)
            return {"ok": True, "removed": removed}

        return {"ok": False, "error": f"unknown action: {action}"}
