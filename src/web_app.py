"""Web UI / API for OmniAgent.

Rewired around the new architecture:

  * `ModelManager` owns the live llama-cpp model. Hot-swappable.
  * `Agent` runs a tool-calling loop over a unified tool catalog (RAG,
    web search, memory, plus every enabled skill as a tool).
  * Async SSE streaming on /api/query/stream so the UI never freezes.
  * Model download endpoint that requires a UI-side confirmation step.
"""

from __future__ import annotations

import asyncio
import json
import uuid
import ipaddress
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from starlette.middleware.base import BaseHTTPMiddleware
import uvicorn

from config import (
    DOCS_DIR, EMBEDDING_MODEL, EMBEDDING_DIMENSION,
    FAITHFULNESS_THRESHOLD, WEB_SEARCH_ENABLED, WEB_SEARCH_MAX_RESULTS,
    AVAILABLE_MODELS, MODELS_DIR,
    CONTEXT_WINDOW, N_THREADS, MAX_NEW_TOKENS, TEMPERATURE, TOP_P,
    SUPPORTED_EXTENSIONS,
    _load_selected_model,
)
from core.agent import Agent
from core.model_manager import (
    ModelManager, cuda_supported,
    select_optimal_model, ensure_model_downloaded,
)
from embeddings import EmbeddingEngine
from ingest import load_documents, chunk_documents
from persistent_memory import get_persistent_memory
from security import (
    audit_log,
    check_bearer_token,
    get_or_create_api_token,
    read_audit_log,
    sanitize_filename,
    validate_text_input,
    validate_query,
    ValidationError,
)
from skill_memory import SkillMemory
from skill_registry import get_registry
from tools import build_default_toolset
from user_memory import UserMemory
from vectorstore import VectorStore
from web_search import WebSearchEngine


app = FastAPI(title="OmniAgent")

# Globals built at startup.
mm: ModelManager | None = None
agent: Agent | None = None
embedder: EmbeddingEngine | None = None
store: VectorStore | None = None
web_search: WebSearchEngine | None = None
memory: UserMemory | None = None
persistent_memory = None  # PersistentMemory; built at startup
skill_memory = SkillMemory()

# Loopback addresses allowed to reach the API.
_LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost"}


def _is_loopback_host(host: str | None) -> bool:
    if not host:
        return False
    if host in _LOOPBACK_HOSTS:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


API_TOKEN = get_or_create_api_token()

_WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
_TOKEN_EXEMPT_PATHS = {
    "/",
    "/jobs",
    "/api/session",
    "/api/query",
    "/api/query/stream",
}


def _extract_bearer(request: Request) -> str:
    auth = request.headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return request.headers.get("X-API-Token", "").strip()


class LocalhostOnlyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        client = request.client
        host = client.host if client else None
        if not _is_loopback_host(host):
            audit_log("http.blocked", status="forbidden",
                      input_summary=request.url.path,
                      detail={"peer": host or "(none)"})
            return JSONResponse({"error": "Forbidden"}, status_code=403)
        return await call_next(request)


class WriteTokenMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.method in _WRITE_METHODS and request.url.path not in _TOKEN_EXEMPT_PATHS:
            supplied = _extract_bearer(request)
            if not check_bearer_token(supplied):
                audit_log("http.unauthorized", status="denied",
                          input_summary=request.url.path,
                          detail={"method": request.method})
                return JSONResponse({"error": "Unauthorized"}, status_code=401)
        return await call_next(request)


app.add_middleware(WriteTokenMiddleware)
app.add_middleware(LocalhostOnlyMiddleware)

sessions: dict[str, list[dict]] = {}
MAX_SESSIONS = 50


def _get_session_history(session_id: str) -> list[dict]:
    if session_id not in sessions:
        if len(sessions) >= MAX_SESSIONS:
            oldest = next(iter(sessions))
            del sessions[oldest]
        sessions[session_id] = []
    return sessions[session_id]


