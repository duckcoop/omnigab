"""
Skill sandboxing.
=================

Skills are user-extensible code, so they are run inside a small
sandbox that:

  * Restricts filesystem reads to `data/` and the skill's own
    directory under `skills/` (writes are limited to `data/`).
  * Restricts network access to hosts whose suffix appears in the
    skill manifest's `network_allowlist`. A skill with an empty
    allowlist gets no network at all.
  * Hides environment variables from skill code; `os.environ` is
    swapped for a stub during execute().
  * Wraps every execute() call in a try/except so a failing skill
    cannot bring down the host.

This is in-process sandboxing - not a security boundary against
intentionally malicious native code - but it is enough to keep an
honest skill from accidentally reaching into ~/.ssh or scraping
$OMNIAGENT_API_TOKEN, and to keep a buggy skill from corrupting the rest
of the project.
"""

from __future__ import annotations

import builtins
import contextlib
import io
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import urlparse

from security import audit_log, validate_url, ValidationError
from skill_base import Skill, SkillContext, SkillResult


class SkillSandboxError(RuntimeError):
    """Raised when sandboxed code violates a restriction."""


_REAL_OPEN = builtins.open
_ALLOWED_IMPORT_ROOTS = {
    "__future__",
    "_io",
    "collections",
    "datetime",
    "functools",
    "itertools",
    "json",
    "math",
    "random",
    "re",
    "skill_base",
    "statistics",
    "string",
    "time",
    "typing",
    "urllib",
}

_RUNNER_PATH = Path(__file__).resolve().parent / "skill_subprocess_runner.py"
_SRC_DIR = Path(__file__).resolve().parent
_SUBPROCESS_TIMEOUT_SECONDS = 30
_MAX_PROXY_ROUNDS = 6


def _normalize(path: Any) -> Path:
    return Path(os.fspath(path)).resolve()


def _is_inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _build_allowed_roots(skill: Skill, project_root: Path) -> list[Path]:
    """Resolve absolute paths the skill is allowed to touch."""
    roots: list[Path] = [
        (project_root / "data").resolve(),
        (project_root / "skills" / skill.name).resolve(),
    ]
    data_root = (project_root / "data").resolve()
    for extra in skill.manifest.read_paths:
        candidate = Path(extra)
        if not candidate.is_absolute():
            candidate = project_root / extra
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        if _is_inside(resolved, data_root):
            roots.append(resolved)
    return roots


def _make_open(allowed_roots: list[Path], data_dir: Path):
    """Return a replacement open() that only touches allowlisted paths."""

    def _open(file, mode="r", *args, **kwargs):  # type: ignore[override]
        if isinstance(file, int):
            # Numeric file descriptors are already opened by the host;
            # passing them through does not let the skill discover new files.
            return _REAL_OPEN(file, mode, *args, **kwargs)
        target = _normalize(file)
        writing = any(flag in mode for flag in ("w", "a", "x", "+"))
        if writing:
            # Writes only into data/.
            if not _is_inside(target, data_dir):
                raise SkillSandboxError(
                    "Skill attempted to write outside data/: {}".format(target)
                )
        else:
            if not any(_is_inside(target, root) for root in allowed_roots):
                raise SkillSandboxError(
                    "Skill attempted to read outside its sandbox: {}".format(target)
                )
        return _REAL_OPEN(file, mode, *args, **kwargs)

    return _open


def _ensure_data_write(path: Any, data_dir: Path, action: str) -> None:
    target = _normalize(path)
    if not _is_inside(target, data_dir):
        raise SkillSandboxError(
            "Skill attempted to {} outside data/: {}".format(action, target)
        )


def _make_path_mutator(real_func, data_dir: Path, action: str):
    def _mutate(path, *args, **kwargs):
        _ensure_data_write(path, data_dir, action)
        return real_func(path, *args, **kwargs)

    return _mutate


def _make_rename(real_func, data_dir: Path, action: str):
    def _rename(src, dst, *args, **kwargs):
        _ensure_data_write(src, data_dir, action)
        _ensure_data_write(dst, data_dir, action)
        return real_func(src, dst, *args, **kwargs)

    return _rename


def _make_import(real_import):
    def _import(name, globals=None, locals=None, fromlist=(), level=0):
        root = name.split(".", 1)[0]
        if root not in _ALLOWED_IMPORT_ROOTS:
            raise SkillSandboxError("Skill attempted to import blocked module: {}".format(name))
        return real_import(name, globals, locals, fromlist, level)

    return _import


