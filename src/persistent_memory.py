"""SQLite-backed persistent memory for the agent.

Lives alongside `UserMemory` (which keeps the legacy JSON file for
backwards compat). This module stores richer rows with timestamps and
categories so the agent can query "what do you know about X" rather
than reading the whole memory blob.

The agent loop calls `snapshot_for_prompt()` on every turn so facts
persist across sessions automatically.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "data" / "storage.db"
# Legacy path from earlier versions. If storage.db doesn't exist but
# memory.db does, we rename it in place on first access so existing users
# keep all their saved facts under the new name.
LEGACY_DB_PATH = PROJECT_ROOT / "data" / "memory.db"


def _migrate_legacy_db():
    """One-shot rename: data/memory.db → data/storage.db if applicable."""
    if DB_PATH.exists():
        return
    if LEGACY_DB_PATH.exists():
        try:
            DB_PATH.parent.mkdir(parents=True, exist_ok=True)
            LEGACY_DB_PATH.rename(DB_PATH)
            print(f"[persistent_memory] migrated {LEGACY_DB_PATH.name} → {DB_PATH.name}")
        except OSError as exc:
            print(f"[persistent_memory] could not migrate legacy DB: {exc}")


# Expanded category enum:
#   preference          — UI/behavior preferences ("I prefer remote work")
#   fact                — atomic facts ("my name is Cooper")
#   instruction         — custom rules ("always show certs first")
#   context             — session/topical context
#   goal                — career/project goals ("target GS-09 by EOY")
#   certification       — held certs cached structurally
#   application_history — applied-to jobs (url, date, status)
_SCHEMA = """
CREATE TABLE IF NOT EXISTS facts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    category    TEXT NOT NULL,
    key         TEXT NOT NULL,
    value       TEXT NOT NULL,
    source      TEXT,
    created_at  REAL NOT NULL,
    updated_at  REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_facts_cat_key ON facts(category, key);
CREATE INDEX IF NOT EXISTS idx_facts_key ON facts(key);

CREATE TABLE IF NOT EXISTS sessions (
    session_id   TEXT PRIMARY KEY,
    started_at   REAL NOT NULL,
    last_seen_at REAL NOT NULL,
    summary      TEXT
);

