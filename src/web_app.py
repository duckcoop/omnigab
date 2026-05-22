"""
Web UI for the RAG Agent
========================
FastAPI backend serving a chat interface. Run with:
    python web_app.py
Then open http://localhost:8080 in your browser.
"""

import os
import sys
import time
import json
import uuid
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from starlette.middleware.base import BaseHTTPMiddleware
import uvicorn

from config import (
    DOCS_DIR, EMBEDDING_MODEL, EMBEDDING_DIMENSION, USE_GGUF,
    FAITHFULNESS_THRESHOLD, WEB_SEARCH_ENABLED,
    AVAILABLE_MODELS, MODELS_DIR, GGUF_MODEL_PATH,
    CONTEXT_WINDOW, N_THREADS, MAX_NEW_TOKENS, TEMPERATURE, TOP_P,
    save_selected_model,
)
from rag_agent import RAGAgent

app = FastAPI(title="Local RAG Agent")
agent = None

# Loopback addresses allowed to reach the API.
_LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost"}

# Optional shared secret for write endpoints. If set in the environment,
# clients must send it via the X-API-Token header on mutating requests.
_API_TOKEN = os.environ.get("RAG_API_TOKEN", "").strip()

# Methods that mutate state and therefore require the API token (when one is set).
_WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

# Endpoints that must remain reachable from the local UI without a token even
# when RAG_API_TOKEN is set (read-only or session bootstrapping).
_TOKEN_EXEMPT_PATHS = {"/", "/jobs", "/api/session"}


class LocalhostOnlyMiddleware(BaseHTTPMiddleware):
    """Reject any request whose peer is not on a loopback address."""

    async def dispatch(self, request: Request, call_next):
        client = request.client
        host = client.host if client else None
        if host not in _LOOPBACK_HOSTS:
            return JSONResponse({"error": "Forbidden"}, status_code=403)
        return await call_next(request)


class WriteTokenMiddleware(BaseHTTPMiddleware):
    """Require X-API-Token on write endpoints when a token is configured."""

    async def dispatch(self, request: Request, call_next):
        if not _API_TOKEN:
            return await call_next(request)
        if request.method in _WRITE_METHODS and request.url.path not in _TOKEN_EXEMPT_PATHS:
            supplied = request.headers.get("X-API-Token", "")
            if supplied != _API_TOKEN:
                return JSONResponse({"error": "Unauthorized"}, status_code=401)
        return await call_next(request)


app.add_middleware(WriteTokenMiddleware)
app.add_middleware(LocalhostOnlyMiddleware)

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
    if not html_path.exists():
        return HTMLResponse("<h1>index.html not found</h1><p>Place it in src/static/</p>", status_code=404)
    return html_path.read_text(encoding="utf-8")


@app.get("/jobs", response_class=HTMLResponse)
def serve_jobs_ui():
    html_path = Path(__file__).parent / "static" / "jobs.html"
    if not html_path.exists():
        return HTMLResponse("<h1>jobs.html not found</h1>", status_code=404)
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

# -- Job Agent Endpoints --
job_agent_instance = None
uploaded_resume_text = ""


def get_job_agent():
    global job_agent_instance
    if job_agent_instance is None:
        from job_agent import JobAgent
        a = get_agent()
        gen = a.generator if hasattr(a, 'generator') else None
        job_agent_instance = JobAgent(generator=gen)
    return job_agent_instance


@app.post("/api/jobs/upload-resume")
async def api_upload_resume(request: Request):
    global uploaded_resume_text
    body = await request.json()
    text = body.get("text", "").strip()
    if not text:
        return JSONResponse({"error": "No resume text provided"}, status_code=400)
    uploaded_resume_text = text
    ja = get_job_agent()
    ja.set_resume_text(text)
    return JSONResponse({"status": "ok", "length": len(text)})


@app.post("/api/jobs/search")
async def api_job_search(request: Request):
    body = await request.json()
    job_title = body.get("title", "").strip()
    location = body.get("location", "").strip()
    num_results = body.get("num_results", 10)

    if not job_title:
        return JSONResponse({"error": "No job title provided"}, status_code=400)

    ja = get_job_agent()

    # Load resume if not already loaded
    if not ja.resume_text:
        if uploaded_resume_text:
            ja.set_resume_text(uploaded_resume_text)
        else:
            loaded = ja.load_resume()
            if not loaded:
                return JSONResponse({
                    "error": "No resume found. Upload one or add a file with 'resume' in the name to data/docs/"
                }, status_code=400)

    jobs = ja.search_and_score(job_title, location, num_results)
    return JSONResponse({
        "status": "ok",
        "count": len(jobs),
        "jobs": ja.to_dict_list(n=len(jobs)),
    })