def _host_allowed(host: str, allowlist: list[str]) -> bool:
    host = host.lower()
    for entry in allowlist:
        entry = entry.lower().strip()
        if not entry:
            continue
        if host == entry or host.endswith("." + entry):
            return True
    return False


def _make_socket_connect(allowlist: list[str]):
    """Wrap socket.create_connection so disallowed hosts cannot be reached."""
    real_create_connection = socket.create_connection

    def _create(address, *args, **kwargs):
        host = address[0] if isinstance(address, tuple) else str(address)
        if not _host_allowed(host, allowlist):
            raise SkillSandboxError(
                "Skill attempted to reach disallowed host: {}".format(host)
            )
        return real_create_connection(address, *args, **kwargs)

    return real_create_connection, _create


class _EmptyEnviron(dict):
    """Stand-in for os.environ that exposes nothing."""

    def __init__(self):
        super().__init__()

    def __setitem__(self, key, value):  # pragma: no cover - skill should not write env
        raise SkillSandboxError("Skill attempted to modify environment variables")


@contextlib.contextmanager
def _sandboxed(skill: Skill, project_root: Path) -> Iterator[None]:
    """Context manager that installs and removes the sandbox patches."""
    allowed_roots = _build_allowed_roots(skill, project_root)
    data_dir = (project_root / "data").resolve()

    real_open = builtins.open
    real_io_open = io.open
    real_path_open = Path.open
    real_import = builtins.__import__
    real_environ = os.environ
    real_getenv = os.getenv
    real_remove = os.remove
    real_unlink = os.unlink
    real_rmdir = os.rmdir
    real_rename = os.rename
    real_replace = os.replace
    real_create_connection = socket.create_connection

    guarded_open = _make_open(allowed_roots, data_dir)
    builtins.open = guarded_open
    io.open = guarded_open
    Path.open = lambda self, *args, **kwargs: guarded_open(self, *args, **kwargs)  # type: ignore[assignment]
    builtins.__import__ = _make_import(real_import)
    os.environ = _EmptyEnviron()  # type: ignore[assignment]
    os.getenv = lambda key, default=None: default  # type: ignore[assignment]
    os.remove = _make_path_mutator(real_remove, data_dir, "remove")  # type: ignore[assignment]
    os.unlink = _make_path_mutator(real_unlink, data_dir, "unlink")  # type: ignore[assignment]
    os.rmdir = _make_path_mutator(real_rmdir, data_dir, "remove directory")  # type: ignore[assignment]
    os.rename = _make_rename(real_rename, data_dir, "rename")  # type: ignore[assignment]
    os.replace = _make_rename(real_replace, data_dir, "replace")  # type: ignore[assignment]
    _, socket.create_connection = _make_socket_connect(skill.manifest.network_allowlist)
    try:
        yield
    finally:
        builtins.open = real_open
        io.open = real_io_open
        Path.open = real_path_open  # type: ignore[assignment]
        builtins.__import__ = real_import
        os.environ = real_environ  # type: ignore[assignment]
        os.getenv = real_getenv  # type: ignore[assignment]
        os.remove = real_remove  # type: ignore[assignment]
        os.unlink = real_unlink  # type: ignore[assignment]
        os.rmdir = real_rmdir  # type: ignore[assignment]
        os.rename = real_rename  # type: ignore[assignment]
        os.replace = real_replace  # type: ignore[assignment]
        socket.create_connection = real_create_connection


