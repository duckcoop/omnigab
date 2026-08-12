"""Multi-board job search tool.

Searches every job board that publishes a usable public API, and returns
ready-made browser links for the boards that prohibit automation.

Companion to `usajobs_search`, which stays separate because federal
postings carry extra structure (series codes, clearance, grade) that
private-sector boards do not have.
"""

from __future__ import annotations

from typing import Any

from jobs import (
    HANDOFF,
    GreenhouseBoard,
    LeverBoard,
    default_registry,
    search_many,
)


class JobBoardsTool:
    name = "job_boards_search"
    description = (
        "Search private-sector job boards (Amazon Jobs, RemoteOK, and any "
        "Greenhouse or Lever company board). Also returns prefilled search "
        "links for LinkedIn, Handshake, and Indeed, which prohibit "
        "automated access. Use usajobs_search for federal jobs instead."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Job title or keywords, e.g. 'help desk'.",
            },
            "location": {
                "type": "string",
                "description": "City, state, or 'Remote'. Optional.",
            },
            "sources": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Source keys to search. Omit for all. "
                               "Options: amazon, remoteok, linkedin, "
                               "handshake, indeed_web.",
            },
            "greenhouse_company": {
                "type": "string",
                "description": "Greenhouse board token, e.g. 'stripe'. "
                               "Optional.",
            },
            "lever_company": {
                "type": "string",
                "description": "Lever company token, e.g. 'netflix'. "
                               "Optional.",
            },
            "limit": {
                "type": "integer",
                "description": "Max results per source. Default 10.",
            },
        },
        "required": ["query"],
    }

    def run(self, arguments: dict[str, Any]) -> dict[str, Any]:
        query = str(arguments.get("query") or "").strip()
        if not query:
            return {"ok": False, "error": "query is required"}

        location = str(arguments.get("location") or "").strip()
        try:
            limit = max(1, min(int(arguments.get("limit") or 10), 25))
        except (TypeError, ValueError):
            limit = 10

        registry = default_registry()
        wanted = arguments.get("sources")
        if wanted:
            chosen = [registry[k] for k in wanted if k in registry]
            if not chosen:
                return {"ok": False,
                        "error": f"No known sources in {wanted}. "
                                 f"Available: {sorted(registry)}"}
        else:
            chosen = list(registry.values())

        # Company-specific boards are opt-in, since they need a token.
        gh = str(arguments.get("greenhouse_company") or "").strip()
        if gh:
            chosen.append(GreenhouseBoard(company=gh))
        lv = str(arguments.get("lever_company") or "").strip()
        if lv:
            chosen.append(LeverBoard(company=lv))

        payload = search_many(chosen, query, location, limit_each=limit)
        payload["sources_searched"] = [
            s.key for s in chosen if s.access != HANDOFF
        ]
        return payload


def build_tool() -> JobBoardsTool:
    return JobBoardsTool()