@app.post("/api/jobs/search/stream")
async def api_job_search_stream(request: Request):
    body = await request.json()
    job_title = body.get("title", "").strip()
    location = body.get("location", "").strip()
    num_results = body.get("num_results", 10)

    if not job_title:
        return JSONResponse({"error": "No job title provided"}, status_code=400)

    ja = get_job_agent()

    if not ja.resume_text:
        if uploaded_resume_text:
            ja.set_resume_text(uploaded_resume_text)
        else:
            loaded = ja.load_resume()
            if not loaded:
                return JSONResponse({
                    "error": "No resume found. Upload one first."
                }, status_code=400)

    def stream():
        from job_agent import search_jobs, _scrape_job_page, parse_job_from_search, score_job_with_llm

        yield "data: " + json.dumps({"type": "status", "message": "Searching Indeed..."}) + "\n\n"

        raw_results = search_jobs(job_title, location, num_results)
        if not raw_results:
            yield "data: " + json.dumps({"type": "error", "message": "No results found."}) + "\n\n"
            return

        yield "data: " + json.dumps({"type": "status", "message": f"Found {len(raw_results)} listings. Scraping..."}) + "\n\n"

        jobs = []
        for i, result in enumerate(raw_results):
            url = result.get("href", "")
            scraped = _scrape_job_page(url) if url else None
            job = parse_job_from_search(result, scraped)
            jobs.append(job)
            yield "data: " + json.dumps({"type": "progress", "step": "scrape", "current": i + 1, "total": len(raw_results)}) + "\n\n"

        if ja.generator:
            for i, job in enumerate(jobs):
                yield "data: " + json.dumps({"type": "status", "message": f"AI scoring {i+1}/{len(jobs)}: {job.title[:40]}..."}) + "\n\n"
                score, reason = score_job_with_llm(ja.generator, job, ja.resume_text)
                job.match_score = score
                job.match_reason = reason
                yield "data: " + json.dumps({"type": "job", "index": i, "job": job.to_dict()}) + "\n\n"

        jobs.sort(key=lambda j: j.match_score, reverse=True)
        ja.jobs = jobs

        yield "data: " + json.dumps({"type": "done", "count": len(jobs), "jobs": [j.to_dict() for j in jobs]}) + "\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")


@app.get("/api/jobs/pdf")
def api_job_pdf():
    ja = get_job_agent()
    if not ja.jobs:
        return JSONResponse({"error": "No job results yet. Run a search first."}, status_code=400)

    from job_report import generate_job_report
    output_path = Path(__file__).parent.parent / "job_results.pdf"
    generate_job_report(ja.get_top_jobs(5), output_path=output_path)

    pdf_bytes = output_path.read_bytes()
    from fastapi.responses import Response
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": "attachment; filename=job_results.pdf"},
    )


# -- Document Management Endpoints --
@app.get("/api/docs/list")
def api_docs_list():
    docs_dir = DOCS_DIR
    if not docs_dir.exists():
        return JSONResponse({"files": [], "total_size": 0})
    docs_root = docs_dir.resolve()
    files = []
    total_size = 0
    for f in sorted(docs_dir.rglob("*")):
        if f.is_symlink():
            continue
        try:
            if not f.resolve().is_relative_to(docs_root):
                continue
        except OSError:
            continue
        if f.is_file():
            size = f.stat().st_size
            total_size += size
            files.append({
                "name": str(f.relative_to(docs_dir)),
                "size": size,
                "extension": f.suffix.lower(),
            })
    return JSONResponse({"files": files, "total_size": total_size})


# -- Model Management Endpoints --
@app.post("/api/models/switch")
async def api_model_switch(request: Request):
    body = await request.json()
    filename = body.get("filename", "").strip()
    if not filename or filename not in AVAILABLE_MODELS:
        return JSONResponse({"error": "Invalid model"}, status_code=400)

    model_path = MODELS_DIR / filename
    if not model_path.exists():
        return JSONResponse({"error": "Model not downloaded"}, status_code=400)

    try:
        save_selected_model(filename)
    except (OSError, ValueError):
        return JSONResponse({"error": "Could not persist model selection"}, status_code=500)

    return JSONResponse({
        "status": "ok",
        "message": f"Switched to {AVAILABLE_MODELS[filename]['name']}. Restart the server to load it.",
        "model": filename,
    })


@app.get("/api/system")
def api_system_info():
    import platform
    import os
    a = get_agent()
    current_model = GGUF_MODEL_PATH.name if GGUF_MODEL_PATH.exists() else "not found"
    return JSONResponse({
        "platform": platform.platform(),
        "python": platform.python_version(),
        "cpu": platform.processor() or "Unknown",
        "threads": N_THREADS,
        "context_window": CONTEXT_WINDOW,
        "max_tokens": MAX_NEW_TOKENS,
        "temperature": TEMPERATURE,
        "top_p": TOP_P,
        "embedding_model": EMBEDDING_MODEL,
        "embedding_dim": EMBEDDING_DIMENSION,
        "current_model": current_model,
        "use_gguf": USE_GGUF,
        "index_size": a.store.size,
        "web_search": WEB_SEARCH_ENABLED,
        "faithfulness_threshold": FAITHFULNESS_THRESHOLD,
        "docs_dir": str(DOCS_DIR),
        "models_dir": str(MODELS_DIR),
    })


@app.get("/api/benchmark")
async def api_benchmark(request: Request):
    """Quick benchmark: generate a short response and return timing stats."""
    a = get_agent()
    test_q = "What is 2+2? Answer in one word."
    test_ctx = "Basic math: 2+2=4, 3+3=6, 4+4=8."
    import time as _time
    t0 = _time.time()
    answer = a.generator.generate(test_q, test_ctx, temperature_override=0.1)
    elapsed = _time.time() - t0
    stats = a.generator.get_last_stats()
    return JSONResponse({
        "answer": answer,
        "tokens": stats["tokens"],
        "tps": stats["tps"],
        "elapsed": round(elapsed, 2),
        "model": GGUF_MODEL_PATH.name,
    })


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8080)
