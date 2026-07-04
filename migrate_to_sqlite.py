import glob
import json
import logging
import os
from datetime import datetime

import crypto
import db

logger = logging.getLogger(__name__)

DATA_FILE = "salary_data.json"
DB_FILE = "salary.db"
MS_PER_HOUR = 3_600_000


def _insert_user(conn, user_id, user):
    settings = user.get("clickup_settings", {}) or {}
    token = settings.get("api_token")
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


def _session_base_ms(s):
    return (int(s.get("hours", 0)) * 60 + int(s.get("minutes", 0))) * 60 * 1000


def _insert_sessions(conn, user_id, work_sessions):
    """Вставляет сессии, восстанавливая точный дневной тотал (бэкфилл секунд)."""
    for date, day in work_sessions.items():
        sessions = day.get("sessions", [])
        if not sessions:
            continue
        base = [_session_base_ms(s) for s in sessions]
        total_hours = day.get("total_hours")
        if total_hours is not None:
            target_ms = round(float(total_hours) * MS_PER_HOUR)
            base[-1] += target_ms - sum(base)          # недостачу — в последнюю сессию дня
        for s, ms in zip(sessions, base):
            conn.execute(
                "INSERT INTO work_sessions (user_id, date, duration_ms, earnings, "
                "timestamp, source, clickup_id, task_name, project_name, description) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    user_id,
                    date,                              # внешний date — источник истины
                    int(ms),
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


def _expected(data):
    totals = {}
    for user_id, user in data.items():
        earnings = hours = sessions = 0
        for day in user.get("work_sessions", {}).values():
            day_sessions = day.get("sessions", [])
            for s in day_sessions:
                earnings += float(s.get("earnings", 0))
                sessions += 1
            if day_sessions:
                th = day.get("total_hours")
                hours += float(th) if th is not None else sum(
                    _session_base_ms(s) for s in day_sessions) / MS_PER_HOUR
        totals[user_id] = {
            "earnings": earnings,
            "hours": hours,
            "sessions": sessions,
            "synced": len(user.get("clickup_synced_entries", []) or []),
        }
    return totals


def _verify(conn, data):
    for user_id, expected in _expected(data).items():
        row = conn.execute(
            "SELECT COALESCE(SUM(duration_ms), 0) AS ms, "
            "COALESCE(SUM(earnings), 0) AS earnings, COUNT(*) AS sessions "
            "FROM work_sessions WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        synced = conn.execute(
            "SELECT COUNT(*) FROM synced_entries WHERE user_id = ?", (user_id,)
        ).fetchone()[0]
        hours = row["ms"] / MS_PER_HOUR

        if abs(row["earnings"] - expected["earnings"]) > 1e-6:
            raise ValueError(f"earnings mismatch for {user_id}: {row['earnings']} != {expected['earnings']}")
        if abs(hours - expected["hours"]) > 1e-3:
            raise ValueError(f"hours mismatch for {user_id}: {hours} != {expected['hours']}")
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

    tmp_path = f"{db_path}.{os.getpid()}.tmp"                # уникальный tmp на процесс
    if os.path.exists(tmp_path):
        os.remove(tmp_path)

    conn = db.get_connection(tmp_path)
    try:
        for user_id, user in data.items():
            _insert_user(conn, user_id, user)
            _insert_sessions(conn, user_id, user.get("work_sessions", {}))
            _insert_synced(conn, user_id, user.get("clickup_synced_entries", []) or [])
        _verify(conn, data)
    except Exception:
        conn.close()
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise
    conn.close()

    if os.path.exists(db_path):                              # проиграли гонку другому процессу
        os.remove(tmp_path)
        return False
    os.replace(tmp_path, db_path)                            # атомарно вводим БД
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    try:
        os.replace(json_path, f"{json_path}.migrated-{ts}")
    except FileNotFoundError:
        pass                                                 # другой процесс уже архивировал
    logger.info("Migrated %s -> %s", json_path, db_path)
    return True


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("migrated" if migrate() else "no-op (db exists or no json)")
