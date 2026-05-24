"""
Child-process entry point for running a single skill.

This file is launched by skill_sandbox.run_skill(). It imports the skill
module only after the sandbox monkeypatches are installed, then exchanges
strict JSON messages with the host process. Expensive or privileged host
capabilities, such as the loaded LLM and web search object, are exposed as
request/response proxies instead of direct Python objects.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any


class _LLMRequest(Exception):
    def __init__(self, request: dict[str, Any]):
        super().__init__("llm_request")
        self.request = request


class _WebSearchRequest(Exception):
    def __init__(self, request: dict[str, Any]):
        super().__init__("web_search_request")
        self.request = request


class GeneratorProxy:
    def __init__(self, responses: list[str]):
        self.responses = responses
        self.index = 0

    def generate(self, question, context, temperature_override=None, user_context="", history=""):
        if self.index < len(self.responses):
            response = self.responses[self.index]
            self.index += 1
            return response
        raise _LLMRequest({
            "question": question,
            "context": context,
            "temperature_override": temperature_override,
            "user_context": user_context,
            "history": history,
        })


class WebSearchProxy:
    def __init__(self, responses: list[list[dict[str, Any]]]):
        self.responses = responses
        self.index = 0

    def search(self, query, max_results=None):
        if self.index < len(self.responses):
            rows = self.responses[self.index]
            self.index += 1
            return [
                (
                    SimpleNamespace(
                        text=row.get("text", ""),
                        source_file=row.get("source_file", "web"),
                        chunk_index=row.get("chunk_index", i),
                    ),
                    float(row.get("score", 0.0)),
                )
                for i, row in enumerate(rows)
            ]
        raise _WebSearchRequest({"query": query, "max_results": max_results})


def _load_skill(skill_dir: Path):
    from skill_base import Skill

    py_path = skill_dir / "skill.py"
    spec = importlib.util.spec_from_file_location("sandboxed_skill", py_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load skill.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    if hasattr(module, "SKILL") and isinstance(module.SKILL, Skill):
        return module.SKILL
    if hasattr(module, "create_skill"):
        candidate = module.create_skill()
        if isinstance(candidate, Skill):
            return candidate
    for name in dir(module):
        obj = getattr(module, name)
        if (
            isinstance(obj, type)
            and obj is not Skill
            and issubclass(obj, Skill)
            and name.endswith("Skill")
        ):
            return obj()
    raise RuntimeError("Skill module does not expose SKILL, create_skill(), or Skill subclass")


def _write(payload: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False))
    sys.stdout.flush()


def main() -> int:
    if len(sys.argv) != 4:
        _write({"type": "error", "error": "usage: runner <src_dir> <project_root> <skill_dir>"})
        return 2

    src_dir = Path(sys.argv[1]).resolve()
    project_root = Path(sys.argv[2]).resolve()
    skill_dir = Path(sys.argv[3]).resolve()
    sys.path.insert(0, str(src_dir))

    from skill_base import SkillContext, SkillResult
    from skill_sandbox import SkillSandboxError, _sandboxed

    try:
        payload = json.loads(sys.stdin.read() or "{}")
        with _sandboxed(SimpleNamespace(name=skill_dir.name, manifest=SimpleNamespace(
            name=skill_dir.name,
            network_allowlist=payload.get("network_allowlist", []),
            read_paths=payload.get("read_paths", []),
        )), project_root):
            skill = _load_skill(skill_dir)
            # Preserve manifest settings from the trusted JSON manifest
            # instead of trusting Python-level declarations.
            skill.manifest.network_allowlist = payload.get("network_allowlist", [])
            skill.manifest.read_paths = payload.get("read_paths", [])

            ctx = SkillContext(
                query=payload.get("query", ""),
                retrieved_chunks=payload.get("retrieved_chunks", []),
                user_memory=payload.get("user_memory", {}),
                generator=GeneratorProxy(payload.get("llm_responses", [])),
                web_search=WebSearchProxy(payload.get("web_search_responses", []))
                if payload.get("network_allowlist")
                else None,
                data_dir=project_root / "data",
                skill_dir=skill_dir,
            )
            result = skill.execute(ctx)
    except _LLMRequest as exc:
        _write({"type": "llm_request", "request": exc.request})
        return 0
    except _WebSearchRequest as exc:
        _write({"type": "web_search_request", "request": exc.request})
        return 0
    except SkillSandboxError as exc:
        _write({"type": "sandbox_violation", "error": str(exc)})
        return 0
    except Exception as exc:  # noqa: BLE001
        _write({
            "type": "error",
            "error_type": exc.__class__.__name__,
            "error": str(exc),
        })
        return 0

    if isinstance(result, SkillResult):
        output = result.to_dict()
    elif isinstance(result, dict):
        output = result
    else:
        output = {"answer": str(result)}
    _write({"type": "result", "result": output})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
