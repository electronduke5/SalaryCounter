# SQLite Storage Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the single-file JSON store with SQLite, normalize the schema, and encrypt ClickUp tokens — eliminating full-file rewrites and read-modify-write races.

**Architecture:** Method-oriented repository (`DataManager`) over one shared SQLite connection (WAL). Callers stop mutating a returned dict and instead call explicit atomic methods. A verified, idempotent migration (`migrate_to_sqlite.py`) converts the existing JSON on first startup and can also be run by hand. ClickUp tokens are encrypted with Fernet using a key from `.env`.

**Tech Stack:** Python 3.8+, sqlite3 (stdlib), `cryptography` (Fernet), aiogram, FastAPI, pytest.

## Global Constraints

- Everything runs in ONE asyncio process (`api.py` starts the bot in its lifespan and injects the shared `DataManager`). Use ONE shared `sqlite3.Connection`.
- DB file: `salary.db`. JSON source: `salary_data.json`. Encryption key env var: `ENCRYPTION_KEY`.
- SQLite PRAGMAs on every connection: `journal_mode=WAL`, `foreign_keys=ON`, `busy_timeout=5000`.
- User ids are TEXT (Telegram id as string), matching current JSON keys.
- Write methods must be synchronous with no `await` inside (atomicity vs coroutine interleaving).
- Tokens are stored encrypted only; decrypt at the point of building a `ClickUpClient`.
- Preserve current sync behavior: entries with `duration_ms < 0` are skipped before dedup and never marked synced.
- Russian is the user-facing language; do not change any user-visible strings.
- Existing tests live in `tests/`; run with `pytest`.

---

### Task 1: Dependencies, .gitignore, encryption module

**Files:**
- Modify: `requirements.txt`
- Modify: `.gitignore`
- Modify: `.env.example`
- Create: `crypto.py`
- Test: `tests/test_crypto.py`

**Interfaces:**
- Produces:
  - `crypto.get_fernet() -> cryptography.fernet.Fernet` — reads `ENCRYPTION_KEY`, raises `RuntimeError` with instructions if unset/invalid.
  - `crypto.encrypt(plaintext: str) -> str`
  - `crypto.decrypt(token: str) -> str`
  - `crypto.generate_key() -> str`
  - CLI: `python crypto.py genkey` prints a fresh key.

- [ ] **Step 1: Add dependency**

In `requirements.txt`, under the aiohttp/fastapi block (before the `# dev` line), add:

```
cryptography==43.0.1
```

- [ ] **Step 2: Ignore the DB file and its WAL sidecars**

Append to `.gitignore`:

```
salary.db
salary.db-wal
salary.db-shm
salary.db.tmp
salary_data.json.migrated-*
```

- [ ] **Step 3: Document the env var**

Append to `.env.example`:

```
# Fernet key for encrypting ClickUp tokens at rest. Generate with: python crypto.py genkey
ENCRYPTION_KEY=
```

- [ ] **Step 4: Install the new dependency**

Run: `pip install cryptography==43.0.1`
Expected: installs successfully.

- [ ] **Step 5: Write the failing test**

Create `tests/test_crypto.py`:

```python
import importlib

import pytest


def _reload_crypto(monkeypatch, key):
    if key is None:
        monkeypatch.delenv("ENCRYPTION_KEY", raising=False)
    else:
        monkeypatch.setenv("ENCRYPTION_KEY", key)
    import crypto
    return importlib.reload(crypto)


def test_round_trip(monkeypatch):
    from cryptography.fernet import Fernet
    crypto = _reload_crypto(monkeypatch, Fernet.generate_key().decode())
    token = "pk_12345_SECRETTOKEN"
    enc = crypto.encrypt(token)
    assert enc != token
    assert crypto.decrypt(enc) == token


def test_missing_key_raises(monkeypatch):
    crypto = _reload_crypto(monkeypatch, None)
    with pytest.raises(RuntimeError):
        crypto.encrypt("anything")


def test_generate_key_is_usable(monkeypatch):
    crypto = _reload_crypto(monkeypatch, None)
    key = crypto.generate_key()
    crypto2 = _reload_crypto(monkeypatch, key)
    assert crypto2.decrypt(crypto2.encrypt("x")) == "x"
```

- [ ] **Step 6: Run test to verify it fails**

Run: `pytest tests/test_crypto.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'crypto'`.

- [ ] **Step 7: Implement `crypto.py`**

```python
import os
import sys

from cryptography.fernet import Fernet

_KEY_ENV = "ENCRYPTION_KEY"

_INSTRUCTIONS = (
    f"{_KEY_ENV} is not set or invalid. Generate one with:\n"
    "    python crypto.py genkey\n"
    f"then add it to your .env as {_KEY_ENV}=<value>."
)


def get_fernet() -> Fernet:
    key = os.environ.get(_KEY_ENV)
    if not key:
        raise RuntimeError(_INSTRUCTIONS)
    try:
        return Fernet(key.encode())
    except Exception as exc:
        raise RuntimeError(_INSTRUCTIONS) from exc


def encrypt(plaintext: str) -> str:
    return get_fernet().encrypt(plaintext.encode()).decode()


def decrypt(token: str) -> str:
    return get_fernet().decrypt(token.encode()).decode()


def generate_key() -> str:
    return Fernet.generate_key().decode()


if __name__ == "__main__":
    if len(sys.argv) == 2 and sys.argv[1] == "genkey":
        print(generate_key())
    else:
        print("usage: python crypto.py genkey")
        sys.exit(1)
```

- [ ] **Step 8: Run test to verify it passes**

Run: `pytest tests/test_crypto.py -v`
Expected: PASS (3 passed).

- [ ] **Step 9: Commit**

```bash
git add requirements.txt .gitignore .env.example crypto.py tests/test_crypto.py
git commit -m "feat: add Fernet token encryption module"
```

---

### Task 2: Database module (schema + connection)

**Files:**
- Create: `db.py`
- Test: `tests/test_db.py`

**Interfaces:**
- Produces:
  - `db.get_connection(db_path: str) -> sqlite3.Connection` — applies PRAGMAs, sets `row_factory = sqlite3.Row`, calls `init_schema`.
  - `db.init_schema(conn: sqlite3.Connection) -> None` — creates tables/indexes if absent (idempotent).

- [ ] **Step 1: Write the failing test**

Create `tests/test_db.py`:

```python
import db


def test_schema_creates_tables(tmp_path):
    conn = db.get_connection(str(tmp_path / "t.db"))
    names = {r["name"] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"users", "work_sessions", "synced_entries"} <= names


def test_pragmas_applied(tmp_path):
    conn = db.get_connection(str(tmp_path / "t.db"))
    assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_init_schema_is_idempotent(tmp_path):
    path = str(tmp_path / "t.db")
    db.get_connection(path)
    conn2 = db.get_connection(path)  # second open must not raise
    assert conn2.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_db.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'db'`.