def run_skill(
    skill: Skill,
    ctx: SkillContext,
    *,
    project_root: Path,
) -> SkillResult:
    """Run skill.execute(ctx) in an isolated child Python process.

    Skill Python is never imported into the main agent process. The
    child process receives only JSON-serializable context and can request
    host services (LLM generation, web search) through explicit JSON
    messages.
    """
    started = time.monotonic()
    llm_responses: list[str] = []
    web_search_responses: list[list[dict[str, Any]]] = []
    payload = {
        "query": ctx.query,
        "retrieved_chunks": ctx.retrieved_chunks,
        "user_memory": ctx.user_memory,
        "network_allowlist": skill.manifest.network_allowlist,
        "read_paths": skill.manifest.read_paths,
        "llm_responses": llm_responses,
        "web_search_responses": web_search_responses,
    }

    try:
        for _ in range(_MAX_PROXY_ROUNDS):
            payload["llm_responses"] = llm_responses
            payload["web_search_responses"] = web_search_responses
            message = _run_child(skill, payload, project_root)

            msg_type = message.get("type")
            if msg_type == "result":
                result = _result_from_payload(message.get("result", {}), skill.name)
                break
            if msg_type == "llm_request":
                if ctx.generator is None:
                    raise RuntimeError("Skill requested LLM generation but no generator is loaded")
                req = message.get("request", {})
                llm_responses.append(ctx.generator.generate(
                    str(req.get("question", "")),
                    str(req.get("context", "")),
                    temperature_override=req.get("temperature_override"),
                    user_context=str(req.get("user_context", "")),
                    history=str(req.get("history", "")),
                ))
                continue
            if msg_type == "web_search_request":
                if not skill.manifest.network_allowlist or ctx.web_search is None:
                    raise SkillSandboxError("Skill requested network access without an allowlist")
                req = message.get("request", {})
                web_search_responses.append(_serialize_web_results(
                    ctx.web_search.search(
                        str(req.get("query", "")),
                        max_results=req.get("max_results"),
                    )
                ))
                continue
            if msg_type == "sandbox_violation":
                raise SkillSandboxError(str(message.get("error", "sandbox violation")))
            if msg_type == "error":
                raise RuntimeError("{}: {}".format(
                    message.get("error_type", "SkillError"),
                    message.get("error", "unknown error"),
                ))
            raise RuntimeError("Unexpected skill runner response: {}".format(msg_type))
        else:
            raise RuntimeError("Skill exceeded proxy request limit")
    except SkillSandboxError as exc:
        audit_log(
            "skill.invoke",
            status="sandbox_violation",
            input_summary=ctx.query,
            detail={"skill": skill.name, "error": str(exc)},
        )
        raise
    except Exception as exc:  # noqa: BLE001
        audit_log(
            "skill.invoke",
            status="error",
            input_summary=ctx.query,
            detail={
                "skill": skill.name,
                "error_type": exc.__class__.__name__,
                "error": str(exc),
            },
        )
        raise

    elapsed_ms = int((time.monotonic() - started) * 1000)
    result.used_skill = skill.name
    audit_log(
        "skill.invoke",
        status="ok",
        input_summary=ctx.query,
        detail={"skill": skill.name, "elapsed_ms": elapsed_ms},
    )
    return result


def _run_child(skill: Skill, payload: dict[str, Any], project_root: Path) -> dict[str, Any]:
    skill_dir = (project_root / "skills" / skill.name).resolve()
    cmd = [
        sys.executable,
        "-I",
        "-B",
        str(_RUNNER_PATH),
        str(_SRC_DIR),
        str(project_root.resolve()),
        str(skill_dir),
    ]
    env = {
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUTF8": "1",
        "NO_PROXY": "*",
    }
    completed = subprocess.run(
        cmd,
        input=json.dumps(payload, ensure_ascii=False),
        text=True,
        capture_output=True,
        cwd=str(skill_dir),
        env=env,
        timeout=_SUBPROCESS_TIMEOUT_SECONDS,
        check=False,
    )
    if completed.returncode != 0 and not completed.stdout.strip():
        raise RuntimeError("Skill runner exited {}: {}".format(
            completed.returncode,
            completed.stderr.strip()[:500],
        ))
    try:
        return json.loads(completed.stdout.strip() or "{}")
    except json.JSONDecodeError as exc:
        raise RuntimeError("Skill runner emitted invalid JSON: {}".format(exc)) from exc


def _result_from_payload(raw: Any, skill_name: str) -> SkillResult:
    if isinstance(raw, str):
        return SkillResult(answer=raw, used_skill=skill_name)
    if not isinstance(raw, dict):
        return SkillResult(answer=str(raw), used_skill=skill_name)
    return SkillResult(
        answer=str(raw.get("answer", "")),
        sources=list(raw.get("sources", [])),
        citations=list(raw.get("citations", [])),
        metadata=dict(raw.get("metadata", {})),
        used_skill=skill_name,
        used_fallback=bool(raw.get("used_fallback", False)),
    )


def _serialize_web_results(results: list[tuple[Any, float]]) -> list[dict[str, Any]]:
    rows = []
    for chunk, score in results:
        rows.append({
            "text": getattr(chunk, "text", ""),
            "source_file": getattr(chunk, "source_file", "web"),
            "chunk_index": getattr(chunk, "chunk_index", len(rows)),
            "score": float(score),
        })
    return rows


def validate_skill_url(url: str, allowlist: list[str]) -> str:
    """Validate URL scheme/host for use inside a skill."""
    canonical = validate_url(url)
    host = urlparse(canonical).netloc.split(":")[0]
    if not _host_allowed(host, allowlist):
        raise ValidationError("Host '{}' is not in this skill's allowlist".format(host))
    return canonical