def _rebuild_toolset() -> None:
    """Re-discover skills and rebuild the agent's tool catalog."""
    if agent is None:
        return
    reg = get_registry()
    reg.reload()
    tools = build_default_toolset(
        embedder=embedder,
        store=store,
        web_search=web_search,
        memory=memory,
        generator_getter=lambda: mm.generator if mm else None,
        skill_registry=reg,
        persistent_memory=persistent_memory,
    )
    agent.tools = tools


@app.on_event("startup")
def startup():
    """Initialize models, embedder, vectorstore, agent, and tools once."""
    global mm, agent, embedder, store, web_search, memory, persistent_memory

    print("Loading OmniAgent...")

    embedder = EmbeddingEngine()
    store = VectorStore()
    try:
        store.load()
    except Exception:
        pass

    if WEB_SEARCH_ENABLED:
        try:
            ws = WebSearchEngine(max_results=WEB_SEARCH_MAX_RESULTS)
            if ws.is_available():
                web_search = ws
                print("Web search: enabled (DuckDuckGo)")
        except Exception as exc:
            print(f"Web search disabled: {exc}")

    memory = UserMemory()
    persistent_memory = get_persistent_memory()
    print(f"Persistent memory: {len(persistent_memory.all_rows())} facts on file.")

    # --- Hardware autotuning ---
    # Honour a saved selection if the user has explicitly switched models
    # before, otherwise pick the best fit for this machine and auto-download
    # it on first run. This is the "anyone can clone and run" path.
    saved = _load_selected_model()
    target_path = MODELS_DIR / saved
    if target_path.exists():
        initial_model = saved
        print(f"Using saved model: {saved}")
    else:
        chosen, why = select_optimal_model()
        ram_gb = why["ram_gb"]
        vram_gb = why["vram_gb"]
        print(f"Hardware: RAM={ram_gb} GB, VRAM={vram_gb} GB, CUDA={cuda_supported()}")
        print(f"Auto-selecting model: {chosen}")
        if not ensure_model_downloaded(chosen):
            print(f"Could not download {chosen}; falling back to whatever is on disk.")
            on_disk = [f for f in AVAILABLE_MODELS if (MODELS_DIR / f).exists()]
            if not on_disk:
                raise RuntimeError("No GGUF models available and download failed.")
            chosen = on_disk[0]
        initial_model = chosen

    mm = ModelManager(initial_model=initial_model)
    gpu_note = "GPU offload active" if mm.gpu_supported and mm.gpu_layers != 0 else "CPU-only"
    print(f"Model manager ready ({gpu_note}, llama-cpp CUDA support: {cuda_supported()}).")

    reg = get_registry()
    reg.discover()
    tools = build_default_toolset(
        embedder=embedder,
        store=store,
        web_search=web_search,
        memory=memory,
        generator_getter=lambda: mm.generator if mm else None,
        skill_registry=reg,
        persistent_memory=persistent_memory,
    )
    agent = Agent(model_manager=mm, tools=tools, memory=memory,
                  persistent_memory=persistent_memory)
    print(f"Agent ready with {len(tools)} tools: {', '.join(sorted(tools.keys()))}")
    print("Ready! Open http://localhost:8080")


# -------------------------------------------------------------------- UI
@app.get("/", response_class=HTMLResponse)
def serve_ui():
    html_path = Path(__file__).parent / "static" / "index.html"
    if not html_path.exists():
        return HTMLResponse("<h1>index.html not found</h1>", status_code=404)
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
    return JSONResponse({"session_id": sid, "api_token": API_TOKEN})


# ---------------------------------------------------------------- query
@app.post("/api/query")
async def api_query(request: Request):
    body = await request.json()
    raw_question = body.get("question", "")
    session_id = body.get("session_id", "default")
    try:
        question = validate_query(raw_question)
    except ValidationError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)

    if agent is None:
        return JSONResponse({"error": "Agent not ready"}, status_code=503)

    history = _get_session_history(session_id)
    agent.history = list(history)
    turn = await asyncio.to_thread(agent.run, question)
    sessions[session_id] = list(agent.history)

    return JSONResponse({
        "answer": turn.answer,
        "tool_calls": [{"name": c.name, "arguments": c.arguments} for c in turn.tool_calls],
        "tokens": turn.tokens,
        "tps": turn.tps,
        "elapsed": turn.elapsed,
        "model": turn.model,
    })