- [ ] **Step 3: Implement `db.py`**

```python
import sqlite3

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id              TEXT PRIMARY KEY,
    rate                 REAL NOT NULL DEFAULT 0,
    clickup_api_token    TEXT,
    clickup_workspace_id TEXT,
    clickup_team_id      TEXT,
    clickup_user_id      TEXT,
    clickup_username     TEXT
);

CREATE TABLE IF NOT EXISTS work_sessions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      TEXT NOT NULL REFERENCES users(user_id),
    date         TEXT NOT NULL,
    hours        INTEGER NOT NULL DEFAULT 0,
    minutes      INTEGER NOT NULL DEFAULT 0,
    earnings     REAL NOT NULL DEFAULT 0,
    timestamp    TEXT,
    source       TEXT NOT NULL DEFAULT 'clickup',
    clickup_id   TEXT,
    task_name    TEXT,
    project_name TEXT,
    description  TEXT
);
CREATE INDEX IF NOT EXISTS idx_sessions_user_date ON work_sessions(user_id, date);

CREATE TABLE IF NOT EXISTS synced_entries (
    user_id  TEXT NOT NULL REFERENCES users(user_id),
    entry_id TEXT NOT NULL,
    PRIMARY KEY (user_id, entry_id)
);
"""


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(_SCHEMA)
    conn.commit()


def get_connection(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    init_schema(conn)
    return conn
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_db.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add db.py tests/test_db.py
git commit -m "feat: add SQLite schema and connection module"
```

---

### Task 3: DataManager — construction and read methods

Rewrites `data_manager.py`'s persistence core. Report/formatting helpers that don't touch storage are kept; the storage-facing parts change. This task covers construction + reads; Task 4 adds writes; Task 5 rewires `sync_clickup_entries`; Task 6 adapts the report generators.

**Files:**
- Modify: `data_manager.py` (replace `__init__`, `load_data`, `save_data`, `get_user_data`; add read methods)
- Test: `tests/test_data_manager_reads.py`

**Interfaces:**
- Consumes: `db.get_connection`, `crypto.encrypt`, `crypto.decrypt`.
- Produces:
  - `DataManager(db_path: str = "salary.db")`
  - `.conn` — the shared `sqlite3.Connection`
  - `ensure_user(user_id: str) -> None`
  - `get_rate(user_id: str) -> float`
  - `get_clickup_settings(user_id: str) -> dict` — keys `api_token` (decrypted), `workspace_id`, `team_id`, `user_id`, `username`; all `None` if unset
  - `get_work_sessions(user_id: str) -> dict` — legacy shape `{date_str: {"total_hours": float, "total_earnings": float, "sessions": [ {hours, minutes, earnings, timestamp, source, clickup_id, task_name, project_name, description}, ... ]}}`
  - `is_entry_synced(user_id: str, entry_id: str) -> bool`
  - `get_user_clickup_client(user_id: str) -> ClickUpClient | None` (unchanged behavior, now reads via `get_clickup_settings`)

- [ ] **Step 1: Write the failing test**

Create `tests/test_data_manager_reads.py`:

```python
from cryptography.fernet import Fernet


def _dm(tmp_path, monkeypatch):
    monkeypatch.setenv("ENCRYPTION_KEY", Fernet.generate_key().decode())
    from data_manager import DataManager
    return DataManager(str(tmp_path / "salary.db"))


def test_defaults_for_new_user(tmp_path, monkeypatch):
    dm = _dm(tmp_path, monkeypatch)
    dm.ensure_user("42")
    assert dm.get_rate("42") == 0
    assert dm.get_work_sessions("42") == {}
    settings = dm.get_clickup_settings("42")
    assert settings["api_token"] is None
    assert settings["workspace_id"] is None


def test_is_entry_synced_false_when_absent(tmp_path, monkeypatch):
    dm = _dm(tmp_path, monkeypatch)
    dm.ensure_user("42")
    assert dm.is_entry_synced("42", "e1") is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_data_manager_reads.py -v`
Expected: FAIL (e.g. `TypeError` on `DataManager(...)` or `AttributeError` for missing methods).

- [ ] **Step 3: Replace the top of `data_manager.py`**

Replace the imports/constant block and the `__init__`/`load_data`/`save_data`/`get_user_data` methods (currently `data_manager.py:1-88`) with:

```python
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional

import crypto
import db
from clickup_client import ClickUpClient

logger = logging.getLogger(__name__)

DB_FILE = "salary.db"

_CLICKUP_KEYS = ("api_token", "workspace_id", "team_id", "user_id", "username")


class DataManager:
    """Управление данными пользователей и генерация отчётов (хранилище — SQLite)."""

    def __init__(self, db_path: str = DB_FILE):
        self.db_path = db_path
        self.conn = db.get_connection(db_path)

    def ensure_user(self, user_id: str) -> None:
        self.conn.execute(
            "INSERT OR IGNORE INTO users (user_id, rate) VALUES (?, 0)", (user_id,)
        )
        self.conn.commit()

    def get_rate(self, user_id: str) -> float:
        row = self.conn.execute(
            "SELECT rate FROM users WHERE user_id = ?", (user_id,)
        ).fetchone()
        return row["rate"] if row else 0.0

    def get_clickup_settings(self, user_id: str) -> Dict[str, Any]:
        row = self.conn.execute(
            "SELECT clickup_api_token, clickup_workspace_id, clickup_team_id, "
            "clickup_user_id, clickup_username FROM users WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        if not row:
            return {k: None for k in _CLICKUP_KEYS}
        token = row["clickup_api_token"]
        return {
            "api_token": crypto.decrypt(token) if token else None,
            "workspace_id": row["clickup_workspace_id"],
            "team_id": row["clickup_team_id"],
            "user_id": row["clickup_user_id"],
            "username": row["clickup_username"],
        }

    def get_work_sessions(self, user_id: str) -> Dict[str, Any]:
        cur = self.conn.execute(
            "SELECT date, hours, minutes, earnings, timestamp, source, clickup_id, "
            "task_name, project_name, description FROM work_sessions "
            "WHERE user_id = ? ORDER BY id",
            (user_id,),
        )
        result: Dict[str, Any] = {}
        for row in cur:
            day = result.setdefault(
                row["date"], {"total_hours": 0.0, "total_earnings": 0.0, "sessions": []}
            )
            day["sessions"].append({
                "hours": row["hours"],
                "minutes": row["minutes"],
                "earnings": row["earnings"],
                "timestamp": row["timestamp"],
                "source": row["source"],
                "clickup_id": row["clickup_id"],
                "task_name": row["task_name"],
                "project_name": row["project_name"],
                "description": row["description"],
            })
            day["total_hours"] += row["hours"] + row["minutes"] / 60
            day["total_earnings"] += row["earnings"]
        return result

    def is_entry_synced(self, user_id: str, entry_id: str) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM synced_entries WHERE user_id = ? AND entry_id = ?",
            (user_id, entry_id),
        ).fetchone()
        return row is not None
```

