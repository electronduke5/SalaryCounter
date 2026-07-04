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
    duration_ms  INTEGER NOT NULL DEFAULT 0,
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


def get_connection(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, isolation_level=None)   # autocommit
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    init_schema(conn)
    return conn
