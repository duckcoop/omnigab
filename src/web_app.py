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
        gen = a.gen if hasattr(a, 'gen') else None
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
    return StreamingResponse(
        iter([pdf_bytes]),
        media_type="application/pdf",
        headers={"Content-Disposition": "attachment; filename=job_results.pdf"}
    )


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8080)
