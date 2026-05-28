# termchat/storage — persistence layer

This package is the **only** code in the project that touches SQLite. Everything outside this directory works exclusively with plain Python dataclasses — no `sqlite3.Row` objects, no cursor handles, and no SQL strings ever leak out.

```
storage/
├── database.py   ← all public database functions
└── models.py     ← dataclass models mirroring the four tables
```

---

## Models (`models.py`)

### `Project`

```python
@dataclass
class Project:
    id: int
    name: str                    # unique
    instructions: str            # system prompt prepended to every chat in this project
    created_at: datetime
    updated_at: datetime
    files: list[ProjectFile]     # populated on demand; not stored in this table
```

### `ProjectFile`

```python
@dataclass
class ProjectFile:
    id: int
    project_id: int
    filename: str                # unique per project
    content: str                 # full text of the file
    created_at: datetime
```

### `Chat`

```python
@dataclass
class Chat:
    id: int
    title: str | None            # AI-generated before the first message; editable via /title
    provider: str                # e.g. "anthropic"
    model: str                   # e.g. "claude-sonnet-4-6"
    project_id: int | None       # FK → projects.id (SET NULL on delete)
    created_at: datetime
    updated_at: datetime
```

### `Message`

```python
@dataclass
class Message:
    id: int
    chat_id: int                 # FK → chats.id (CASCADE delete)
    role: str                    # "user" | "assistant" | "summary"
    content: str
    input_tokens: int | None     # populated on assistant turns
    output_tokens: int | None    # populated on assistant turns
    created_at: datetime

    @property
    def total_tokens(self) -> int: ...   # input + output (0 if None)

    @property
    def char_count(self) -> int: ...     # len(self.content)
```

---

## Schema

```sql
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE projects (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    name         TEXT    NOT NULL UNIQUE,
    instructions TEXT    NOT NULL DEFAULT '',
    created_at   TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at   TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE project_files (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id  INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    filename    TEXT    NOT NULL,
    content     TEXT    NOT NULL,
    created_at  TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE(project_id, filename)
);

CREATE TABLE chats (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    title       TEXT,
    provider    TEXT    NOT NULL DEFAULT 'anthropic',
    model       TEXT    NOT NULL,
    project_id  INTEGER REFERENCES projects(id) ON DELETE SET NULL,
    created_at  TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE messages (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id       INTEGER NOT NULL REFERENCES chats(id) ON DELETE CASCADE,
    role          TEXT    NOT NULL CHECK(role IN ('user','assistant','summary')),
    content       TEXT    NOT NULL,
    input_tokens  INTEGER,
    output_tokens INTEGER,
    created_at    TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_messages_chat_id ON messages(chat_id);
CREATE INDEX idx_chats_project_id ON chats(project_id);
```

### Design notes

- **WAL mode** — allows concurrent reads while a write is in progress. Suitable for a local single-user tool.
- **Foreign keys with `ON DELETE CASCADE`** — deleting a chat automatically deletes all its messages; deleting a project automatically deletes its attached files.
- **`ON DELETE SET NULL`** on `chats.project_id` — deleting a project does not delete the chats that belong to it; they become unattached.
- **`title` is nullable** — new chats start with `title=NULL`; the AI generates a title before the first message is sent and stores it via `update_chat_title`.
- **Datetime stored as TEXT** — ISO-8601 strings (`datetime('now')`). `database._dt()` parses them back to `datetime` objects.
- **File permissions** — `init()` sets `termchat.db` to `chmod 600` after creation so conversation history is only readable by the owning user.

---

## Public API (`database.py`)

### Initialisation

```python
init(path: Path) -> None
```

Must be called once before any other function. Creates the directory tree, runs the schema, and applies any pending migrations. Called automatically by the CLI root group on every invocation.

---

### Projects

```python
create_project(name: str, instructions: str = "") -> Project
get_project(project_id: int) -> Project | None          # includes files
get_project_by_name(name: str) -> Project | None        # includes files
list_projects() -> list[Project]                         # ordered by updated_at DESC
update_project(project_id, *, name=None, instructions=None) -> Project | None
delete_project(project_id: int) -> bool
```

---

### Project files

```python
add_project_file(project_id, filename, content) -> ProjectFile
    # Upsert: if (project_id, filename) already exists, the content is replaced.

get_project_files(project_id: int) -> list[ProjectFile]   # ordered by filename
remove_project_file(project_id, filename) -> bool
```

---

### Chats

```python
create_chat(model, provider="anthropic", project_id=None, title=None) -> Chat
get_chat(chat_id: int) -> Chat | None
list_chats(project_id=None, limit=50) -> list[Chat]     # ordered by updated_at DESC
update_chat_title(chat_id, title) -> None
touch_chat(chat_id) -> None                              # updates updated_at
delete_chat(chat_id) -> bool
```

---

### Messages

```python
add_message(chat_id, role, content, input_tokens=None, output_tokens=None) -> Message
get_messages(chat_id) -> list[Message]               # ordered by (created_at, id)
delete_messages_before(chat_id, before_id) -> int    # returns rows deleted
replace_messages_with_summary(chat_id, up_to_id, summary_content) -> Message
    # Atomically: delete messages with id <= up_to_id, insert one summary row.
    # The summary's created_at is set to the earliest deleted message's timestamp
    # so it always sorts before preserved recent messages.
chat_token_totals(chat_id) -> dict[str, int]         # {"input": N, "output": N}
```

---

## Migration system

`_migrate(conn)` is called inside `init()` and applies schema changes that post-date the initial table creation. Each migration is wrapped in `suppress(Exception)` so it is safe to run on a database that already has the change applied.

---

## Testing in isolation

```bash
TERMCHAT_CONFIG_DIR=/tmp/tc termchat chat new
```

Setting `TERMCHAT_CONFIG_DIR` redirects both `config.json` and `termchat.db` to a different directory, leaving your real database untouched. Delete `/tmp/tc` to reset.
