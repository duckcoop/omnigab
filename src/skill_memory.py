"""
SQLite-backed feedback memory for skills.

The router uses these aggregate scores to prefer skills that have worked
well for the user and to push consistently poor matches lower in the
candidate list.
"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Any


_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DB_PATH = _PROJECT_ROOT / "data" / "skill_memory.sqlite3"


class SkillMemory:
    """Stores skill feedback and exposes simple ranking scores."""

    def __init__(self, db_path: Path = _DB_PATH):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS skill_feedback (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts REAL NOT NULL,
                    skill_name TEXT NOT NULL,
                    query TEXT NOT NULL,
                    feedback INTEGER NOT NULL CHECK (feedback IN (-1, 1)),
                    notes TEXT DEFAULT ''
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_skill_feedback_name ON skill_feedback(skill_name)"
            )

    def record_feedback(
        self,
        skill_name: str,
        query: str,
        feedback: int | str | bool,
        notes: str = "",
    ) -> int:
        value = self._normalize_feedback(feedback)
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO skill_feedback (ts, skill_name, query, feedback, notes)
                VALUES (?, ?, ?, ?, ?)
                """,
                (time.time(), skill_name, query[:1000], value, notes[:1000]),
            )
            return int(cur.lastrowid)

    def score(self, skill_name: str) -> float:
        """Return a smoothed score in roughly [-1, 1]."""
        stats = self.stats_for(skill_name)
        return float(stats["score"])

    def stats_for(self, skill_name: str) -> dict[str, Any]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    SUM(CASE WHEN feedback = 1 THEN 1 ELSE 0 END) AS positive,
                    SUM(CASE WHEN feedback = -1 THEN 1 ELSE 0 END) AS negative,
                    COUNT(*) AS total
                FROM skill_feedback
                WHERE skill_name = ?
                """,
                (skill_name,),
            ).fetchone()
        positive = int(rows["positive"] or 0)
        negative = int(rows["negative"] or 0)
        total = int(rows["total"] or 0)
        score = 0.0
        if total:
            # Bayesian-ish smoothing keeps one bad click from burying a skill.
            score = (positive - negative) / (total + 2)
        return {
            "skill_name": skill_name,
            "positive": positive,
            "negative": negative,
            "total": total,
            "score": round(score, 4),
        }

    def all_stats(self) -> dict[str, dict[str, Any]]:
        with self._connect() as conn:
            names = [
                row["skill_name"]
                for row in conn.execute("SELECT DISTINCT skill_name FROM skill_feedback")
            ]
        return {name: self.stats_for(name) for name in names}

    @staticmethod
    def _normalize_feedback(value: int | str | bool) -> int:
        if isinstance(value, bool):
            return 1 if value else -1
        if isinstance(value, int):
            return 1 if value > 0 else -1
        text = str(value).strip().lower()
        if text in {"up", "thumbs_up", "positive", "good", "1", "+1", "true"}:
            return 1
        if text in {"down", "thumbs_down", "negative", "bad", "-1", "false"}:
            return -1
        raise ValueError("Feedback must be thumbs up/down")