- [ ] **Step 4: Update `get_user_clickup_client` to read via settings**

Replace the body of `get_user_clickup_client` (currently `data_manager.py:464-475`) with:

```python
    def get_user_clickup_client(self, user_id: str) -> Optional[ClickUpClient]:
        """Получение ClickUp клиента для конкретного пользователя"""
        settings = self.get_clickup_settings(user_id)
        api_token = settings.get("api_token")
        workspace_id = settings.get("workspace_id")
        if not api_token or not workspace_id:
            return None
        return ClickUpClient(api_token, workspace_id)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_data_manager_reads.py -v`
Expected: PASS (2 passed).

- [ ] **Step 6: Commit**

```bash
git add data_manager.py tests/test_data_manager_reads.py
git commit -m "feat: DataManager reads backed by SQLite"
```

---

### Task 4: DataManager — write methods

**Files:**
- Modify: `data_manager.py` (add write methods)
- Test: `tests/test_data_manager_writes.py`

**Interfaces:**
- Consumes: `self.conn`, `crypto.encrypt`, `ensure_user`.
- Produces:
  - `set_rate(user_id: str, rate: float) -> None`
  - `set_clickup_settings(user_id: str, **fields) -> None` — accepts any of `api_token, workspace_id, team_id, user_id, username`; encrypts `api_token`
  - `clear_clickup_settings(user_id: str) -> None`
  - `add_session(user_id: str, date: str, session: dict) -> None` — session keys: `hours, minutes, earnings, timestamp, source, clickup_id, task_name, project_name, description` (missing keys default sensibly)
  - `try_mark_synced(user_id: str, entry_id: str) -> bool` — `INSERT OR IGNORE`; returns `True` iff newly inserted

- [ ] **Step 1: Write the failing test**

Create `tests/test_data_manager_writes.py`:

```python
from cryptography.fernet import Fernet


def _dm(tmp_path, monkeypatch):
    monkeypatch.setenv("ENCRYPTION_KEY", Fernet.generate_key().decode())
    from data_manager import DataManager
    return DataManager(str(tmp_path / "salary.db"))


def test_set_rate(tmp_path, monkeypatch):
    dm = _dm(tmp_path, monkeypatch)
    dm.set_rate("42", 500.0)
    assert dm.get_rate("42") == 500.0


def test_token_stored_encrypted(tmp_path, monkeypatch):
    dm = _dm(tmp_path, monkeypatch)
    dm.set_clickup_settings("42", api_token="pk_SECRET", workspace_id="ws1")
    raw = dm.conn.execute(
        "SELECT clickup_api_token FROM users WHERE user_id='42'").fetchone()[0]
    assert raw != "pk_SECRET"                       # ciphertext in the column
    assert dm.get_clickup_settings("42")["api_token"] == "pk_SECRET"
    assert dm.get_clickup_settings("42")["workspace_id"] == "ws1"


def test_clear_clickup_settings(tmp_path, monkeypatch):
    dm = _dm(tmp_path, monkeypatch)
    dm.set_clickup_settings("42", api_token="pk_SECRET", workspace_id="ws1")
    dm.clear_clickup_settings("42")
    s = dm.get_clickup_settings("42")
    assert s["api_token"] is None and s["workspace_id"] is None


def test_add_session_aggregates(tmp_path, monkeypatch):
    dm = _dm(tmp_path, monkeypatch)
    dm.add_session("42", "2026-07-04", {
        "hours": 1, "minutes": 30, "earnings": 750.0, "source": "clickup",
        "clickup_id": "e1", "task_name": "T", "project_name": "P", "description": "",
        "timestamp": "2026-07-04T10:00:00",
    })
    ws = dm.get_work_sessions("42")
    assert ws["2026-07-04"]["total_earnings"] == 750.0
    assert abs(ws["2026-07-04"]["total_hours"] - 1.5) < 1e-9
    assert len(ws["2026-07-04"]["sessions"]) == 1


def test_try_mark_synced_dedups(tmp_path, monkeypatch):
    dm = _dm(tmp_path, monkeypatch)
    dm.ensure_user("42")
    assert dm.try_mark_synced("42", "e1") is True
    assert dm.try_mark_synced("42", "e1") is False   # second time: already present
    assert dm.is_entry_synced("42", "e1") is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_data_manager_writes.py -v`
Expected: FAIL with `AttributeError` for the missing methods.

- [ ] **Step 3: Add write methods to `DataManager`**

Insert after `is_entry_synced` (from Task 3):

