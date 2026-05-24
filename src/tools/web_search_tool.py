"""Web search tool (wraps DuckDuckGo via web_search.py)."""

from __future__ import annotations

from typing import Any


class WebSearchTool:
    name = "web_search"
    description = (
        "Search the public web (DuckDuckGo) for current information, news, "
        "documentation, or anything outside the user's local documents. "
        "Returns snippet text and URLs."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "What to search for."},
            "max_results": {"type": "integer", "description": "Number of results (default 3, max 8)."},
        },
        "required": ["query"],
    }

    def __init__(self, *, web_search):
        self.web_search = web_search

    def run(self, arguments: dict[str, Any]) -> dict[str, Any]:
        query = str(arguments.get("query") or "").strip()
        if not query:
            return {"results": [], "note": "Empty query."}
        try:
            max_results = max(1, min(8, int(arguments.get("max_results") or 3)))
        except (TypeError, ValueError):
            max_results = 3

        try:
            raw = self.web_search.search(query, max_results=max_results)
        except TypeError:
            raw = self.web_search.search(query)

        results = []
        for chunk, score in (raw or []):
            results.append({
                "title": getattr(chunk, "source_file", "web"),
                "text": getattr(chunk, "text", "")[:600],
                "score": round(float(score), 4),
            })
        return {"results": results, "count": len(results)}
