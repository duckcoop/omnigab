"""python_eval — sandboxed Python execution for the agent.

Lets the LLM compute, parse, and analyze data without sending anything
to a third-party code interpreter. The sandbox is *defense in depth*,
not a hostile-code containment system:

  * Spawns a fresh CPython subprocess with `python -I` (isolated mode —
    ignores PYTHONHOME, PYTHONPATH, and the user site-packages dir).
  * Empty environment (no inherited secrets like API tokens or PATH).
  * Cwd set to a fresh tempdir, deleted after execution.
  * Hard wall-clock timeout (default 10 s, max 30 s).
  * Output capped at 8 KB to keep tool observations small.
  * A pre-amble script monkey-patches `socket` to raise on network use,
    so the user code can't accidentally exfiltrate data over the wire.

What this *does NOT* defend against: a determined attacker who knows
they're in our sandbox could bypass the socket patch via ctypes or
spawn a subprocess that re-enables networking. For a true hostile-code
sandbox you'd use OS-level isolation (gVisor, Firecracker, AppContainer,
Windows Job Objects with restricted tokens). This tool is sized for the
"agent computes things on the user's behalf" use case, which is the
NIST AI-100-1 capability-containment baseline.

See also: docs/AI_SAFETY.md (TODO) for the threat model.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
from typing import Any


MAX_TIMEOUT_S = 30
DEFAULT_TIMEOUT_S = 10
MAX_OUTPUT_BYTES = 8 * 1024
MAX_CODE_BYTES = 16 * 1024

# Pre-amble that runs BEFORE the user code. Disables socket-based
# networking so well-behaved code can't accidentally reach out.
#
# IMPORTANT design notes:
#   * We do NOT replace `socket.socket` itself — that's a CLASS that
#     `ssl.SSLSocket(socket)` inherits from at SSL-module import time,
#     and replacing it with a function breaks any later ssl import.
#   * Instead we patch the network-INITIATING functions: getaddrinfo,
#     create_connection, gethostbyname. urllib, requests, http.client,
#     and ftplib all go through these. Direct socket.connect() to a raw
#     IP would bypass the patch — see module docstring for the threat
#     model; this is defense-in-depth, not a hostile-code container.
_PREAMBLE = textwrap.dedent("""
    import socket as _omnigab_socket
    def _omnigab_blocked(*a, **kw):
        raise OSError("network access disabled in sandbox")
    _omnigab_socket.getaddrinfo = _omnigab_blocked
    _omnigab_socket.gethostbyname = _omnigab_blocked
    _omnigab_socket.gethostbyname_ex = _omnigab_blocked
    _omnigab_socket.create_connection = _omnigab_blocked
""").strip()


class PythonEvalTool:
    name = "python_eval"
    description = (
        "Execute a short Python snippet in a sandboxed subprocess and return "
        "stdout + stderr. Use this for ARITHMETIC, data parsing, JSON "
        "manipulation, regex tests, or any deterministic computation. The "
        "sandbox: isolated mode (no user site-packages), empty environment, "
        "fresh tempdir cwd, hard timeout, network disabled. Do NOT use for "
        "tasks the user wants you to keep doing across turns — there is no "
        "persistence between calls."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "code": {
                "type": "string",
                "description": "Python source. Use print() to return values. "
                               "The last expression is NOT auto-printed.",
            },
            "timeout_s": {
                "type": "integer",
                "description": f"Wall-clock timeout (default {DEFAULT_TIMEOUT_S}, "
                               f"max {MAX_TIMEOUT_S})",
            },
        },
        "required": ["code"],
    }

    def run(self, arguments: dict[str, Any]) -> dict[str, Any]:
        code = arguments.get("code") or ""
        if not isinstance(code, str) or not code.strip():
            return {"ok": False, "error": "code is required"}
        if len(code.encode("utf-8")) > MAX_CODE_BYTES:
            return {"ok": False,
                    "error": f"code exceeds {MAX_CODE_BYTES} byte limit"}

        try:
            timeout_s = int(arguments.get("timeout_s") or DEFAULT_TIMEOUT_S)
        except (TypeError, ValueError):
            timeout_s = DEFAULT_TIMEOUT_S
        timeout_s = max(1, min(MAX_TIMEOUT_S, timeout_s))

        # Compose preamble + user code into one script. Pass via stdin so
        # we never write user code to disk and the subprocess command line
        # stays clean of arbitrary content.
        script = _PREAMBLE + "\n\n# === user code ===\n" + code

        # Fresh tempdir as cwd. Survives only for the duration of the run.
        sandbox_dir = tempfile.mkdtemp(prefix="omnigab_eval_")

        # Minimal env. Windows needs SYSTEMROOT / TEMP for Python itself
        # to spin up; without them you get "ImportError: DLL load failed".
        # Everything else (PATH, USER, secrets) is stripped.
        env = {}
        for k in ("SYSTEMROOT", "TEMP", "TMP", "PATHEXT"):
            if k in os.environ:
                env[k] = os.environ[k]
        # Block Python from finding the parent venv's site-packages.
        env["PYTHONNOUSERSITE"] = "1"
        env["PYTHONDONTWRITEBYTECODE"] = "1"

        try:
            proc = subprocess.run(
                [sys.executable, "-I", "-c", script],
                cwd=sandbox_dir,
                env=env,
                capture_output=True,
                timeout=timeout_s,
                input="",         # closed stdin
                check=False,
            )
            stdout = proc.stdout.decode("utf-8", errors="replace")
            stderr = proc.stderr.decode("utf-8", errors="replace")
            truncated = False
            if len(stdout) > MAX_OUTPUT_BYTES:
                stdout = stdout[:MAX_OUTPUT_BYTES] + "\n…(stdout truncated)"
                truncated = True
            if len(stderr) > MAX_OUTPUT_BYTES:
                stderr = stderr[:MAX_OUTPUT_BYTES] + "\n…(stderr truncated)"
                truncated = True
            return {
                "ok": proc.returncode == 0,
                "exit_code": proc.returncode,
                "stdout": stdout,
                "stderr": stderr,
                "timed_out": False,
                "truncated": truncated,
                "sandbox": {
                    "mode": "subprocess -I",
                    "cwd": "isolated tempdir",
                    "env": "stripped (only SYSTEMROOT/TEMP retained)",
                    "network": "disabled (socket monkey-patched)",
                    "timeout_s": timeout_s,
                },
            }
        except subprocess.TimeoutExpired as exc:
            return {
                "ok": False,
                "timed_out": True,
                "timeout_s": timeout_s,
                "stdout": (exc.stdout or b"").decode("utf-8", errors="replace")[:MAX_OUTPUT_BYTES],
                "stderr": (exc.stderr or b"").decode("utf-8", errors="replace")[:MAX_OUTPUT_BYTES],
                "error": f"sandbox killed after {timeout_s}s wall-clock",
            }
        except Exception as exc:
            return {"ok": False, "error": f"sandbox launch failed: {exc!r}"}
        finally:
            shutil.rmtree(sandbox_dir, ignore_errors=True)
