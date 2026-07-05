import sqlite3

import db

NOTIFY_COLUMNS = {
    "monthly_goal",
    "monthly_hours_norm",
    "notify_daily_digest",
    "digest_time",
    "notify_weekly",
    "notify_long_timer",
    "long_timer_hours",
    "autosync_enabled",
}

OLD_USERS_SCHEMA = """
CREATE TABLE users (
    user_id              TEXT PRIMARY KEY,
    rate                 REAL NOT NULL DEFAULT 0,
    clickup_api_token    TEXT,
    clickup_workspace_id TEXT,
    clickup_team_id      TEXT,
    clickup_user_id      TEXT,
    clickup_username     TEXT
);
"""


def _user_columns(conn):
    return {r["name"] for r in conn.execute("PRAGMA table_info(users)")}


def test_fresh_db_has_new_tables_and_columns(tmp_path):
    conn = db.get_connection(str(tmp_path / "t.db"))
    names = {r["name"] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"notification_log", "bonuses"} <= names
    assert NOTIFY_COLUMNS <= _user_columns(conn)


def test_ensure_columns_upgrades_old_schema(tmp_path):
    path = str(tmp_path / "t.db")
    raw = sqlite3.connect(path)
    raw.executescript(OLD_USERS_SCHEMA)
    raw.execute("INSERT INTO users (user_id, rate) VALUES ('42', 100)")
    raw.commit()
    raw.close()

    conn = db.get_connection(path)
    assert NOTIFY_COLUMNS <= _user_columns(conn)
    row = conn.execute("SELECT * FROM users WHERE user_id='42'").fetchone()
    assert row["rate"] == 100
    assert row["monthly_goal"] == 0
    assert row["digest_time"] == "21:00"
    assert row["notify_daily_digest"] == 0
    assert row["notify_long_timer"] == 1
    assert row["long_timer_hours"] == 4
    assert row["autosync_enabled"] == 1


def test_ensure_columns_idempotent(tmp_path):
    path = str(tmp_path / "t.db")
    db.get_connection(path)
    conn2 = db.get_connection(path)
    assert NOTIFY_COLUMNS <= _user_columns(conn2)
    assert conn2.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0
