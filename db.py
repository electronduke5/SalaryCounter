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

CREATE TABLE IF NOT EXISTS bonuses (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    TEXT NOT NULL REFERENCES users(user_id),
    date       TEXT NOT NULL,
    amount     REAL NOT NULL,
    comment    TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_bonuses_user_date ON bonuses(user_id, date);

CREATE TABLE IF NOT EXISTS notification_log (
    user_id  TEXT NOT NULL,
    kind     TEXT NOT NULL,
    ref      TEXT NOT NULL,
    sent_at  TEXT NOT NULL,
    PRIMARY KEY (user_id, kind, ref)
);
"""

# Колонки users, появившиеся после первичного релиза SQLite-схемы:
# существующие базы обновляются через _ensure_columns (ALTER TABLE).
_USERS_EXTRA_COLUMNS = [
    ("monthly_goal", "REAL NOT NULL DEFAULT 0"),
    ("monthly_hours_norm", "REAL NOT NULL DEFAULT 0"),
    ("notify_daily_digest", "INTEGER NOT NULL DEFAULT 0"),
    ("digest_time", "TEXT NOT NULL DEFAULT '21:00'"),
    ("notify_weekly", "INTEGER NOT NULL DEFAULT 0"),
    ("notify_long_timer", "INTEGER NOT NULL DEFAULT 1"),
    ("long_timer_hours", "REAL NOT NULL DEFAULT 4"),
    ("autosync_enabled", "INTEGER NOT NULL DEFAULT 1"),
]


def _ensure_columns(conn: sqlite3.Connection) -> None:
    existing = {r[1] for r in conn.execute("PRAGMA table_info(users)")}
    for name, ddl in _USERS_EXTRA_COLUMNS:
        if name not in existing:
            conn.execute(f"ALTER TABLE users ADD COLUMN {name} {ddl}")


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(_SCHEMA)
    _ensure_columns(conn)


def get_connection(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, isolation_level=None, check_same_thread=False)   # autocommit
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    init_schema(conn)
    return conn