```python
    def set_rate(self, user_id: str, rate: float) -> None:
        self.ensure_user(user_id)
        self.conn.execute(
            "UPDATE users SET rate = ? WHERE user_id = ?", (rate, user_id)
        )
        self.conn.commit()

    def set_clickup_settings(self, user_id: str, **fields) -> None:
        self.ensure_user(user_id)
        column_map = {
            "api_token": "clickup_api_token",
            "workspace_id": "clickup_workspace_id",
            "team_id": "clickup_team_id",
            "user_id": "clickup_user_id",
            "username": "clickup_username",
        }
        assignments = []
        values = []
        for key, value in fields.items():
            if key not in column_map:
                continue
            if key == "api_token" and value is not None:
                value = crypto.encrypt(value)
            assignments.append(f"{column_map[key]} = ?")
            values.append(value)
        if not assignments:
            return
        values.append(user_id)
        self.conn.execute(
            f"UPDATE users SET {', '.join(assignments)} WHERE user_id = ?", values
        )
        self.conn.commit()

    def clear_clickup_settings(self, user_id: str) -> None:
        self.ensure_user(user_id)
        self.conn.execute(
            "UPDATE users SET clickup_api_token = NULL, clickup_workspace_id = NULL, "
            "clickup_team_id = NULL, clickup_user_id = NULL, clickup_username = NULL "
            "WHERE user_id = ?",
            (user_id,),
        )
        self.conn.commit()

    def add_session(self, user_id: str, date: str, session: Dict[str, Any]) -> None:
        self.ensure_user(user_id)
        self.conn.execute(
            "INSERT INTO work_sessions (user_id, date, hours, minutes, earnings, "
            "timestamp, source, clickup_id, task_name, project_name, description) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                user_id,
                date,
                int(session.get("hours", 0)),
                int(session.get("minutes", 0)),
                float(session.get("earnings", 0)),
                session.get("timestamp"),
                session.get("source", "clickup"),
                session.get("clickup_id"),
                session.get("task_name"),
                session.get("project_name"),
                session.get("description", ""),
            ),
        )
        self.conn.commit()

    def try_mark_synced(self, user_id: str, entry_id: str) -> bool:
        self.ensure_user(user_id)
        cur = self.conn.execute(
            "INSERT OR IGNORE INTO synced_entries (user_id, entry_id) VALUES (?, ?)",
            (user_id, entry_id),
        )
        self.conn.commit()
        return cur.rowcount == 1
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_data_manager_writes.py -v`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add data_manager.py tests/test_data_manager_writes.py
git commit -m "feat: DataManager atomic write methods"
```

---

### Task 5: Rewrite `sync_clickup_entries` onto the new methods

**Files:**
- Modify: `data_manager.py` (replace `sync_clickup_entries`, currently `data_manager.py:828-906`)
- Test: `tests/test_sync.py`

**Interfaces:**
- Consumes: `get_user_clickup_client`, `get_rate`, `try_mark_synced`, `add_session`, `_entry_list_id`, `_resolve_list_name`.
- Produces: `async sync_clickup_entries(user_id, start_date, end_date) -> dict` (unchanged return shape: `success`, `synced_count`, `total_hours`, `total_earnings`, or `success/error`).

- [ ] **Step 1: Write the failing test**

Create `tests/test_sync.py`:

```python
from datetime import datetime

import pytest
from cryptography.fernet import Fernet


def _dm(tmp_path, monkeypatch):
    monkeypatch.setenv("ENCRYPTION_KEY", Fernet.generate_key().decode())
    from data_manager import DataManager
    return DataManager(str(tmp_path / "salary.db"))


class FakeClient:
    def __init__(self, entries):
        self._entries = entries

    async def get_time_entries(self, start, end):
        return self._entries

    async def get_list(self, list_id):
        return {"name": "Проект X"}


@pytest.mark.asyncio
async def test_sync_inserts_and_dedups(tmp_path, monkeypatch):
    dm = _dm(tmp_path, monkeypatch)
    dm.set_rate("42", 600.0)
    entry = {
        "id": "e1", "duration": str(1000 * 60 * 90),  # 1.5h in ms
        "start": str(int(datetime(2026, 7, 4, 10).timestamp() * 1000)),
        "task": {"name": "Задача", "list": {"id": "L1"}},
        "description": "",
    }
    monkeypatch.setattr(dm, "get_user_clickup_client", lambda uid: FakeClient([entry]))

    r1 = await dm.sync_clickup_entries("42", datetime(2026, 7, 1), datetime(2026, 7, 31))
    assert r1["success"] and r1["synced_count"] == 1
    assert abs(r1["total_earnings"] - 900.0) < 1e-6      # 1.5h * 600

    r2 = await dm.sync_clickup_entries("42", datetime(2026, 7, 1), datetime(2026, 7, 31))
    assert r2["synced_count"] == 0                        # already synced

    ws = dm.get_work_sessions("42")
    assert len(ws["2026-07-04"]["sessions"]) == 1
    assert ws["2026-07-04"]["sessions"][0]["project_name"] == "Проект X"


@pytest.mark.asyncio
async def test_sync_skips_negative_duration(tmp_path, monkeypatch):
    dm = _dm(tmp_path, monkeypatch)
    dm.set_rate("42", 600.0)
    running = {"id": "run1", "duration": "-1000", "start": "0", "task": None, "description": ""}
    monkeypatch.setattr(dm, "get_user_clickup_client", lambda uid: FakeClient([running]))
    r = await dm.sync_clickup_entries("42", datetime(2026, 7, 1), datetime(2026, 7, 31))
    assert r["success"] and r["synced_count"] == 0
    assert dm.is_entry_synced("42", "run1") is False     # never marked
```

- [ ] **Step 2: Ensure async test support**

Confirm `pytest-asyncio` is available (existing `tests/test_clickup_status.py` may already use it). If `pytest tests/test_sync.py` errors on the `asyncio` marker, add to `requirements.txt` under `# dev`:

```
pytest-asyncio==0.24.0
```

Then create `pytest.ini` at repo root:

```ini
[pytest]
asyncio_mode = auto
```