@app.post("/api/query/stream")
async def api_query_stream(request: Request):
    body = await request.json()
    raw_question = body.get("question", "")
    session_id = body.get("session_id", "default")

    if agent is None:
        return JSONResponse({"error": "Agent not ready"}, status_code=503)

    history = _get_session_history(session_id)
    agent.history = list(history)

    async def event_stream():
        try:
            async for chunk in agent.stream(raw_question):
                yield "data: " + json.dumps(chunk) + "\n\n"
        except Exception as exc:
            yield "data: " + json.dumps({"type": "error", "message": str(exc)}) + "\n\n"
        sessions[session_id] = list(agent.history)
        yield "data: [DONE]\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


# ---------------------------------------------------------- ingest, etc.
@app.post("/api/ingest")
async def api_ingest():
    if embedder is None or store is None:
        return JSONResponse({"error": "Not ready"}, status_code=503)

    def _do_ingest():
        documents = load_documents(DOCS_DIR)
        if not documents:
            return None
        chunks = chunk_documents(documents)
        if not chunks:
            return None
        texts = [c.text for c in chunks]
        vectors = embedder.embed_texts(texts)
        store.__init__()  # reset
        store.add(vectors, chunks)
        store.save()
        return store.size

    size = await asyncio.to_thread(_do_ingest)
    if size is None:
        audit_log("ingest.api", status="empty")
        return JSONResponse({"status": "error", "message": "No documents found"}, status_code=400)
    audit_log("ingest.api", status="ok", detail={"vectors": size})
    return JSONResponse({"status": "ok", "vectors": size})


def _tool_calling_capability(model_filename: str) -> dict:
    """Heuristic: which Qwen sizes can reliably emit our <tool_call> syntax.

    Returns a dict with `tier` ('good' | 'marginal' | 'poor') and a short
    human-readable note for the UI to surface in the topbar.
    """
    name = (model_filename or "").lower()
    if "14b" in name:
        return {"tier": "good", "note": "tool calling: reliable"}
    if "7b" in name:
        return {"tier": "good", "note": "tool calling: reliable"}
    if "3b" in name:
        return {"tier": "marginal",
                "note": "tool calling: hit-and-miss — upgrade to 7B+ for jobs/search"}
    return {"tier": "poor",
            "note": "tool calling: unreliable on this model — switch to 7B or 14B"}


@app.get("/api/status")
def api_status():
    model_name = mm.current_model_name if mm else ""
    return JSONResponse({
        "embedding": EMBEDDING_MODEL,
        "generator": "GGUF/llama-cpp",
        "index_size": store.size if store else 0,
        "web_search": web_search is not None,
        "active_sessions": len(sessions),
        "model": model_name or None,
        "gpu_supported": mm.gpu_supported if mm else False,
        "gpu_layers": mm.gpu_layers if mm else 0,
        "tool_calling": _tool_calling_capability(model_name),
    })


# ---------------------------------------------------------------- skills
@app.get("/api/skills")
def api_skills():
    reg = get_registry()
    reg.reload()
    feedback = skill_memory.all_stats()
    out = []
    for manifest in reg.manifests(include_disabled=True):
        d = manifest.to_dict()
        d["feedback"] = feedback.get(manifest.name, skill_memory.stats_for(manifest.name))
        out.append(d)
    return JSONResponse({"skills": out})


