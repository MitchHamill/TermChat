"""SQLite persistence layer.

All public functions accept/return dataclass models or plain Python types —
no SQL leaks outside this module.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager, suppress
from datetime import datetime
from pathlib import Path
from typing import Generator

from termchat.storage.models import Chat, Message, Project, ProjectFile

# ── Schema ───────────────────────────────────────────────────────────────────

_SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS projects (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    name         TEXT    NOT NULL UNIQUE,
    instructions TEXT    NOT NULL DEFAULT '',
    created_at   TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at   TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS project_files (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id  INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    filename    TEXT    NOT NULL,
    content     TEXT    NOT NULL,
    created_at  TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE(project_id, filename)
);

CREATE TABLE IF NOT EXISTS chats (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    key         TEXT    UNIQUE,
    title       TEXT,
    provider    TEXT    NOT NULL DEFAULT 'anthropic',
    model       TEXT    NOT NULL,
    project_id  INTEGER REFERENCES projects(id) ON DELETE SET NULL,
    created_at  TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS messages (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id       INTEGER NOT NULL REFERENCES chats(id) ON DELETE CASCADE,
    role          TEXT    NOT NULL CHECK(role IN ('user','assistant','summary')),
    content       TEXT    NOT NULL,
    input_tokens  INTEGER,
    output_tokens INTEGER,
    created_at    TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_messages_chat_id ON messages(chat_id);
CREATE INDEX IF NOT EXISTS idx_chats_project_id ON chats(project_id);
"""

# ── Connection management ────────────────────────────────────────────────────

_db_path: Path | None = None


def init(path: Path) -> None:
    """Initialise the database at *path* and create tables if needed."""
    global _db_path
    path.parent.mkdir(parents=True, exist_ok=True)
    _db_path = path
    with _connect() as conn:
        conn.executescript(_SCHEMA)
        _migrate(conn)


def _migrate(conn: sqlite3.Connection) -> None:
    """Apply schema changes that post-date the initial table creation."""
    # Add the 'key' column to existing databases that don't have it yet.
    with suppress(Exception):
        conn.execute("ALTER TABLE chats ADD COLUMN key TEXT")
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_chats_key ON chats(key) WHERE key IS NOT NULL"
    )


@contextmanager
def _connect() -> Generator[sqlite3.Connection, None, None]:
    if _db_path is None:
        raise RuntimeError("Database not initialised — call database.init() first.")
    conn = sqlite3.connect(_db_path, detect_types=sqlite3.PARSE_DECLTYPES)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ── Helpers ──────────────────────────────────────────────────────────────────

def _dt(value: str | None) -> datetime | None:
    if value is None:
        return None
    try:
        return datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return datetime.now()


def _row_to_project(row: sqlite3.Row) -> Project:
    return Project(
        id=row["id"],
        name=row["name"],
        instructions=row["instructions"],
        created_at=_dt(row["created_at"]),
        updated_at=_dt(row["updated_at"]),
    )


def _row_to_file(row: sqlite3.Row) -> ProjectFile:
    return ProjectFile(
        id=row["id"],
        project_id=row["project_id"],
        filename=row["filename"],
        content=row["content"],
        created_at=_dt(row["created_at"]),
    )


def _row_to_chat(row: sqlite3.Row) -> Chat:
    keys = row.keys()
    return Chat(
        id=row["id"],
        key=row["key"] if "key" in keys else None,
        title=row["title"],
        provider=row["provider"],
        model=row["model"],
        project_id=row["project_id"],
        created_at=_dt(row["created_at"]),
        updated_at=_dt(row["updated_at"]),
    )


def _row_to_message(row: sqlite3.Row) -> Message:
    return Message(
        id=row["id"],
        chat_id=row["chat_id"],
        role=row["role"],
        content=row["content"],
        input_tokens=row["input_tokens"],
        output_tokens=row["output_tokens"],
        created_at=_dt(row["created_at"]),
    )


# ── Projects ─────────────────────────────────────────────────────────────────