Run: `pip install pytest-asyncio==0.24.0`

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_sync.py -v`
Expected: FAIL — the old `sync_clickup_entries` uses `user_data["clickup_synced_entries"]`/`user_data["work_sessions"]` and will raise or behave wrong against the new store.

- [ ] **Step 4: Replace `sync_clickup_entries`**

Replace the whole method (`data_manager.py:828-906`) with:

```python
    async def sync_clickup_entries(self, user_id: str, start_date: datetime, end_date: datetime) -> Dict[str, Any]:
        """Синхронизация записей ClickUp с данными пользователя"""
        clickup_client = self.get_user_clickup_client(user_id)
        if not clickup_client:
            return {"success": False, "error": "ClickUp не настроен для этого пользователя"}

        rate = self.get_rate(user_id)
        list_name_cache: Dict[str, str] = {}

        try:
            clickup_entries = await clickup_client.get_time_entries(start_date, end_date)

            if not clickup_entries:
                return {"success": True, "synced_count": 0, "message": "Записи не найдены"}

            synced_count = 0
            total_hours = 0
            total_earnings = 0

            for entry in clickup_entries:
                entry_id = entry.get('id')
                duration_ms = int(entry.get('duration', 0))

                if duration_ms < 0:
                    continue

                # Дедуп на уровне БД: сессию создаём только если запись новая
                if not self.try_mark_synced(user_id, entry_id):
                    continue

                duration_hours = duration_ms / (1000 * 60 * 60)
                earnings = duration_hours * rate

                start_timestamp = int(entry.get('start', 0)) / 1000
                entry_date = datetime.fromtimestamp(start_timestamp).strftime("%Y-%m-%d")

                project_name = await self._resolve_list_name(
                    clickup_client, self._entry_list_id(entry), list_name_cache
                )

                clickup_session = {
                    "hours": int(duration_hours),
                    "minutes": int((duration_hours % 1) * 60),
                    "earnings": earnings,
                    "timestamp": datetime.fromtimestamp(start_timestamp).isoformat(),
                    "source": "clickup",
                    "clickup_id": entry_id,
                    "task_name": entry.get('task', {}).get('name', 'Неизвестная задача') if entry.get('task') else 'Без задачи',
                    "project_name": project_name,
                    "description": entry.get('description', ''),
                }

                self.add_session(user_id, entry_date, clickup_session)

                synced_count += 1
                total_hours += duration_hours
                total_earnings += earnings

            return {
                "success": True,
                "synced_count": synced_count,
                "total_hours": total_hours,
                "total_earnings": total_earnings,
            }

        except Exception as e:
            return {"success": False, "error": str(e)}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_sync.py -v`
Expected: PASS (2 passed).

- [ ] **Step 6: Commit**

```bash
git add data_manager.py tests/test_sync.py requirements.txt pytest.ini
git commit -m "feat: sync via atomic add_session + DB-level dedup"
```

---

### Task 6: Adapt report generators and analytics to `get_work_sessions`

The report/analytics helpers currently take a `user_data` dict and read `user_data["work_sessions"]`. Change them to take a `work_sessions` dict directly; callers will pass `dm.get_work_sessions(user_id)`. `get_tasks_summary` and the breakdown helpers take `user_id` and fetch internally.

**Files:**
- Modify: `data_manager.py` (report generators + `get_tasks_summary` + `get_days_breakdown`/`get_weeks_breakdown`/`get_months_breakdown`)
- Test: `tests/test_reports.py`

**Interfaces:**
- Produces (changed signatures):
  - `generate_today_report(work_sessions: dict) -> str`
  - `generate_yesterday_report(work_sessions: dict) -> str`
  - `generate_week_report(work_sessions: dict) -> str`
  - `generate_month_report(work_sessions: dict) -> str`
  - `generate_week_details_report(work_sessions: dict) -> str`
  - `generate_month_weeks_report(work_sessions: dict) -> str`
  - `generate_prev_month_weeks_report(work_sessions: dict) -> str`
  - `generate_year_report(work_sessions: dict) -> str`
  - `get_tasks_summary(user_id: str, start_date, end_date) -> dict` (unchanged signature; internal source changes)
  - `get_days_breakdown / get_weeks_breakdown / get_months_breakdown(user_id, start, end) -> list` (unchanged signatures; internal source changes)

- [ ] **Step 1: Write the failing test**

Create `tests/test_reports.py`:

```python
from datetime import datetime

from cryptography.fernet import Fernet


def _dm(tmp_path, monkeypatch):
    monkeypatch.setenv("ENCRYPTION_KEY", Fernet.generate_key().decode())
    from data_manager import DataManager
    return DataManager(str(tmp_path / "salary.db"))


def test_today_report_from_work_sessions(tmp_path, monkeypatch):
    dm = _dm(tmp_path, monkeypatch)
    today = datetime.now().strftime("%Y-%m-%d")
    dm.add_session("42", today, {
        "hours": 2, "minutes": 0, "earnings": 1000.0, "clickup_id": "e1",
        "task_name": "T", "project_name": "P", "timestamp": today + "T10:00:00",
    })
    text = dm.generate_today_report(dm.get_work_sessions("42"))
    assert "1000.00 руб" in text