@app.post("/api/skills/{skill_name}/enable")
async def api_skill_enable(skill_name: str, request: Request):
    body = await request.json()
    enabled = bool(body.get("enabled", True))
    reg = get_registry()
    if not reg.set_enabled(skill_name, enabled):
        return JSONResponse({"error": "Unknown skill"}, status_code=404)
    _rebuild_toolset()
    audit_log("skill.state", status="ok", input_summary=skill_name,
              detail={"enabled": enabled})
    return JSONResponse({"status": "ok", "skill": skill_name, "enabled": enabled})


@app.post("/api/skills")
async def api_skill_create(request: Request):
    body = await request.json()
    try:
        name = validate_text_input(body.get("name", ""), field="Skill name", max_chars=80)
        description = validate_text_input(body.get("description", ""), field="Skill description", max_chars=1000)
        system_prompt = validate_text_input(body.get("system_prompt", ""), field="System prompt", max_chars=4000)
        triggers = [
            validate_text_input(str(t), field="Trigger", max_chars=120)
            for t in body.get("triggers", []) if str(t).strip()
        ]
        function_body = validate_text_input(
            body.get("function_body", ""), field="Function body",
            max_chars=8000, allow_empty=True,
        )
        network_allowlist = [
            validate_text_input(str(host), field="Network host", max_chars=253)
            for host in body.get("network_allowlist", []) if str(host).strip()
        ]
    except ValidationError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)

    try:
        skill = get_registry().create_skill_from_spec(
            name=name, description=description,
            system_prompt=system_prompt, triggers=triggers,
            function_body=function_body or None,
            network_allowlist=network_allowlist,
        )
    except FileExistsError as exc:
        return JSONResponse({"error": str(exc)}, status_code=409)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)

    _rebuild_toolset()
    audit_log("skill.create", status="ok", input_summary=name,
              detail={"skill": skill.name})
    return JSONResponse({"status": "ok", "skill": skill.manifest.to_dict()})


@app.post("/api/skills/feedback")
async def api_skill_feedback(request: Request):
    body = await request.json()
    try:
        skill_name = validate_text_input(body.get("skill_name", ""), field="Skill name", max_chars=120)
        query = validate_text_input(body.get("query", ""), field="Query", max_chars=4000)
        notes = validate_text_input(body.get("notes", ""), field="Notes", max_chars=1000, allow_empty=True)
        row_id = skill_memory.record_feedback(skill_name, query, body.get("feedback"), notes=notes)
    except (ValidationError, ValueError) as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    audit_log("skill.feedback", status="ok", input_summary=query,
              detail={"skill": skill_name, "row_id": row_id})
    return JSONResponse({"status": "ok", "id": row_id, "stats": skill_memory.stats_for(skill_name)})


# ---------------------------------------------------------------- memory
@app.get("/api/memory")
def api_memory():
    return JSONResponse(memory.get_all() if memory else {})


@app.post("/api/memory")
async def api_memory_update(request: Request):
    body = await request.json()
    if memory is None:
        return JSONResponse({"error": "Memory not ready"}, status_code=503)
    action = body.get("action", "")

    if action == "set":
        try:
            key = validate_text_input(body.get("key", ""), field="Memory key", max_chars=80)
            value = validate_text_input(body.get("value", ""), field="Memory value", max_chars=1000)
        except ValidationError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        if key in ("location", "units", "language"):
            memory.set(key, value)
        else:
            memory.learn_fact(key, value)
        return JSONResponse({"status": "ok", "memory": memory.get_all()})

    if action == "remember":
        try:
            instruction = validate_text_input(body.get("instruction", ""), field="Instruction", max_chars=1000)
        except ValidationError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        memory.add_instruction(instruction)
        return JSONResponse({"status": "ok", "memory": memory.get_all()})

    if action == "forget":
        try:
            instruction = validate_text_input(body.get("instruction", ""), field="Instruction", max_chars=1000)
        except ValidationError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        memory.remove_instruction(instruction)
        memory.forget_fact(instruction)
        return JSONResponse({"status": "ok", "memory": memory.get_all()})

    if action == "clear":
        memory.clear()
        return JSONResponse({"status": "ok", "memory": memory.get_all()})

    return JSONResponse({"error": "Unknown action"}, status_code=400)


