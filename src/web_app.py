"""
Web UI for the RAG Agent
========================
FastAPI backend serving a chat interface. Run with:
    python web_app.py
Then open http://localhost:8000 in your browser.
"""

import sys
import time
import json
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
import uvicorn

from config import (
    DOCS_DIR, EMBEDDING_MODEL, USE_GGUF,
    FAITHFULNESS_THRESHOLD, WEB_SEARCH_ENABLED,
)
from rag_agent import RAGAgent

app = FastAPI(title="Local RAG Agent")
agent = None


def get_agent():
    global agent
    if agent is None:
        agent = RAGAgent(load_gen=True)
        agent.load_index()
    return agent


@app.on_event("startup")
def startup():
    print("Loading RAG Agent...")
    get_agent()
    print("Ready! Open http://localhost:8000")


@app.get("/", response_class=HTMLResponse)
def serve_ui():
    html_path = Path(__file__).parent / "static" / "index.html"
    return html_path.read_text(encoding="utf-8")


@app.post("/api/query")
async def api_query(request: Request):
    body = await request.json()
    question = body.get("question", "").strip()
    if not question:
        return JSONResponse({"error": "No question provided"}, status_code=400)

    a = get_agent()
    result = a.query(question, verbose=False)

    v = result.get("verification")
    response = {
        "answer": result["answer"],
        "sources": result["sources"],
        "faithfulness": round(v.faithfulness_score, 2) if v else None,
        "correction_rounds": result["correction_rounds"],
        "tokens": result.get("tokens", 0),
        "tps": result.get("tps", 0),
        "retrieve_time": result["retrieve_time"],
        "generate_time": result["generate_time"],
    }
    return JSONResponse(response)


@app.post("/api/ingest")
async def api_ingest():
    a = get_agent()
    success = a.ingest()
    if success:
        a.load_index()
        return JSONResponse({"status": "ok", "vectors": a.store.size})
    return JSONResponse({"status": "error", "message": "No documents found"}, status_code=400)


@app.get("/api/status")
def api_status():
    a = get_agent()
    return JSONResponse({
        "embedding": EMBEDDING_MODEL,
        "generator": "GGUF/llama-cpp" if USE_GGUF else "HuggingFace",
        "index_size": a.store.size,
        "web_search": WEB_SEARCH_ENABLED and a.web_search is not None,
        "verification_threshold": FAITHFULNESS_THRESHOLD,
    })


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
