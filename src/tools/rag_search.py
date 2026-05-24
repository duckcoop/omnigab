"""RAG search tool: look up the user's indexed documents."""

from __future__ import annotations

from typing import Any

from config import TOP_K
from security import strip_chat_tokens


class RagSearchTool:
    name = "rag_search"
    description = (
        "Search the user's local indexed documents (IT docs, uploaded files, "
        "resumes, etc.). Use this when the user asks about their own files."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "The search query."},
            "top_k": {"type": "integer", "description": "How many chunks to return (default 3, max 8)."},
        },
        "required": ["query"],
    }

    def __init__(self, *, embedder, store):
        self.embedder = embedder
        self.store = store

    def run(self, arguments: dict[str, Any]) -> dict[str, Any]:
        query = str(arguments.get("query") or "").strip()
        if not query:
            return {"chunks": [], "note": "Empty query."}
        try:
            top_k = max(1, min(8, int(arguments.get("top_k") or TOP_K)))
        except (TypeError, ValueError):
            top_k = TOP_K

        if self.store.size == 0:
            return {"chunks": [], "note": "No documents indexed."}

        vec = self.embedder.embed_query(query)
        hits = self.store.search(vec, top_k=top_k)
        chunks = []
        for chunk, score in hits:
            chunks.append({
                "text": strip_chat_tokens(chunk.text),
                "source": chunk.source_file,
                "chunk_index": chunk.chunk_index,
                "score": round(float(score), 4),
            })
        return {"chunks": chunks, "count": len(chunks)}