@app.post("/api/clear_history")
async def api_clear_history(request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    session_id = body.get("session_id", "default")
    if session_id in sessions:
        sessions[session_id] = []
    if agent is not None:
        agent.clear_history()
    return JSONResponse({"status": "ok"})


# ---------------------------------------------------------------- models
@app.get("/api/models")
def api_models():
    out = []
    for filename, info in AVAILABLE_MODELS.items():
        path = MODELS_DIR / filename
        out.append({
            "filename": filename,
            "name": info["name"],
            "size": info["size"],
            "ram": info["ram"],
            "repo": info["repo"],
            "downloaded": path.exists(),
            "active": filename == (mm.current_model_name if mm else ""),
        })
    return JSONResponse({
        "models": out,
        "status": mm.status() if mm else {},
    })


@app.post("/api/models/switch")
async def api_model_switch(request: Request):
    body = await request.json()
    filename = (body.get("filename") or "").strip()
    if mm is None:
        return JSONResponse({"error": "ModelManager not ready"}, status_code=503)
    try:
        status = await asyncio.to_thread(mm.load, filename)
    except FileNotFoundError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    except Exception as exc:
        audit_log("model.switch", status="error", input_summary=filename,
                  detail={"error": str(exc)})
        return JSONResponse({"error": f"Load failed: {exc}"}, status_code=500)
    audit_log("model.switch", status="ok", input_summary=filename,
              detail={"name": AVAILABLE_MODELS[filename]["name"]})
    return JSONResponse({"status": "ok", "model": filename, "info": status})


@app.post("/api/models/unload")
async def api_model_unload():
    if mm is None:
        return JSONResponse({"error": "Not ready"}, status_code=503)
    await asyncio.to_thread(mm.unload)
    return JSONResponse({"status": "ok"})


@app.post("/api/models/download")
async def api_model_download(request: Request):
    """Two-phase download: first call (no `confirmed`) returns 409 with
    size info so the UI can show a confirmation modal; second call
    (`confirmed: true`) streams progress over SSE.
    """
    body = await request.json()
    filename = (body.get("filename") or "").strip()
    confirmed = bool(body.get("confirmed", False))

    if filename not in AVAILABLE_MODELS:
        return JSONResponse({"error": "Unknown model"}, status_code=400)
    info = AVAILABLE_MODELS[filename]

    if (MODELS_DIR / filename).exists():
        return JSONResponse({"status": "already_downloaded", "filename": filename})

    if not confirmed:
        return JSONResponse({
            "needs_confirmation": True,
            "filename": filename,
            "name": info["name"],
            "size": info["size"],
            "ram": info["ram"],
            "repo": info["repo"],
        }, status_code=409)

    async def stream():
        yield "data: " + json.dumps({
            "type": "start", "filename": filename, "name": info["name"],
            "size": info["size"], "repo": info["repo"],
        }) + "\n\n"
        try:
            from huggingface_hub import hf_hub_download
            MODELS_DIR.mkdir(parents=True, exist_ok=True)
            local_path = await asyncio.to_thread(
                hf_hub_download,
                repo_id=info["repo"],
                filename=filename,
                local_dir=str(MODELS_DIR),
            )
            audit_log("model.download", status="ok", input_summary=filename,
                      detail={"repo": info["repo"]})
            yield "data: " + json.dumps({"type": "done", "path": local_path}) + "\n\n"
        except Exception as exc:
            audit_log("model.download", status="error", input_summary=filename,
                      detail={"error": str(exc)})
            yield "data: " + json.dumps({"type": "error", "message": str(exc)}) + "\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")


# ---------------------------------------------------------------- docs
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


