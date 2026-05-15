"""
Web UI for the RAG Agent
========================
FastAPI backend serving a chat interface. Run with:
    python web_app.py
Then open http://localhost:8080 in your browser.
"""

import sys
import time
import json
import uuid
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
import uvicorn

from config import (
    DOCS_DIR, EMBEDDING_MODEL, USE_GGUF,
    FAITHFULNESS_THRESHOLD, WEB_SEARCH_ENABLED,
    AVAILABLE_MODELS, MODELS_DIR,
)
from rag_agent import RAGAgent

app = FastAPI(title="Local RAG Agent")
agent = None

# Per-session conversation histories
sessions = {}
MAX_SESSIONS = 50


def get_agent():
    global agent
    if agent is None:
        agent = RAGAgent(load_gen=True)
        agent.load_index()
    return agent


def get_session_history(session_id):
    if session_id not in sessions:
        if len(sessions) >= MAX_SESSIONS:
            oldest = next(iter(sessions))
            del sessions[oldest]
        sessions[session_id] = []
    return sessions[session_id]


@app.on_event("startup")
def startup():
    print("Loading RAG Agent...")
    get_agent()
    print("Ready! Open http://localhost:8080")


@app.get("/", response_class=HTMLResponse)
def serve_ui():
    html_path = Path(__file__).parent / "static" / "index.html"
    return html_path.read_text(encoding="utf-8")


@app.get("/api/session")
def api_new_session():
    sid = str(uuid.uuid4())[:8]
    sessions[sid] = []
    return JSONResponse({"session_id": sid})


@app.post("/api/query")
async def api_query(request: Request):
    body = await request.json()
    question = body.get("question", "").strip()
    session_id = body.get("session_id", "default")
    if not question:
        return JSONResponse({"error": "No question provided"}, status_code=400)

    a = get_agent()
    history = get_session_history(session_id)
    a.history = history
    result = a.query(question, verbose=False)
    sessions[session_id] = a.history[:]

    v = result.get("verification")
    resp = {
        "answer": result["answer"],
        "sources": result["sources"],
        "faithfulness": round(v.faithfulness_score, 2) if v else None,
        "correction_rounds": result["correction_rounds"],
        "tokens": result.get("tokens", 0),
        "tps": result.get("tps", 0),
        "retrieve_time": result["retrieve_time"],
        "generate_time": result["generate_time"],
    }
    return JSONResponse(resp)


@app.post("/api/query/stream")
async def api_query_stream(request: Request):
    body = await request.json()
    question = body.get("question", "").strip()
    session_id = body.get("session_id", "default")
    if not question:
        return JSONResponse({"error": "No question provided"}, status_code=400)

    a = get_agent()
    history = get_session_history(session_id)
    a.history = history

    def event_stream():
        for chunk in a.query_stream(question):
            yield "data: " + json.dumps(chunk) + "\n\n"
        sessions[session_id] = a.history[:]
        yield "data: [DONE]\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


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
        "active_sessions": len(sessions),
    })


@app.get("/api/memory")
def api_memory():
    a = get_agent()
    return JSONResponse(a.memory.get_all())


@app.post("/api/memory")
async def api_memory_update(request: Request):
    body = await request.json()
    a = get_agent()
    action = body.get("action", "")

    if action == "set":
        key = body.get("key", "")
        value = body.get("value", "")
        if key in ("location", "units", "language"):
            a.memory.set(key, value)
        else:
            a.memory.learn_fact(key, value)
        return JSONResponse({"status": "ok", "memory": a.memory.get_all()})

    elif action == "remember":
        instruction = body.get("instruction", "")
        a.memory.add_instruction(instruction)
        return JSONResponse({"status": "ok", "memory": a.memory.get_all()})

    elif action == "forget":
        instruction = body.get("instruction", "")
        a.memory.remove_instruction(instruction)
        a.memory.forget_fact(instruction)
        return JSONResponse({"status": "ok", "memory": a.memory.get_all()})

    elif action == "clear":
        a.memory.clear()
        return JSONResponse({"status": "ok", "memory": a.memory.get_all()})

    return JSONResponse({"error": "Unknown action"}, status_code=400)


@app.get("/api/models")
def api_models():
    models = []
    for filename, info in AVAILABLE_MODELS.items():
        path = MODELS_DIR / filename
        models.append({
            "filename": filename,
            "name": info["name"],
            "size": info["size"],
            "ram": info["ram"],
            "repo": info["repo"],
            "downloaded": path.exists(),
        })
    return JSONResponse(models)


@app.post("/api/clear_history")
async def api_clear_history(request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    session_id = body.get("session_id", "default")
    if session_id in sessions:
        sessions[session_id] = []
    a = get_agent()
    a.history = []
    return JSONResponse({"status": "ok"})


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8080)