def test_tasks_summary_groups_by_task(tmp_path, monkeypatch):
    dm = _dm(tmp_path, monkeypatch)
    day = datetime(2026, 7, 4)
    dm.add_session("42", "2026-07-04", {
        "hours": 1, "minutes": 0, "earnings": 500.0, "source": "clickup",
        "clickup_id": "e1", "task_name": "Задача А", "timestamp": "2026-07-04T10:00:00",
    })
    summary = dm.get_tasks_summary("42", day.replace(hour=0), day.replace(hour=23, minute=59))
    assert summary["total_tasks"] == 1
    assert "Задача А" in summary["tasks"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_reports.py -v`
Expected: FAIL — generators still expect `user_data` and index `["work_sessions"]`.

- [ ] **Step 3: Rename the parameter in the 8 report generators**

In each of `generate_today_report`, `generate_yesterday_report`, `generate_week_report`, `generate_month_report`, `generate_week_details_report`, `generate_month_weeks_report`, `generate_prev_month_weeks_report`, `generate_year_report`:
- Change the signature `def generate_x(self, user_data: Dict[str, Any]) -> str:` to `def generate_x(self, work_sessions: Dict[str, Any]) -> str:`.
- Replace every occurrence of `user_data["work_sessions"]` inside these methods with `work_sessions`.

There are no other uses of `user_data` inside these eight methods, so no further edits are needed within them.

- [ ] **Step 4: Update `get_tasks_summary` to fetch internally**

In `get_tasks_summary` (currently `data_manager.py:539-580`), replace:

```python
        user_data = self.get_user_data(user_id)

        all_sessions = []
        current_date = start_date

        while current_date <= end_date:
            date_str = current_date.strftime("%Y-%m-%d")
            if date_str in user_data["work_sessions"]:
                day_sessions = user_data["work_sessions"][date_str]["sessions"]
```

with:

```python
        work_sessions = self.get_work_sessions(user_id)

        all_sessions = []
        current_date = start_date

        while current_date <= end_date:
            date_str = current_date.strftime("%Y-%m-%d")
            if date_str in work_sessions:
                day_sessions = work_sessions[date_str]["sessions"]
```

- [ ] **Step 5: Update the three breakdown helpers**

In `get_days_breakdown`, `get_weeks_breakdown`, `get_months_breakdown` (currently `data_manager.py:582-684`), replace the line `user_data = self.get_user_data(user_id)` with `work_sessions = self.get_work_sessions(user_id)`, and replace every `user_data["work_sessions"]` in those three methods with `work_sessions`.

- [ ] **Step 6: Run test to verify it passes**

Run: `pytest tests/test_reports.py -v`
Expected: PASS (2 passed).

- [ ] **Step 7: Run the full suite**

Run: `pytest -v`
Expected: all tests pass (the old `tests/test_data_manager.py` will be replaced in Task 9; if it still references the JSON API it will fail — that is expected and fixed in Task 9. For now run `pytest --ignore=tests/test_data_manager.py -v` and confirm green.)

- [ ] **Step 8: Commit**

```bash
git add data_manager.py tests/test_reports.py
git commit -m "feat: reports and analytics read from SQLite via get_work_sessions"
```

---

### Task 7: Migration script with verification

**Files:**
- Create: `migrate_to_sqlite.py`
- Test: `tests/test_migration.py`

**Interfaces:**
- Consumes: `db.get_connection`, `db.init_schema`, `crypto.encrypt`.
- Produces:
  - `migrate(json_path="salary_data.json", db_path="salary.db") -> bool` — returns `True` if it migrated, `False` if it was a no-op (db already exists, or no JSON). Raises `ValueError` on verification mismatch (leaving JSON intact, removing the partial `.tmp`).
  - CLI: `python migrate_to_sqlite.py` runs `migrate()` and prints the result.

- [ ] **Step 1: Write the failing test**

Create `tests/test_migration.py`:

```python
import json
import os

import pytest
from cryptography.fernet import Fernet


@pytest.fixture(autouse=True)
def _key(monkeypatch):
    monkeypatch.setenv("ENCRYPTION_KEY", Fernet.generate_key().decode())


def _write_json(path):
    data = {
        "42": {
            "rate": 500.0,
            "work_sessions": {
                "2026-07-04": {
                    "total_hours": 1.5, "total_earnings": 750.0,
                    "sessions": [{
                        "hours": 1, "minutes": 30, "earnings": 750.0,
                        "timestamp": "2026-07-04T10:00:00", "source": "clickup",
                        "clickup_id": "e1", "task_name": "T",
                        "project_name": "P", "description": "",
                        "date": "2026-07-04",
                    }],
                }
            },
            "clickup_synced_entries": ["e1"],
            "clickup_settings": {
                "api_token": "pk_SECRET", "workspace_id": "ws1",
                "team_id": "t1", "user_id": "u1", "username": "vasya",
            },
        }
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)


def test_migrate_transfers_and_archives(tmp_path):
    import migrate_to_sqlite
    from data_manager import DataManager

    json_path = str(tmp_path / "salary_data.json")
    db_path = str(tmp_path / "salary.db")
    _write_json(json_path)

    assert migrate_to_sqlite.migrate(json_path, db_path) is True
    assert not os.path.exists(json_path)                      # archived away
    assert any(p.name.startswith("salary_data.json.migrated-") for p in tmp_path.iterdir())

    dm = DataManager(db_path)
    assert dm.get_rate("42") == 500.0
    assert dm.get_clickup_settings("42")["api_token"] == "pk_SECRET"  # decrypts
    assert dm.is_entry_synced("42", "e1") is True
    ws = dm.get_work_sessions("42")
    assert abs(ws["2026-07-04"]["total_earnings"] - 750.0) < 1e-6


def test_migrate_is_noop_when_db_exists(tmp_path):
    import migrate_to_sqlite
    json_path = str(tmp_path / "salary_data.json")
    db_path = str(tmp_path / "salary.db")
    _write_json(json_path)
    open(db_path, "w").close()                                # db already present
    assert migrate_to_sqlite.migrate(json_path, db_path) is False
    assert os.path.exists(json_path)                          # untouched


def test_verification_failure_keeps_json(tmp_path, monkeypatch):
    import migrate_to_sqlite
    json_path = str(tmp_path / "salary_data.json")
    db_path = str(tmp_path / "salary.db")
    _write_json(json_path)

    # Force a mismatch by corrupting insertion (monkeypatch _insert_session to skip)
    monkeypatch.setattr(migrate_to_sqlite, "_insert_sessions",
                        lambda conn, uid, ws: None)
    with pytest.raises(ValueError):
        migrate_to_sqlite.migrate(json_path, db_path)
    assert os.path.exists(json_path)                          # left intact
    assert not os.path.exists(db_path)                        # partial db removed
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_migration.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'migrate_to_sqlite'`.

- [ ] **Step 3: Implement `migrate_to_sqlite.py`**

```python
import json
import logging
import os
from datetime import datetime

import crypto
import db

logger = logging.getLogger(__name__)

DATA_FILE = "salary_data.json"
DB_FILE = "salary.db"


def _insert_user(conn, user_id, user):
    token = user.get("clickup_settings", {}).get("api_token")
    settings = user.get("clickup_settings", {})
    conn.execute(
        "INSERT INTO users (user_id, rate, clickup_api_token, clickup_workspace_id, "
        "clickup_team_id, clickup_user_id, clickup_username) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            user_id,
            float(user.get("rate", 0) or 0),
            crypto.encrypt(token) if token else None,
            settings.get("workspace_id"),
            settings.get("team_id"),
            settings.get("user_id"),
            settings.get("username"),
        ),
    )


def _insert_sessions(conn, user_id, work_sessions):
    for date, day in work_sessions.items():
        for s in day.get("sessions", []):
            conn.execute(
                "INSERT INTO work_sessions (user_id, date, hours, minutes, earnings, "
                "timestamp, source, clickup_id, task_name, project_name, description) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    user_id,
                    date,                                  # outer date is authoritative
                    int(s.get("hours", 0)),
                    int(s.get("minutes", 0)),
                    float(s.get("earnings", 0)),
                    s.get("timestamp"),
                    s.get("source", "clickup"),
                    s.get("clickup_id"),
                    s.get("task_name"),
                    s.get("project_name"),
                    s.get("description", ""),
                ),
            )


def _insert_synced(conn, user_id, entries):
    for entry_id in entries:
        conn.execute(
            "INSERT OR IGNORE INTO synced_entries (user_id, entry_id) VALUES (?, ?)",
            (user_id, entry_id),
        )


def _expected_totals(data):
    """Пер-user контрольные суммы из JSON."""
    totals = {}
    for user_id, user in data.items():
        hours = earnings = sessions = 0
        for day in user.get("work_sessions", {}).values():
            for s in day.get("sessions", []):
                hours += int(s.get("hours", 0)) + int(s.get("minutes", 0)) / 60
                earnings += float(s.get("earnings", 0))
                sessions += 1
        totals[user_id] = {
            "hours": hours,
            "earnings": earnings,
            "sessions": sessions,
            "synced": len(user.get("clickup_synced_entries", []) or []),
        }
    return totals


def _verify(conn, data):
    for user_id, expected in _expected_totals(data).items():
        row = conn.execute(
            "SELECT COALESCE(SUM(hours + minutes / 60.0), 0) AS hours, "
            "COALESCE(SUM(earnings), 0) AS earnings, COUNT(*) AS sessions "
            "FROM work_sessions WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        synced = conn.execute(
            "SELECT COUNT(*) FROM synced_entries WHERE user_id = ?", (user_id,)
        ).fetchone()[0]

        if abs(row["hours"] - expected["hours"]) > 1e-6:
            raise ValueError(f"hours mismatch for {user_id}: {row['hours']} != {expected['hours']}")
        if abs(row["earnings"] - expected["earnings"]) > 1e-6:
            raise ValueError(f"earnings mismatch for {user_id}: {row['earnings']} != {expected['earnings']}")
        if row["sessions"] != expected["sessions"]:
            raise ValueError(f"session count mismatch for {user_id}: {row['sessions']} != {expected['sessions']}")
        if synced != expected["synced"]:
            raise ValueError(f"synced count mismatch for {user_id}: {synced} != {expected['synced']}")