@app.post("/api/docs/upload")
async def api_docs_upload(request: Request):
    body = await request.json()
    try:
        filename = sanitize_filename(body.get("filename", ""), default="upload.txt")
        content = validate_text_input(body.get("content", ""), field="Document content", max_chars=2_000_000)
    except ValidationError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)

    suffix = Path(filename).suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        return JSONResponse({"error": "Unsupported file extension"}, status_code=400)

    target = (DOCS_DIR / filename).resolve()
    docs_root = DOCS_DIR.resolve()
    try:
        if not target.is_relative_to(docs_root):
            return JSONResponse({"error": "Invalid filename"}, status_code=400)
    except OSError:
        return JSONResponse({"error": "Invalid filename"}, status_code=400)

    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    if target.exists():
        stem = target.stem[:150]
        suffix = target.suffix
        target = DOCS_DIR / f"{stem}-{uuid.uuid4().hex[:8]}.{suffix.lstrip('.')}"
    target.write_text(content, encoding="utf-8")
    audit_log("docs.upload", status="ok", input_summary=filename,
              detail={"bytes": len(content)})
    return JSONResponse({"status": "ok", "filename": target.name, "bytes": len(content)})


# ---------------------------------------------------------------- system
@app.get("/api/system")
def api_system_info():
    import platform
    current_model = mm.current_model_name if mm and mm.current_model_name else "not loaded"
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
        "use_gguf": True,
        "gpu_supported": mm.gpu_supported if mm else False,
        "gpu_layers": mm.gpu_layers if mm else 0,
        "index_size": store.size if store else 0,
        "web_search": web_search is not None,
        "faithfulness_threshold": FAITHFULNESS_THRESHOLD,
        "docs_dir": str(DOCS_DIR),
        "models_dir": str(MODELS_DIR),
    })


@app.get("/api/audit")
def api_audit(limit: int = 200):
    limit = max(1, min(1000, int(limit)))
    return JSONResponse({"events": read_audit_log(limit=limit)})


# ---------------------------------------------------------------- resume
# A single "active resume" lives at data/docs/active_resume.<ext>. The
# IndeedApplyTool picks it up automatically because its loader globs
# `data/docs/*resume*`. Putting it under data/docs/ also means it gets
# indexed by RAG so the agent can answer questions about it.

import base64

_RESUME_EXTS = {".pdf", ".docx", ".txt", ".md"}


def _find_active_resume() -> Path | None:
    docs_dir = DOCS_DIR
    if not docs_dir.exists():
        return None
    for path in sorted(docs_dir.glob("active_resume.*")):
        if path.suffix.lower() in _RESUME_EXTS:
            return path
    return None


@app.get("/api/resume")
def api_resume_status():
    path = _find_active_resume()
    if path is None:
        return JSONResponse({"active": False})
    return JSONResponse({
        "active": True,
        "filename": path.name,
        "size": path.stat().st_size,
        "mtime": int(path.stat().st_mtime),
    })


@app.post("/api/resume/upload")
async def api_resume_upload(request: Request):
    """Accept a resume as base64 JSON so the existing JSON-only client
    plumbing works without multipart.
    Body: {"filename": "cooper.pdf", "content_b64": "<base64 bytes>"}
    """
    body = await request.json()
    raw_filename = (body.get("filename") or "").strip()
    content_b64 = body.get("content_b64") or ""
    if not raw_filename or not content_b64:
        return JSONResponse({"error": "filename and content_b64 required"}, status_code=400)

    suffix = Path(raw_filename).suffix.lower()
    if suffix not in _RESUME_EXTS:
        return JSONResponse({"error": f"Unsupported extension: {suffix}. Use PDF, DOCX, TXT, or MD."},
                            status_code=400)

    try:
        data = base64.b64decode(content_b64)
    except Exception:
        return JSONResponse({"error": "content_b64 is not valid base64"}, status_code=400)
    if not data:
        return JSONResponse({"error": "empty file"}, status_code=400)
    if len(data) > 5 * 1024 * 1024:
        return JSONResponse({"error": "resume too large (5 MB max)"}, status_code=400)

    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    # Remove any previous active resume so swapping formats works cleanly.
    for old in DOCS_DIR.glob("active_resume.*"):
        try:
            old.unlink()
        except OSError:
            pass

    target = DOCS_DIR / f"active_resume{suffix}"
    target.write_bytes(data)
    audit_log("resume.upload", status="ok", input_summary=raw_filename,
              detail={"bytes": len(data), "ext": suffix})
    return JSONResponse({
        "status": "ok",
        "filename": target.name,
        "original_filename": raw_filename,
        "size": len(data),
    })


