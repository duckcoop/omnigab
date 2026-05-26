"""RAG search tool: look up the user's indexed documents.

Two-stage retrieval architecture:
  Stage 1 (bi-encoder, fast):  FAISS cosine over the existing index.
                                Returns top-K * 3 candidates.
  Stage 2 (cross-encoder, accurate):  BGE-reranker re-scores each
                                (query, candidate) pair jointly and picks
                                the top-K. Much higher precision than
                                bi-encoder alone — the standard upgrade
                                path for production RAG.

Reranker is opt-in via `rerank=true` (default true) and lazily loaded
on first use so app boot stays fast. Model: BAAI/bge-reranker-base
(~280 MB, fits in VRAM next to the LLM with q8_0 KV cache enabled).
"""

from __future__ import annotations

import threading
from typing import Any

from config import TOP_K
from security import strip_chat_tokens


# Module-level cached reranker so we only load the ~280 MB model once
# per process, no matter how many RagSearchTool instances exist.
_RERANKER = None
_RERANKER_LOCK = threading.Lock()
_RERANKER_MODEL = "BAAI/bge-reranker-base"


def _get_reranker():
    """Lazy-load the cross-encoder. Returns None if sentence-transformers
    isn't installed or model download fails (graceful degradation —
    we fall back to bi-encoder-only ranking).
    """
    global _RERANKER
    if _RERANKER is not None:
        return _RERANKER
    with _RERANKER_LOCK:
        if _RERANKER is not None:
            return _RERANKER
        try:
            from sentence_transformers import CrossEncoder
            _RERANKER = CrossEncoder(_RERANKER_MODEL, max_length=512)
            print(f"[rag_search] Reranker loaded: {_RERANKER_MODEL}")
        except Exception as exc:
            print(f"[rag_search] Reranker unavailable ({exc}); "
                  f"falling back to bi-encoder ranking.")
            _RERANKER = False   # sentinel: tried + failed
        return _RERANKER if _RERANKER is not False else None


class RagSearchTool:
    name = "rag_search"
    description = (
        "Search the user's local indexed documents (IT docs, uploaded files, "
        "resumes, etc.). Use this when the user asks about their own files. "
        "Uses two-stage retrieval: FAISS bi-encoder for speed + BGE "
        "cross-encoder rerank for precision."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "The search query."},
            "top_k": {"type": "integer",
                      "description": "How many chunks to return (default 3, max 8)."},
            "rerank": {"type": "boolean",
                       "description": "Apply cross-encoder rerank (default true). "
                                      "Set false for raw bi-encoder ranking."},
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
        rerank = arguments.get("rerank")
        rerank = True if rerank is None else bool(rerank)

        if self.store.size == 0:
            return {"chunks": [], "note": "No documents indexed."}

        # Stage 1: pull a wider candidate pool than the final top_k so the
        # cross-encoder has something useful to rerank.
        candidate_k = top_k * 3 if rerank else top_k
        candidate_k = min(candidate_k, self.store.size)
        vec = self.embedder.embed_query(query)
        hits = self.store.search(vec, top_k=candidate_k)

        ranking_mode = "bi-encoder"
        if rerank and len(hits) > 1:
            reranker = _get_reranker()
            if reranker is not None:
                pairs = [(query, strip_chat_tokens(c.text)) for c, _ in hits]
                try:
                    scores = reranker.predict(pairs)
                    # Pair each hit with its rerank score, sort desc, take top_k.
                    scored = sorted(
                        zip(hits, scores),
                        key=lambda x: float(x[1]),
                        reverse=True,
                    )
                    hits = [(h[0], float(s)) for (h, _), s in
                            zip(scored, [s for _, s in scored])]
                    hits = hits[:top_k]
                    ranking_mode = "bi-encoder + cross-encoder rerank"
                except Exception as exc:
                    print(f"[rag_search] Rerank failed ({exc}); using bi-encoder order.")
                    hits = hits[:top_k]
            else:
                hits = hits[:top_k]
        else:
            hits = hits[:top_k]

        chunks = []
        for chunk, score in hits:
            chunks.append({
                "text": strip_chat_tokens(chunk.text),
                "source": chunk.source_file,
                "chunk_index": chunk.chunk_index,
                "score": round(float(score), 4),
            })
        return {
            "chunks": chunks,
            "count": len(chunks),
            "ranking": ranking_mode,
        }
