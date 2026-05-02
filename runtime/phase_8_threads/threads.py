"""Phase 8 — Multi-thread chat store.

See docs/rag-architecture.md §8.

* §8.1 Thread model: opaque UUID `thread_id`, optional non-PII
  `session_key`, message rows `{role, content, timestamp,
  retrieval_debug_id}`.
* §8.2 Context-window policy: last-N-turns window via `THREAD_MAX_TURNS`
  (default 6). Optional query expansion uses **prior user lines only**
  (never assistant echo) to keep PII / leakage surface minimal.
* §8.3 Concurrency: SQLite WAL mode locally; swap for Postgres in
  production by reusing the same schema.
* `post_user_message()` is the ingress: persist user turn → call phase 7
  `answer()` → persist assistant turn (with `retrieval_debug_id`) →
  return `SafeAnswer`.
"""
from __future__ import annotations

import logging
import os
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from runtime.phase_7_safety import SafeAnswer, SafetyPipeline

log = logging.getLogger(__name__)


DEFAULT_DB_PATH = "data/threads.sqlite"
DEFAULT_MAX_TURNS = 6


# ---------- schema ----------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS threads (
    thread_id   TEXT PRIMARY KEY,
    session_key TEXT,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    thread_id           TEXT NOT NULL REFERENCES threads(thread_id) ON DELETE CASCADE,
    role                TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content             TEXT NOT NULL,
    timestamp           TEXT NOT NULL,
    retrieval_debug_id  TEXT
);

