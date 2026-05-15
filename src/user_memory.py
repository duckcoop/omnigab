"""
User Memory Module
==================
Persistent user preferences and memory that personalizes RAG responses.
Stores preferences in a JSON file that survives restarts.

Preferences are injected into the generator prompt so answers respect
user-specific context like location, units, and custom instructions.
"""

import json
from pathlib import Path
from datetime import datetime

from config import PROJECT_ROOT

MEMORY_PATH = PROJECT_ROOT.parent / "user_memory.json"

DEFAULT_PREFERENCES = {
    "location": None,
    "units": "imperial",
    "language": "en",
    "custom_instructions": [],
    "learned_facts": {},
}


class UserMemory:
    """Manages persistent user preferences and learned context."""

    def __init__(self, path: Path = MEMORY_PATH):
        self.path = path
        self.preferences = dict(DEFAULT_PREFERENCES)
        self.load()

    def load(self):
        """Load preferences from disk."""
        if self.path.exists():
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                for key in DEFAULT_PREFERENCES:
                    if key in saved:
                        self.preferences[key] = saved[key]
                print(f"User memory loaded from {self.path.name}")
            except Exception as e:
                print(f"Could not load user memory: {e}")
        else:
            print("No user memory found, starting fresh.")

    def save(self):
        """Save preferences to disk."""
        self.preferences["last_updated"] = datetime.now().isoformat()
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self.preferences, f, indent=2)

    def get(self, key: str, default=None):
        """Get a preference value."""
        return self.preferences.get(key, default)

    def set(self, key: str, value):
        """Set a preference and save."""
        self.preferences[key] = value
        self.save()

    def add_instruction(self, instruction: str):
        """Add a custom instruction (e.g., 'dont use celsius')."""
        instructions = self.preferences.get("custom_instructions", [])
        normalized = instruction.strip().lower()
        for existing in instructions:
            if existing.lower() == normalized:
                return False
        instructions.append(instruction.strip())
        self.preferences["custom_instructions"] = instructions
        self.save()
        return True

    def remove_instruction(self, instruction: str):
        """Remove a custom instruction by text match."""
        instructions = self.preferences.get("custom_instructions", [])
        normalized = instruction.strip().lower()
        updated = [i for i in instructions if i.lower() != normalized]
        if len(updated) < len(instructions):
            self.preferences["custom_instructions"] = updated
            self.save()
            return True
        return False

    def learn_fact(self, key: str, value: str):
        """Store a learned fact about the user (e.g., name, job title)."""
        facts = self.preferences.get("learned_facts", {})
        facts[key] = value
        self.preferences["learned_facts"] = facts
        self.save()

    def forget_fact(self, key: str):
        """Remove a learned fact."""
        facts = self.preferences.get("learned_facts", {})
        if key in facts:
            del facts[key]
            self.preferences["learned_facts"] = facts
            self.save()
            return True
        return False

    def build_prompt_context(self) -> str:
        """
        Build a string to inject into the generator system prompt.
        Only includes preferences that are actually set.
        """
        parts = []

        location = self.get("location")
        if location:
            parts.append(f"The user is located in {location}.")

        units = self.get("units", "imperial")
        if units == "imperial":
            parts.append("Use Fahrenheit for temperature, miles for distance, pounds for weight.")
        elif units == "metric":
            parts.append("Use Celsius for temperature, kilometers for distance, kilograms for weight.")

        facts = self.get("learned_facts", {})
        if facts:
            fact_lines = [f"  {k}: {v}" for k, v in facts.items()]
            parts.append("Known facts about the user:\n" + "\n".join(fact_lines))

        instructions = self.get("custom_instructions", [])
        if instructions:
            parts.append("User preferences:\n" + "\n".join(f"  - {i}" for i in instructions))

        if not parts:
            return ""

        return "\n".join(parts)

    def get_all(self) -> dict:
        """Return all current preferences."""
        return dict(self.preferences)

    def clear(self):
        """Reset all preferences to defaults."""
        self.preferences = dict(DEFAULT_PREFERENCES)
        self.save()


if __name__ == "__main__":
    print("=== User Memory Test ===\n")
    mem = UserMemory()
    mem.set("location", "Frederick, MD")
    mem.set("units", "imperial")
    mem.add_instruction("Don't use Celsius, I'm in the US")
    mem.add_instruction("Keep answers short unless I ask for detail")
    mem.learn_fact("name", "Cooper")
    print(f"\nPreferences: {json.dumps(mem.get_all(), indent=2)}")
    print(f"\nPrompt context:\n{mem.build_prompt_context()}")
