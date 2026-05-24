"""
Skill registry: auto-discovery, manifests, enable/disable state.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any, Optional

from skill_base import (
    Skill,
    SkillManifest,
    load_manifest_json,
)


_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_SKILLS_DIR = _PROJECT_ROOT / "skills"
_STATE_PATH = _PROJECT_ROOT / "data" / "skill_state.json"


def _load_state() -> dict[str, dict[str, Any]]:
    if not _STATE_PATH.exists():
        return {}
    try:
        return json.loads(_STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _save_state(state: dict[str, dict[str, Any]]) -> None:
    _STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _STATE_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")


def _load_skill_manifest(skill_dir: Path) -> Optional[Skill]:
    """Load a skill from its JSON manifest without importing skill code.

    Skill Python is intentionally not imported in the host process. It
    runs later inside the subprocess sandbox.
    """
    py_path = skill_dir / "skill.py"
    if not py_path.exists():
        return None
    raw = load_manifest_json(skill_dir)
    if not raw:
        print("Skill {} is missing skill.json manifest".format(skill_dir.name))
        return None
    try:
        manifest = SkillManifest.from_dict(raw)
    except TypeError as exc:
        print("Skill {} has invalid manifest: {}".format(skill_dir.name, exc))
        return None
    skill = Skill(
        name=manifest.name,
        description=manifest.description,
        triggers=manifest.triggers,
        system_prompt=manifest.system_prompt,
        network_allowlist=manifest.network_allowlist,
        read_paths=manifest.read_paths,
        requires_generator=manifest.requires_generator,
        requires_retrieval=manifest.requires_retrieval,
        version=manifest.version,
    )
    skill.manifest.enabled = manifest.enabled
    return skill


class SkillRegistry:
    """In-memory registry of all available skills."""

    def __init__(self, skills_dir: Path = _SKILLS_DIR):
        self.skills_dir = skills_dir
        self._skills: dict[str, Skill] = {}
        self._state = _load_state()
        self._lock = threading.RLock()

    def discover(self) -> list[str]:
        """Walk skills_dir and (re)load every skill on disk."""
        with self._lock:
            self._skills.clear()
            if not self.skills_dir.exists():
                self.skills_dir.mkdir(parents=True, exist_ok=True)
                return []
            for entry in sorted(self.skills_dir.iterdir()):
                if not entry.is_dir():
                    continue
                if entry.name.startswith("_") or entry.name.startswith("."):
                    continue
                skill = _load_skill_manifest(entry)
                if skill is None:
                    continue
                # Apply persisted enable/disable state.
                if skill.name in self._state:
                    skill.manifest.enabled = bool(self._state[skill.name].get("enabled", True))
                self._skills[skill.name] = skill
            return list(self._skills.keys())

    # -- introspection --

    def names(self) -> list[str]:
        with self._lock:
            return list(self._skills.keys())

    def get(self, name: str) -> Optional[Skill]:
        with self._lock:
            return self._skills.get(name)

    def manifests(self, include_disabled: bool = True) -> list[SkillManifest]:
        with self._lock:
            out = []
            for skill in self._skills.values():
                if include_disabled or skill.manifest.enabled:
                    out.append(skill.manifest)
            return out

    def enabled_skills(self) -> list[Skill]:
        with self._lock:
            return [s for s in self._skills.values() if s.manifest.enabled]

    # -- mutation --

    def set_enabled(self, name: str, enabled: bool) -> bool:
        with self._lock:
            skill = self._skills.get(name)
            if skill is None:
                return False
            skill.manifest.enabled = bool(enabled)
            entry = self._state.get(name, {})
            entry["enabled"] = bool(enabled)
            self._state[name] = entry
            _save_state(self._state)
            return True

    def reload(self) -> list[str]:
        return self.discover()

    def create_skill_from_spec(
        self,
        *,
        name: str,
        description: str,
        system_prompt: str,
        triggers: Optional[list[str]] = None,
        function_body: Optional[str] = None,
        network_allowlist: Optional[list[str]] = None,
    ) -> Skill:
        """Materialize a new skill on disk from a manifest plus optional code.

        The skill ends up at `skills/<safe_name>/` with two files:
          * `skill.json` - the manifest fields.
          * `skill.py`   - either a generated template that calls the
                           LLM with the configured system prompt, or a
                           wrapper that runs the user-supplied
                           `function_body`.
        """
        safe_name = _slugify(name)
        if not safe_name:
            raise ValueError("Skill name must contain letters or digits")
        skill_dir = self.skills_dir / safe_name
        if skill_dir.exists():
            raise FileExistsError("Skill directory already exists: {}".format(skill_dir))
        skill_dir.mkdir(parents=True)

        manifest = {
            "name": safe_name,
            "description": description,
            "triggers": triggers or [],
            "system_prompt": system_prompt,
            "network_allowlist": network_allowlist or [],
            "requires_generator": True,
            "requires_retrieval": True,
            "version": "1.0.0",
            "enabled": True,
        }
        (skill_dir / "skill.json").write_text(
            json.dumps(manifest, indent=2), encoding="utf-8"
        )

        if function_body:
            # User-supplied implementation. Indent each line by four
            # spaces so it nests under the execute() function. The
            # sandbox will still enforce filesystem and network rules.
            indented = "\n".join("    " + line for line in function_body.splitlines() or [""])
            skill_py = (
                "from skill_base import Skill, SkillContext, SkillResult\n\n"
                "def _execute(ctx: SkillContext) -> SkillResult:\n"
                + indented + "\n\n"
                "SKILL = Skill(name={name!r}, description={desc!r}, execute=_execute, system_prompt={sp!r})\n"
            ).format(name=safe_name, desc=description, sp=system_prompt)
        else:
            # Default template: pass the configured system prompt to
            # the LLM along with the user's query and any retrieved
            # context the agent already fetched.
            skill_py = (
                "from skill_base import Skill, SkillContext, SkillResult\n\n"
                "def _execute(ctx: SkillContext) -> SkillResult:\n"
                "    gen = ctx.generator\n"
                "    if gen is None:\n"
                "        return SkillResult(answer='Generator unavailable')\n"
                "    context_parts = [c.get('text', '') for c in ctx.retrieved_chunks]\n"
                "    context = '\\n\\n'.join(context_parts)\n"
                "    answer = gen.generate(\n"
                "        ctx.query, context, user_context={sp!r}\n"
                "    )\n"
                "    sources = [\n"
                "        {{'file': c.get('source'), 'chunk': c.get('chunk_index'), 'score': c.get('score'), 'preview': (c.get('text') or '')[:100] + '...'}}\n"
                "        for c in ctx.retrieved_chunks\n"
                "    ]\n"
                "    return SkillResult(answer=answer, sources=sources)\n\n"
                "SKILL = Skill(name={name!r}, description={desc!r}, execute=_execute, system_prompt={sp!r})\n"
            ).format(name=safe_name, desc=description, sp=system_prompt)

        (skill_dir / "skill.py").write_text(skill_py, encoding="utf-8")

        # Hot-reload so the new skill is usable without a restart.
        self.discover()
        return self._skills[safe_name]


def _slugify(name: str) -> str:
    """Turn a free-form skill name into a safe directory name."""
    out = []
    for char in name.lower().strip():
        if char.isalnum():
            out.append(char)
        elif char in {" ", "-", "_"}:
            out.append("_")
    slug = "".join(out).strip("_")
    while "__" in slug:
        slug = slug.replace("__", "_")
    return slug


# Module-level singleton so the agent and the web app share state.
_registry_singleton: Optional[SkillRegistry] = None
_singleton_lock = threading.Lock()


def get_registry() -> SkillRegistry:
    """Return the shared registry, discovering skills on first use."""
    global _registry_singleton
    if _registry_singleton is None:
        with _singleton_lock:
            if _registry_singleton is None:
                reg = SkillRegistry()
                reg.discover()
                _registry_singleton = reg
    return _registry_singleton