CREATE INDEX IF NOT EXISTS idx_messages_thread ON messages(thread_id, id);
"""


@dataclass
class Message:
    role: str
    content: str
    timestamp: str
    retrieval_debug_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Thread:
    thread_id: str
    session_key: str | None
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------- helpers ----------


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _max_turns() -> int:
    raw = os.getenv("THREAD_MAX_TURNS", str(DEFAULT_MAX_TURNS))
    try:
        n = int(raw)
        return n if n > 0 else DEFAULT_MAX_TURNS
    except ValueError:
        return DEFAULT_MAX_TURNS


# ---------- store ----------


class ThreadStore:
    def __init__(self, db_path: str | None = None) -> None:
        self.db_path = db_path or os.getenv("THREAD_DB_PATH", DEFAULT_DB_PATH)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as conn:
            conn.executescript(_SCHEMA)

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        # WAL keeps readers non-blocking; fine for the single-host dev case.
        conn = sqlite3.connect(self.db_path, isolation_level=None, timeout=30.0)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            yield conn
        finally:
            conn.close()

    # ----- thread CRUD -----

    def create_thread(self, session_key: str | None = None) -> Thread:
        tid = uuid.uuid4().hex
        created = _now_iso()
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO threads(thread_id, session_key, created_at) VALUES (?, ?, ?)",
                (tid, session_key, created),
            )
        return Thread(thread_id=tid, session_key=session_key, created_at=created)

    def get_thread(self, thread_id: str) -> Thread | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT thread_id, session_key, created_at FROM threads WHERE thread_id=?",
                (thread_id,),
            ).fetchone()
        if not row:
            return None
        return Thread(
            thread_id=row["thread_id"],
            session_key=row["session_key"],
            created_at=row["created_at"],
        )

    def delete_thread(self, thread_id: str) -> bool:
        with self._conn() as conn:
            cur = conn.execute(
                "DELETE FROM threads WHERE thread_id = ?", (thread_id,)
            )
            return cur.rowcount > 0

    def list_threads(self, *, session_key: str | None = None, limit: int = 50) -> list[Thread]:
        with self._conn() as conn:
            if session_key is None:
                rows = conn.execute(
                    "SELECT thread_id, session_key, created_at FROM threads "
                    "ORDER BY created_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT thread_id, session_key, created_at FROM threads "
                    "WHERE session_key=? ORDER BY created_at DESC LIMIT ?",
                    (session_key, limit),
                ).fetchall()
        return [
            Thread(
                thread_id=r["thread_id"],
                session_key=r["session_key"],
                created_at=r["created_at"],
            )
            for r in rows
        ]

    # ----- messages -----

    def append_message(
        self,
        thread_id: str,
        role: str,
        content: str,
        *,
        retrieval_debug_id: str | None = None,
    ) -> Message:
        if role not in ("user", "assistant"):
            raise ValueError(f"invalid role: {role}")
        ts = _now_iso()
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO messages(thread_id, role, content, timestamp, retrieval_debug_id) "
                "VALUES (?, ?, ?, ?, ?)",
                (thread_id, role, content, ts, retrieval_debug_id),
            )
        return Message(
            role=role, content=content, timestamp=ts, retrieval_debug_id=retrieval_debug_id
        )

    def history(self, thread_id: str, *, limit: int | None = None) -> list[Message]:
        sql = (
            "SELECT role, content, timestamp, retrieval_debug_id FROM messages "
            "WHERE thread_id=? ORDER BY id ASC"
        )
        params: tuple[Any, ...] = (thread_id,)
        if limit is not None:
            sql += " LIMIT ?"
            params = (thread_id, limit)
        with self._conn() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [
            Message(
                role=r["role"],
                content=r["content"],
                timestamp=r["timestamp"],
                retrieval_debug_id=r["retrieval_debug_id"],
            )
            for r in rows
        ]

    # ----- §8.2 context window -----

    def recent_window(self, thread_id: str, *, max_turns: int | None = None) -> list[Message]:
        """Return the last `max_turns` of (user+assistant) message pairs."""
        n = max_turns or _max_turns()
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT role, content, timestamp, retrieval_debug_id FROM messages "
                "WHERE thread_id=? ORDER BY id DESC LIMIT ?",
                (thread_id, n * 2),
            ).fetchall()
        msgs = [
            Message(
                role=r["role"],
                content=r["content"],
                timestamp=r["timestamp"],
                retrieval_debug_id=r["retrieval_debug_id"],
            )
            for r in rows
        ]
        msgs.reverse()
        return msgs


# ---------- §8.2 retrieval query expansion ----------


def expand_query(thread_id: str, latest_user: str, store: ThreadStore) -> str:
    """Combine the latest user message with prior **user** lines only.

    Per §8.2, never echo assistant text into retrieval — it can leak prior
    citations / phrasing and amplify model errors. We grab the previous
    user turns within the last-N window and prepend their distinctive
    nouns to the latest query as context.
    """
    window = store.recent_window(thread_id)
    prior_user_lines = [
        m.content for m in window if m.role == "user" and m.content != latest_user
    ]
    if not prior_user_lines:
        return latest_user
    # Cheap context carry: join recent user lines as a prefix. The retriever
    # is dense + scheme-resolving so concatenated context resolves "same
    # scheme as before" follow-ups without an LLM rewrite step.
    prefix = " ".join(prior_user_lines[-3:])
    return f"{prefix} {latest_user}".strip()


# ---------- ingress ----------


class ThreadedChat:
    def __init__(
        self,
        *,
        store: ThreadStore | None = None,
        pipeline: SafetyPipeline | None = None,
    ) -> None:
        self.store = store or ThreadStore()
        self._pipeline = pipeline

    def _ensure_pipeline(self) -> SafetyPipeline:
        if self._pipeline is None:
            self._pipeline = SafetyPipeline()
        return self._pipeline

    def post_user_message(
        self,
        thread_id: str,
        content: str,
        *,
        use_query_expansion: bool = True,
    ) -> SafeAnswer:
        if self.store.get_thread(thread_id) is None:
            raise ValueError(f"unknown thread_id: {thread_id}")

        # 1. Persist user turn first so a crash mid-pipeline doesn't drop it.
        self.store.append_message(thread_id, "user", content)

        # 2. §8.2 expansion uses prior user lines only.
        query = (
            expand_query(thread_id, content, self.store)
            if use_query_expansion
            else content
        )

        # 3. Phase 7 orchestrates router → retrieve → generate.
        result = self._ensure_pipeline().answer(query)

        # 4. Persist assistant turn with a debug id for joining to logs.
        debug_id = uuid.uuid4().hex[:12]
        self.store.append_message(
            thread_id,
            "assistant",
            result.answer,
            retrieval_debug_id=debug_id,
        )
        return result