def migrate(json_path: str = DATA_FILE, db_path: str = DB_FILE) -> bool:
    if os.path.exists(db_path):
        return False
    if not os.path.exists(json_path):
        return False

    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    tmp_path = f"{db_path}.tmp"
    if os.path.exists(tmp_path):
        os.remove(tmp_path)

    conn = db.get_connection(tmp_path)
    try:
        for user_id, user in data.items():
            _insert_user(conn, user_id, user)
            _insert_sessions(conn, user_id, user.get("work_sessions", {}))
            _insert_synced(conn, user_id, user.get("clickup_synced_entries", []) or [])
        conn.commit()
        _verify(conn, data)
    except Exception:
        conn.close()
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise
    conn.close()

    os.replace(tmp_path, db_path)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    os.replace(json_path, f"{json_path}.migrated-{ts}")
    logger.info("Migrated %s -> %s", json_path, db_path)
    return True


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    result = migrate()
    print("migrated" if result else "no-op (db exists or no json)")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_migration.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add migrate_to_sqlite.py tests/test_migration.py
git commit -m "feat: verified JSON->SQLite migration script"
```

---

### Task 8: Wire migration + new methods into `api.py`

**Files:**
- Modify: `api.py`

**Interfaces:**
- Consumes: `migrate_to_sqlite.migrate`, `DataManager` new methods, `get_work_sessions`.

- [ ] **Step 1: Call migration before constructing DataManager**

At `api.py:19-32`, the module imports `DataManager` and does `data_manager = DataManager()`. Replace the construction line `data_manager = DataManager()` with:

```python
import migrate_to_sqlite

migrate_to_sqlite.migrate()
data_manager = DataManager()
```

(Place the `import migrate_to_sqlite` with the other top-level imports near `from data_manager import DataManager`.)

- [ ] **Step 2: Replace rate read/writes**

- `api.py:185-187`:

```python
    user_data = data_manager.get_user_data(user_id)
    user_data["rate"] = body.rate
    data_manager.save_data()
```

becomes:

```python
    data_manager.set_rate(user_id, body.rate)
```

- [ ] **Step 3: Replace clickup settings reads**

- `api.py:165-166` and `api.py:415-416`: replace `user_data = data_manager.get_user_data(user_id)` + `clickup = user_data.get("clickup_settings", {})` (and the `clickup_settings = user_data.get("clickup_settings", {})` variant) with a single:

```python
    clickup = data_manager.get_clickup_settings(user_id)
```

Update the local variable name used by the following lines accordingly (`clickup` or `clickup_settings`) so the `.get(...)` calls still resolve. The values are identical keys (`api_token`, `workspace_id`, `team_id`, `user_id`, `username`).

- [ ] **Step 4: Replace `synced_count` computation**

- `api.py:452`: `"synced_count": len(user_data.get("clickup_synced_entries", set())),` becomes:

```python
        "synced_count": data_manager.conn.execute(
            "SELECT COUNT(*) FROM synced_entries WHERE user_id = ?", (user_id,)
        ).fetchone()[0],
```

- [ ] **Step 5: Replace clickup settings writes**

- `api.py:463-469`:

```python
    user_data = data_manager.get_user_data(user_id)
    user_data["clickup_settings"]["api_token"] = body.api_token
    user_data["clickup_settings"]["workspace_id"] = body.workspace_id
    user_data["clickup_settings"]["team_id"] = result["team_id"]
    user_data["clickup_settings"]["user_id"] = result["user_id"]
    user_data["clickup_settings"]["username"] = result["username"]
    data_manager.save_data()
```

becomes:

```python
    data_manager.set_clickup_settings(
        user_id,
        api_token=body.api_token,
        workspace_id=body.workspace_id,
        team_id=result["team_id"],
        user_id=result["user_id"],
        username=result["username"],
    )
```

- `api.py:480-488` (disconnect handler that resets settings) — replace the `user_data = get_user_data`/`user_data["clickup_settings"] = {...}`/`save_data()` block with:

```python
    data_manager.clear_clickup_settings(user_id)
```

- [ ] **Step 6: Replace `work_sessions` reads in analytics endpoints**

For every endpoint that does `user_data = data_manager.get_user_data(user_id)` and then reads `user_data["work_sessions"]` (`api.py:177,197,214,227,252,255,268,271,284,291,319,326,333,362,369,376,380`), replace the `user_data = data_manager.get_user_data(user_id)` line with:

```python
    work_sessions = data_manager.get_work_sessions(user_id)
```

and replace each `user_data["work_sessions"]` in that endpoint body with `work_sessions`.

For endpoints at `api.py:542-543` that read `user_data.get("clickup_settings", {}).get("user_id")`, replace with:

```python
    assignee_id = data_manager.get_clickup_settings(user_id).get("user_id")
```

- [ ] **Step 7: Smoke-test import**

Run: `python -c "import api"`
Expected: no exception (module imports cleanly). If `ENCRYPTION_KEY` is unset locally, this will raise the crypto RuntimeError — set a throwaway key first: `ENCRYPTION_KEY=$(python crypto.py genkey) python -c "import api"`.

- [ ] **Step 8: Commit**

```bash
git add api.py
git commit -m "feat: wire api.py to SQLite DataManager and startup migration"
```

---

### Task 9: Wire `main.py`, replace legacy DataManager test

**Files:**
- Modify: `main.py`
- Modify: `tests/test_data_manager.py` (replace JSON round-trip tests with SQLite equivalents)

**Interfaces:**
- Consumes: `DataManager` new methods.

- [ ] **Step 0: Run the migration on startup**

`main.py` is also a standalone entrypoint (`python main.py`), so it must trigger the migration too. In `SalaryBot.__init__` (`main.py:40`), immediately before `self.data_manager = DataManager()`, add:

```python
        import migrate_to_sqlite
        migrate_to_sqlite.migrate()
```

(`migrate()` is idempotent — when `api.py` already migrated, this is a no-op.)

- [ ] **Step 1: Replace rate reads in main.py**

- `main.py:457,484-485`: replace `user_data = self.data_manager.get_user_data(user_id)` then `user_data["rate"]` usage. Where only the rate is needed, use `rate = self.data_manager.get_rate(user_id)` and reference `rate`.
- `main.py:555-557`:

```python
                user_data = self.data_manager.get_user_data(user_id)
                user_data["rate"] = rate
                self.data_manager.save_data()
```

becomes:

```python
                self.data_manager.set_rate(user_id, rate)