def create_project(name: str, instructions: str = "") -> Project:
    with _connect() as conn:
        cur = conn.execute(
            "INSERT INTO projects (name, instructions) VALUES (?, ?)",
            (name, instructions),
        )
        row = conn.execute(
            "SELECT * FROM projects WHERE id=?", (cur.lastrowid,)
        ).fetchone()
        return _row_to_project(row)


def get_project(project_id: int) -> Project | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM projects WHERE id=?", (project_id,)
        ).fetchone()
        if not row:
            return None
        proj = _row_to_project(row)
        proj.files = get_project_files(project_id)
        return proj


def get_project_by_name(name: str) -> Project | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM projects WHERE name=?", (name,)
        ).fetchone()
        if not row:
            return None
        proj = _row_to_project(row)
        proj.files = get_project_files(proj.id)
        return proj


def list_projects() -> list[Project]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM projects ORDER BY updated_at DESC"
        ).fetchall()
        return [_row_to_project(r) for r in rows]


def update_project(project_id: int, *, name: str | None = None, instructions: str | None = None) -> Project | None:
    updates: list[str] = ["updated_at=datetime('now')"]
    params: list = []
    if name is not None:
        updates.append("name=?")
        params.append(name)
    if instructions is not None:
        updates.append("instructions=?")
        params.append(instructions)
    params.append(project_id)
    with _connect() as conn:
        conn.execute(
            f"UPDATE projects SET {', '.join(updates)} WHERE id=?", params
        )
    return get_project(project_id)


def delete_project(project_id: int) -> bool:
    with _connect() as conn:
        cur = conn.execute("DELETE FROM projects WHERE id=?", (project_id,))
        return cur.rowcount > 0


# ── Project files ─────────────────────────────────────────────────────────────

def add_project_file(project_id: int, filename: str, content: str) -> ProjectFile:
    with _connect() as conn:
        cur = conn.execute(
            """INSERT INTO project_files (project_id, filename, content)
               VALUES (?, ?, ?)
               ON CONFLICT(project_id, filename) DO UPDATE SET content=excluded.content""",
            (project_id, filename, content),
        )
        row = conn.execute(
            "SELECT * FROM project_files WHERE id=?",
            (cur.lastrowid or conn.execute(
                "SELECT id FROM project_files WHERE project_id=? AND filename=?",
                (project_id, filename)
            ).fetchone()["id"],),
        ).fetchone()
        return _row_to_file(row)


def get_project_files(project_id: int) -> list[ProjectFile]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM project_files WHERE project_id=? ORDER BY filename",
            (project_id,),
        ).fetchall()
        return [_row_to_file(r) for r in rows]


def remove_project_file(project_id: int, filename: str) -> bool:
    with _connect() as conn:
        cur = conn.execute(
            "DELETE FROM project_files WHERE project_id=? AND filename=?",
            (project_id, filename),
        )
        return cur.rowcount > 0


# ── Chats ────────────────────────────────────────────────────────────────────

def create_chat(model: str, provider: str = "anthropic", project_id: int | None = None, title: str | None = None) -> Chat:
    with _connect() as conn:
        cur = conn.execute(
            "INSERT INTO chats (title, provider, model, project_id) VALUES (?, ?, ?, ?)",
            (title, provider, model, project_id),
        )
        row = conn.execute("SELECT * FROM chats WHERE id=?", (cur.lastrowid,)).fetchone()
        return _row_to_chat(row)


def get_chat(chat_id: int) -> Chat | None:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM chats WHERE id=?", (chat_id,)).fetchone()
        return _row_to_chat(row) if row else None