@app.delete("/api/resume")
async def api_resume_clear():
    removed = []
    for old in DOCS_DIR.glob("active_resume.*"):
        try:
            old.unlink()
            removed.append(old.name)
        except OSError:
            pass
    audit_log("resume.clear", status="ok", detail={"removed": removed})
    return JSONResponse({"status": "ok", "removed": removed})


@app.get("/api/benchmark")
async def api_benchmark(request: Request):
    if mm is None or mm.generator is None:
        return JSONResponse({"error": "No model loaded"}, status_code=503)
    import time as _time
    t0 = _time.time()
    answer = await asyncio.to_thread(
        mm.generator.generate,
        "What is 2+2? Answer in one word.",
        "Basic math: 2+2=4, 3+3=6.",
        0.1,
    )
    elapsed = _time.time() - t0
    stats = mm.generator.get_last_stats()
    return JSONResponse({
        "answer": answer,
        "tokens": stats["tokens"],
        "tps": stats["tps"],
        "elapsed": round(elapsed, 2),
        "model": mm.current_model_name,
    })


# -------------------------------------------------------- job agent
job_agent_instance = None
uploaded_resume_text = ""


def get_job_agent():
    global job_agent_instance
    if job_agent_instance is None:
        from job_agent import JobAgent
        gen = mm.generator if mm else None
        job_agent_instance = JobAgent(generator=gen)
    return job_agent_instance


@app.post("/api/jobs/upload-resume")
async def api_upload_resume(request: Request):
    global uploaded_resume_text
    body = await request.json()
    try:
        text = validate_text_input(body.get("text", ""), field="Resume text", max_chars=200000)
    except ValidationError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    uploaded_resume_text = text
    ja = get_job_agent()
    ja.set_resume_text(text)
    return JSONResponse({"status": "ok", "length": len(text)})


@app.post("/api/jobs/search")
async def api_job_search(request: Request):
    body = await request.json()
    try:
        job_title = validate_text_input(body.get("title", ""), field="Job title", max_chars=200)
        location = validate_text_input(body.get("location", ""), field="Location", max_chars=200, allow_empty=True)
    except ValidationError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    num_results = body.get("num_results", 10)
    try:
        num_results = max(1, min(25, int(num_results)))
    except (TypeError, ValueError):
        return JSONResponse({"error": "num_results must be an integer"}, status_code=400)

    ja = get_job_agent()
    if not ja.resume_text:
        if uploaded_resume_text:
            ja.set_resume_text(uploaded_resume_text)
        else:
            loaded = ja.load_resume()
            if not loaded:
                return JSONResponse({"error": "No resume uploaded"}, status_code=400)

    jobs = await asyncio.to_thread(ja.search_and_score, job_title, location, num_results)
    return JSONResponse({
        "status": "ok",
        "count": len(jobs),
        "jobs": ja.to_dict_list(n=len(jobs)),
    })


@app.get("/api/jobs/pdf")
def api_job_pdf():
    ja = get_job_agent()
    if not ja.jobs:
        return JSONResponse({"error": "No job results yet."}, status_code=400)
    from job_report import generate_job_report
    output_path = Path(__file__).parent.parent / "job_results.pdf"
    generate_job_report(ja.get_top_jobs(5), output_path=output_path)
    pdf_bytes = output_path.read_bytes()
    from fastapi.responses import Response
    return Response(content=pdf_bytes, media_type="application/pdf",
                    headers={"Content-Disposition": "attachment; filename=job_results.pdf"})


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8080)