```

- Every `if user_data["rate"] <= 0:` / `> 0` guard (`main.py:713,772,807,1692,1709,1726,1743,1760,1777`): replace the preceding `user_data = self.data_manager.get_user_data(user_id)` with `rate = self.data_manager.get_rate(user_id)` and change the guard to `if rate <= 0:` / `if rate > 0:`.

- [ ] **Step 2: Replace clickup token/setting writes in main.py**

- `main.py:598-600`:

```python
            user_data = self.data_manager.get_user_data(user_id)
            user_data["clickup_settings"]["api_token"] = token
            self.data_manager.save_data()
```

becomes:

```python
            self.data_manager.set_clickup_settings(user_id, api_token=token)
```

- `main.py:622-638` (workspace validation flow): replace the read `user_data = get_user_data` + `api_token = user_data["clickup_settings"].get("api_token")` with `api_token = self.data_manager.get_clickup_settings(user_id).get("api_token")`; and the success-branch block that sets `workspace_id/team_id/user_id/username` + `save_data()` with:

```python
                self.data_manager.set_clickup_settings(
                    user_id,
                    workspace_id=workspace_id,
                    team_id=validation_result["team_id"],
                    user_id=validation_result["user_id"],
                    username=validation_result["username"],
                )
```

- `main.py:657-666` (reset settings): replace the `user_data["clickup_settings"] = {...}` + `save_data()` block with `self.data_manager.clear_clickup_settings(user_id)`.
- `main.py:693-696`: replace with `self.data_manager.set_clickup_settings(user_id, user_id=current_user.get('id'), username=current_user.get('username', current_user.get('email', 'Unknown')))`, and for the following message line that reads `user_data['clickup_settings']['username']`, read it back via `self.data_manager.get_clickup_settings(user_id)["username"]`.

- [ ] **Step 3: Replace clickup settings reads in main.py**

- `main.py:864-866`: replace `user_data = get_user_data` + `user_data["clickup_settings"].get(...)` with:

```python
            clickup_settings = self.data_manager.get_clickup_settings(user_id)
            clickup_username = clickup_settings.get("username", "Неизвестно")
            clickup_user_id = clickup_settings.get("user_id")
```

- `main.py:888`: `synced_count = len(user_data.get("clickup_synced_entries", set()))` becomes:

```python
            synced_count = self.data_manager.conn.execute(
                "SELECT COUNT(*) FROM synced_entries WHERE user_id = ?", (user_id,)
            ).fetchone()[0]
```

- [ ] **Step 4: Replace report-generator calls in main.py**

Every call of the form `user_data = self.data_manager.get_user_data(user_id)` followed by `content = self.data_manager.generate_X_report(user_data)` (`main.py:899-949` and `main.py:1609-1680`) becomes a single line passing work_sessions:

```python
            content = self.data_manager.generate_X_report(
                self.data_manager.get_work_sessions(user_id))
```

(Replace `X` with the matching report name for each site: `today`, `yesterday`, `week`, `week_details`, `month`, `month_weeks`, `prev_month_weeks`, `year`.)

- [ ] **Step 5: Verify no stale references remain**

Run: `grep -n "get_user_data\|save_data\|work_sessions\[\|clickup_synced_entries\|\[\"clickup_settings\"\]\|\['clickup_settings'\]" main.py api.py`
Expected: no matches (all call sites migrated).

- [ ] **Step 6: Replace the legacy DataManager test**

Overwrite `tests/test_data_manager.py` with SQLite-based equivalents:

```python
from cryptography.fernet import Fernet


def _dm(tmp_path, monkeypatch):
    monkeypatch.setenv("ENCRYPTION_KEY", Fernet.generate_key().decode())
    from data_manager import DataManager
    return DataManager(str(tmp_path / "salary.db"))


def test_rate_round_trip(tmp_path, monkeypatch):
    dm = _dm(tmp_path, monkeypatch)
    dm.set_rate("42", 500.0)
    dm2_path = dm.db_path
    from data_manager import DataManager
    reopened = DataManager(dm2_path)
    assert reopened.get_rate("42") == 500.0


def test_synced_entries_persist(tmp_path, monkeypatch):
    dm = _dm(tmp_path, monkeypatch)
    dm.try_mark_synced("42", "entry-1")
    from data_manager import DataManager
    reopened = DataManager(dm.db_path)
    assert reopened.is_entry_synced("42", "entry-1") is True
```

- [ ] **Step 7: Run the full suite**

Run: `pytest -v`
Expected: all tests pass.

- [ ] **Step 8: Smoke-test both entrypoints import**

Run: `ENCRYPTION_KEY=$(python crypto.py genkey) python -c "import main, api"`
Expected: no exception.

- [ ] **Step 9: Commit**

```bash
git add main.py tests/test_data_manager.py
git commit -m "feat: wire main.py to SQLite DataManager; update tests"
```

---

### Task 10: Manual end-to-end verification against real data

**Files:** none (operational check)

- [ ] **Step 1: Generate and set an encryption key**

Run: `python crypto.py genkey`, then add the printed value to `.env` as `ENCRYPTION_KEY=...`.

- [ ] **Step 2: Back up the live JSON**

Run: `cp salary_data.json salary_data.pre-sqlite.json`
(Keep this outside git — it is already gitignored.)

- [ ] **Step 3: Run the migration manually and read the output**

Run: `python migrate_to_sqlite.py`
Expected: prints `migrated`. A `salary.db` appears and `salary_data.json` becomes `salary_data.json.migrated-<ts>`.
If it raises a `ValueError` (verification mismatch), the JSON is untouched and no `salary.db` is produced — capture the message and stop; do not proceed.

- [ ] **Step 4: Spot-check totals match**

Pick one user id present in the backup and compare a report. Run:

```bash
ENCRYPTION_KEY=$(grep ENCRYPTION_KEY .env | cut -d= -f2) python -c "
from data_manager import DataManager
dm = DataManager()
uid = 'REPLACE_WITH_REAL_USER_ID'
ws = dm.get_work_sessions(uid)
print('days:', len(ws))
print('total earnings:', sum(d['total_earnings'] for d in ws.values()))
print('token decrypts:', bool(dm.get_clickup_settings(uid)['api_token']))
"
```

Expected: day count and total earnings match the pre-migration data; token decrypts to a truthy value for a user who had ClickUp configured.

- [ ] **Step 5: Confirm idempotency**

Run: `python migrate_to_sqlite.py`
Expected: prints `no-op (db exists or no json)`. The existing `salary.db` is untouched.

---

## Post-implementation notes (out of scope for this plan)

- `salary_data.json` is tracked in git history despite `.gitignore` (git status showed it as modified). After migration, run `git rm --cached salary_data.json` to stop tracking it. Scrubbing historical commits (real tokens/earnings already committed) and rotating the ClickUp tokens is a **separate task** — flag to the user.