def list_chats(project_id: int | None = None, limit: int = 50) -> list[Chat]:
    with _connect() as conn:
        if project_id is not None:
            rows = conn.execute(
                "SELECT * FROM chats WHERE project_id=? ORDER BY updated_at DESC LIMIT ?",
                (project_id, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM chats ORDER BY updated_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [_row_to_chat(r) for r in rows]


def get_chat_by_key(key: str) -> Chat | None:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM chats WHERE key=?", (key,)).fetchone()
        return _row_to_chat(row) if row else None


def update_chat_key(chat_id: int, key: str) -> str:
    """Persist *key* for *chat_id* and return it."""
    with _connect() as conn:
        conn.execute(
            "UPDATE chats SET key=? WHERE id=?",
            (key, chat_id),
        )
    return key


def unique_chat_key(base_key: str) -> str:
    """Return *base_key* if unused, otherwise *base_key*-2, *base_key*-3, …"""
    if get_chat_by_key(base_key) is None:
        return base_key
    n = 2
    while True:
        suffix = f"-{n}"
        candidate = base_key[: 10 - len(suffix)] + suffix
        if get_chat_by_key(candidate) is None:
            return candidate
        n += 1


def update_chat_title(chat_id: int, title: str) -> None:
    with _connect() as conn:
        conn.execute(
            "UPDATE chats SET title=?, updated_at=datetime('now') WHERE id=?",
            (title, chat_id),
        )


def touch_chat(chat_id: int) -> None:
    with _connect() as conn:
        conn.execute(
            "UPDATE chats SET updated_at=datetime('now') WHERE id=?", (chat_id,)
        )


def delete_chat(chat_id: int) -> bool:
    with _connect() as conn:
        cur = conn.execute("DELETE FROM chats WHERE id=?", (chat_id,))
        return cur.rowcount > 0


# ── Messages ─────────────────────────────────────────────────────────────────

def add_message(
    chat_id: int,
    role: str,
    content: str,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
) -> Message:
    with _connect() as conn:
        cur = conn.execute(
            """INSERT INTO messages (chat_id, role, content, input_tokens, output_tokens)
               VALUES (?, ?, ?, ?, ?)""",
            (chat_id, role, content, input_tokens, output_tokens),
        )
        row = conn.execute(
            "SELECT * FROM messages WHERE id=?", (cur.lastrowid,)
        ).fetchone()
        return _row_to_message(row)


def get_messages(chat_id: int) -> list[Message]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM messages WHERE chat_id=? ORDER BY created_at, id",
            (chat_id,),
        ).fetchall()
        return [_row_to_message(r) for r in rows]


def delete_messages_before(chat_id: int, before_id: int) -> int:
    """Delete all messages with id < *before_id* for *chat_id*."""
    with _connect() as conn:
        cur = conn.execute(
            "DELETE FROM messages WHERE chat_id=? AND id<?", (chat_id, before_id)
        )
        return cur.rowcount


def replace_messages_with_summary(chat_id: int, up_to_id: int, summary_content: str) -> Message:
    """Atomically delete old messages and insert a summary placeholder.

    The summary is given the *earliest* created_at of the deleted messages so
    it always sorts before the preserved recent messages when ordered by
    (created_at, id).
    """
    with _connect() as conn:
        # Grab the earliest timestamp among the messages we're about to delete
        ts_row = conn.execute(
            "SELECT MIN(created_at) AS ts FROM messages WHERE chat_id=? AND id<=?",
            (chat_id, up_to_id),
        ).fetchone()
        earliest_ts = ts_row["ts"] if ts_row and ts_row["ts"] else "1970-01-01 00:00:00"

        conn.execute(
            "DELETE FROM messages WHERE chat_id=? AND id<=?", (chat_id, up_to_id)
        )
        cur = conn.execute(
            """INSERT INTO messages (chat_id, role, content, created_at)
               VALUES (?, 'summary', ?, ?)""",
            (chat_id, summary_content, earliest_ts),
        )
        row = conn.execute(
            "SELECT * FROM messages WHERE id=?", (cur.lastrowid,)
        ).fetchone()
        return _row_to_message(row)


def chat_token_totals(chat_id: int) -> dict[str, int]:
    with _connect() as conn:
        row = conn.execute(
            """SELECT
                 COALESCE(SUM(input_tokens), 0)  AS input,
                 COALESCE(SUM(output_tokens), 0) AS output
               FROM messages WHERE chat_id=?""",
            (chat_id,),
        ).fetchone()
        return {"input": row["input"], "output": row["output"]}
