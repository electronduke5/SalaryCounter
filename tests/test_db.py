import db


def test_schema_creates_tables(tmp_path):
    conn = db.get_connection(str(tmp_path / "t.db"))
    names = {r["name"] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"users", "work_sessions", "synced_entries"} <= names


def test_work_sessions_has_duration_ms(tmp_path):
    conn = db.get_connection(str(tmp_path / "t.db"))
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(work_sessions)")}
    assert "duration_ms" in cols
    assert "hours" not in cols and "minutes" not in cols


def test_pragmas_applied(tmp_path):
    conn = db.get_connection(str(tmp_path / "t.db"))
    assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert conn.isolation_level is None


def test_init_schema_is_idempotent(tmp_path):
    path = str(tmp_path / "t.db")
    db.get_connection(path)
    conn2 = db.get_connection(path)
    assert conn2.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0
