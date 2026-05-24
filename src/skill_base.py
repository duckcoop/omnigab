"""
Skill base classes and helpers.
===============================

A skill is a self-contained Python module that ships with a manifest
describing what it does and when to fire. The registry loads skills
from the project's `skills/` directory and exposes them to the agent's
router.

A skill module exposes ONE of the following:

  * A module-level `SKILL` attribute that is a `Skill` instance.
  * A `create_skill()` factory returning a `Skill` instance.
  * A subclass of `Skill` named `Skill` or anything ending in `Skill`.

The manifest portion of the skill (name, description, triggers, etc.)
may also be provided as a separate `skill.json` file in the same
directory. When both are present the JSON file wins, which lets users
ship a custom skill purely as JSON plus a small Python entry point.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Callable, Optional


@dataclass
class SkillContext:
    """Read-only context passed to skill execute() calls.

    Attributes:
      query: the validated user query that triggered the skill.
      retrieved_chunks: list of {text, source} dicts the RAG layer
        already pulled for this query. Skills can use them directly
        instead of asking the agent for new retrieval.
      user_memory: dict of persistent user preferences (read only;
        skills should not mutate this).
      generator: the loaded language model (optional). Skills should
        call `generator.generate(question, context, ...)` for any LLM
        work they need rather than spawning their own model.
      web_search: the web search engine instance, only set if the
        skill's manifest allows network access.
      data_dir: absolute path to the project's data/ directory; the
        only writable filesystem location a skill is allowed to touch.
      skill_dir: absolute path to this skill's own directory.
    """

    query: str
    retrieved_chunks: list[dict[str, Any]] = field(default_factory=list)
    user_memory: dict[str, Any] = field(default_factory=dict)
    generator: Any = None
    web_search: Any = None
    data_dir: Optional[Path] = None
    skill_dir: Optional[Path] = None


@dataclass
class SkillResult:
    """What a skill returns."""

    answer: str
    sources: list[dict[str, Any]] = field(default_factory=list)
    citations: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    used_skill: Optional[str] = None
    used_fallback: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SkillManifest:
    """Description of a skill used by the router."""

    name: str
    description: str
    triggers: list[str] = field(default_factory=list)
    system_prompt: Optional[str] = None
    network_allowlist: list[str] = field(default_factory=list)
    read_paths: list[str] = field(default_factory=list)
    requires_generator: bool = True
    requires_retrieval: bool = True
    version: str = "1.0.0"
    enabled: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "SkillManifest":
        clean = {k: v for k, v in raw.items() if k in cls.__dataclass_fields__}
        return cls(**clean)


class Skill:
    """Base class. Subclass it OR instantiate with kwargs."""

    def __init__(
        self,
        name: str,
        description: str,
        execute: Optional[Callable[[SkillContext], SkillResult]] = None,
        triggers: Optional[list[str]] = None,
        system_prompt: Optional[str] = None,
        network_allowlist: Optional[list[str]] = None,
        read_paths: Optional[list[str]] = None,
        requires_generator: bool = True,
        requires_retrieval: bool = True,
        version: str = "1.0.0",
    ):
        self.manifest = SkillManifest(
            name=name,
            description=description,
            triggers=triggers or [],
            system_prompt=system_prompt,
            network_allowlist=network_allowlist or [],
            read_paths=read_paths or [],
            requires_generator=requires_generator,
            requires_retrieval=requires_retrieval,
            version=version,
        )
        self._execute = execute

    # -- public API --

    @property
    def name(self) -> str:
        return self.manifest.name

    @property
    def description(self) -> str:
        return self.manifest.description

    def matches(self, query: str) -> float:
        """Lightweight keyword score in [0, 1].

        The full router uses the LLM to pick the best skill; this
        function is a cheap pre-filter so the LLM does not have to
        evaluate skills that have zero shared keywords with the query.
        """
        if not query:
            return 0.0
        q = query.lower()
        score = 0.0
        for trigger in self.manifest.triggers:
            t = trigger.lower().strip()
            if not t:
                continue
            try:
                if re.search(t, q):
                    score = max(score, 1.0)
                    continue
            except re.error:
                pass
            if t in q:
                score = max(score, 0.6)
        return score

    def execute(self, ctx: SkillContext) -> SkillResult:
        if self._execute is None:
            raise NotImplementedError(
                "Skill '{}' has no execute() function".format(self.name)
            )
        return self._execute(ctx)


# ----------------------------------------------------------- helpers

def load_manifest_json(skill_dir: Path) -> Optional[dict[str, Any]]:
    """Read skill.json from a skill directory if present."""
    candidate = skill_dir / "skill.json"
    if not candidate.exists():
        return None
    try:
        return json.loads(candidate.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def attach_manifest_overrides(skill: Skill, overrides: dict[str, Any]) -> None:
    """Apply overrides loaded from skill.json onto an in-code Skill."""
    for key, value in overrides.items():
        if key in SkillManifest.__dataclass_fields__:
            setattr(skill.manifest, key, value)