CREATE TABLE IF NOT EXISTS application_history (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    job_url       TEXT NOT NULL UNIQUE,
    job_title     TEXT,
    agency        TEXT,
    match_percent INTEGER,
    status        TEXT,                 -- 'flagged' | 'drafted' | 'applied' | 'rejected'
    applied_at    REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_history_status ON application_history(status);
"""

KNOWN_CATEGORIES = (
    "preference", "fact", "instruction", "context",
    "goal", "certification", "application_history",
)


class PersistentMemory:
    """Thread-safe SQLite wrapper."""

    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        # Migrate the legacy memory.db if present (no-op if storage.db
        # already exists or legacy was already migrated).
        if db_path == DB_PATH:
            _migrate_legacy_db()
        with self._conn() as conn:
            conn.executescript(_SCHEMA)

    @contextmanager
    def _conn(self):
        with self._lock:
            conn = sqlite3.connect(str(self.db_path))
            conn.row_factory = sqlite3.Row
            try:
                yield conn
                conn.commit()
            finally:
                conn.close()

    # ---------- writes ------------------------------------------------

    def put(self, category: str, key: str, value: Any, source: str = "user") -> int:
        now = time.time()
        value_str = value if isinstance(value, str) else json.dumps(value, default=str)
        with self._conn() as conn:
            cur = conn.execute(
                "SELECT id FROM facts WHERE category=? AND key=? LIMIT 1",
                (category, key),
            )
            row = cur.fetchone()
            if row:
                conn.execute(
                    "UPDATE facts SET value=?, source=?, updated_at=? WHERE id=?",
                    (value_str, source, now, row["id"]),
                )
                return int(row["id"])
            cur = conn.execute(
                "INSERT INTO facts(category,key,value,source,created_at,updated_at) "
                "VALUES (?,?,?,?,?,?)",
                (category, key, value_str, source, now, now),
            )
            return int(cur.lastrowid)

    def forget(self, category: str | None = None, key: str | None = None) -> int:
        with self._conn() as conn:
            if category and key:
                cur = conn.execute("DELETE FROM facts WHERE category=? AND key=?", (category, key))
            elif category:
                cur = conn.execute("DELETE FROM facts WHERE category=?", (category,))
            elif key:
                cur = conn.execute("DELETE FROM facts WHERE key=?", (key,))
            else:
                cur = conn.execute("DELETE FROM facts")
            return cur.rowcount

    def touch_session(self, session_id: str) -> None:
        now = time.time()
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO sessions(session_id,started_at,last_seen_at) VALUES (?,?,?) "
                "ON CONFLICT(session_id) DO UPDATE SET last_seen_at=excluded.last_seen_at",
                (session_id, now, now),
            )

    # ---------- reads -------------------------------------------------

    def get(self, category: str, key: str) -> str | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT value FROM facts WHERE category=? AND key=? LIMIT 1",
                (category, key),
            ).fetchone()
            return row["value"] if row else None

    def list_by_category(self, category: str) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT id,key,value,source,updated_at FROM facts WHERE category=? "
                "ORDER BY updated_at DESC",
                (category,),
            ).fetchall()
            return [dict(r) for r in rows]

    def search(self, term: str, limit: int = 20) -> list[dict]:
        """Substring search over keys + values. Useful for 'what do you know about X'."""
        like = f"%{term.lower()}%"
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT category,key,value,updated_at FROM facts "
                "WHERE LOWER(key) LIKE ? OR LOWER(value) LIKE ? "
                "ORDER BY updated_at DESC LIMIT ?",
                (like, like, limit),
            ).fetchall()
            return [dict(r) for r in rows]

    def all_rows(self) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT id,category,key,value,source,updated_at FROM facts "
                "ORDER BY category, updated_at DESC"
            ).fetchall()
            return [dict(r) for r in rows]

    # ---------- application history ----------------------------------

    def record_application(self, *, job_url: str, job_title: str,
                           agency: str, match_percent: int | None,
                           status: str = "flagged") -> int:
        now = time.time()
        with self._conn() as conn:
            cur = conn.execute(
                "INSERT INTO application_history(job_url,job_title,agency,"
                "match_percent,status,applied_at) VALUES (?,?,?,?,?,?) "
                "ON CONFLICT(job_url) DO UPDATE SET "
                "match_percent=excluded.match_percent, status=excluded.status",
                (job_url, job_title, agency, match_percent, status, now),
            )
            return int(cur.lastrowid or 0)

    def recent_applications(self, limit: int = 25) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT id,job_url,job_title,agency,match_percent,status,applied_at "
                "FROM application_history ORDER BY applied_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]

    # ---------- prompt injection -------------------------------------

    def snapshot_for_prompt(self, max_facts: int = 30) -> str:
        """Format the most recent facts as a system-prompt block.

        Called by the Agent before every turn so memory persists across
        sessions without the model having to explicitly fetch.
        """
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT category,key,value FROM facts ORDER BY updated_at DESC LIMIT ?",
                (max_facts,),
            ).fetchall()
        if not rows:
            return ""

        sections: dict[str, list[str]] = {}
        for r in rows:
            sections.setdefault(r["category"], []).append(f"  {r['key']}: {r['value']}")

        out = ["Known about the user (persistent memory):"]
        ordered = ("certification", "goal", "preference", "fact",
                   "instruction", "context", "application_history")
        for cat in ordered:
            if cat in sections:
                out.append(f"[{cat}]")
                out.extend(sections[cat])
        for cat, lines in sections.items():
            if cat not in ordered:
                out.append(f"[{cat}]")
                out.extend(lines)
        return "\n".join(out)


# Module-level singleton for the web app + desktop app to share.
_singleton: PersistentMemory | None = None
_singleton_lock = threading.Lock()


def get_persistent_memory() -> PersistentMemory:
    global _singleton
    if _singleton is None:
        with _singleton_lock:
            if _singleton is None:
                _singleton = PersistentMemory()
    return _singleton
