"""Adapter that exposes a registered Skill as a Tool to the agent.

A skill is sandboxed code with a manifest. The adapter packages each
manifest as a Tool whose input schema accepts a free-form `query`
(plus an optional `extra` payload) and whose `run()` executes the
skill in its subprocess sandbox, returning the SkillResult as JSON.

Skill discovery + enable/disable still happen in `skill_registry`;
this layer just translates between the Skill API and the Tool API.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from skill_base import Skill, SkillContext, SkillResult
from skill_sandbox import SkillSandboxError, run_skill


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


class SkillTool:
    def __init__(
        self,
        skill: Skill,
        *,
        generator_getter: Callable[[], Any],
        web_search: Any,
        memory: Any,
    ):
        self.skill = skill
        self.name = skill.name
        self.description = skill.description or f"Run the {skill.name} skill."
        self.input_schema = {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Natural-language task for this skill.",
                },
            },
            "required": ["query"],
        }
        self._generator_getter = generator_getter
        self._web_search = web_search
        self._memory = memory

    def run(self, arguments: dict[str, Any]) -> dict[str, Any]:
        query = str(arguments.get("query") or "").strip()
        if not query:
            return {"ok": False, "error": "query is required"}

        ctx = SkillContext(
            query=query,
            retrieved_chunks=[],  # the agent has already called rag_search if it needed to
            user_memory=self._memory.get_all() if self._memory else {},
            generator=self._generator_getter(),
            web_search=self._web_search,
            data_dir=PROJECT_ROOT / "data",
            skill_dir=PROJECT_ROOT / "skills" / self.skill.name,
        )

        try:
            result = run_skill(self.skill, ctx, project_root=PROJECT_ROOT)
        except SkillSandboxError as exc:
            return {"ok": False, "error": f"sandbox blocked: {exc}"}
        except Exception as exc:
            return {"ok": False, "error": f"{exc.__class__.__name__}: {exc}"}

        if not isinstance(result, SkillResult):
            return {"ok": True, "answer": str(result)}

        return {
            "ok": True,
            "answer": result.answer,
            "sources": result.sources,
            "citations": result.citations,
            "metadata": result.metadata,
        }


def adapt_skill(skill: Skill, *, generator_getter, web_search, memory) -> SkillTool:
    return SkillTool(skill,
                     generator_getter=generator_getter,
                     web_search=web_search,
                     memory=memory)
