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
                "enum": ["remember", "search", "list", "forget", "clear_all"],
            },
            "category": {
                "type": "string",
                "enum": ["preference", "fact", "instruction", "context"],
                "description": "Type of memory. Default: fact.",
            },
            "key": {"type": "string"},
            "value": {"type": "string"},
            "term": {"type": "string", "description": "Search term for action=search"},
            "id": {"type": "integer", "description": "Row id for action=forget"},
        },
        "required": ["action"],
    }

    def __init__(self, *, persistent_memory):
        self.pm = persistent_memory

    def run(self, arguments: dict[str, Any]) -> dict[str, Any]:
        action = str(arguments.get("action") or "").lower()
        category = str(arguments.get("category") or "fact")

        if action == "remember":
            value = str(arguments.get("value") or "").strip()
            if not value:
                return {"ok": False, "error": "remember requires value"}
            # `key` is optional from slash-command callers (/remember <text>);
            # auto-generate one from the first few words so put() always has
            # something to hash on.
            key = str(arguments.get("key") or "").strip()
            if not key:
                key = " ".join(value.split()[:6])[:80] or "fact"
            row_id = self.pm.put(category, key, value, source="agent")
            return {"ok": True, "id": row_id, "stored": {category: {key: value}}}

        if action == "search":
            term = str(arguments.get("term") or arguments.get("key") or "").strip()
            if not term:
                # Treat empty search as "list everything", which is what users
                # expect when they type `/memory` with no args.
                rows = self.pm.list_all() if hasattr(self.pm, "list_all") else self.pm.all_rows()
                return {"ok": True, "rows": rows, "count": len(rows)}
            rows = self.pm.search(term)
            return {"ok": True, "matches": rows, "rows": rows, "count": len(rows)}

        if action == "list":
            # No category filter → return everything so /memory shows the
            # full store, not just one category bucket.
            if not arguments.get("category"):
                rows = self.pm.list_all() if hasattr(self.pm, "list_all") else self.pm.all_rows()
                return {"ok": True, "rows": rows, "count": len(rows)}
            rows = self.pm.list_by_category(category)
            return {"ok": True, "category": category, "rows": rows, "count": len(rows)}

        if action == "forget":
            row_id = arguments.get("id")
            if row_id is not None:
                try:
                    rid = int(row_id)
                except (TypeError, ValueError):
                    return {"ok": False, "error": "id must be an integer"}
                # Use a direct delete-by-id if the store supports it.
                if hasattr(self.pm, "forget_by_id"):
                    removed = self.pm.forget_by_id(rid)
                    return {"ok": True, "removed": removed}
                # Fallback: list all, find the matching row, forget by key.
                all_rows = (self.pm.list_all() if hasattr(self.pm, "list_all")
                            else self.pm.all_rows())
                for row in all_rows:
                    if row.get("id") == rid:
                        removed = self.pm.forget(category=row.get("category"),
                                                  key=row.get("key"))
                        return {"ok": True, "removed": removed}
                return {"ok": False, "error": f"no row with id {rid}"}
            key = arguments.get("key")
            removed = self.pm.forget(category=category if category else None, key=key)
            return {"ok": True, "removed": removed}

        if action == "clear_all":
            if hasattr(self.pm, "clear_all"):
                removed = self.pm.clear_all()
            else:
                # Fallback: forget each row individually.
                rows = (self.pm.list_all() if hasattr(self.pm, "list_all")
                        else self.pm.all_rows())
                removed = 0
                for row in rows:
                    removed += self.pm.forget(category=row.get("category"),
                                               key=row.get("key"))
            return {"ok": True, "removed": removed}

        return {"ok": False, "error": f"unknown action: {action}"}
