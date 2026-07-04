import json
import os

import pytest
from cryptography.fernet import Fernet


@pytest.fixture(autouse=True)
def _key(monkeypatch):
    monkeypatch.setenv("ENCRYPTION_KEY", Fernet.generate_key().decode())


def _write_json(path):
    # Session hours/minutes are TRUNCATED (1h29m) but the day total is the
    # precise 1.5h — mirrors the real data's lost-seconds drift.
    data = {
        "42": {
            "rate": 500.0,
            "work_sessions": {
                "2026-07-04": {
                    "total_hours": 1.5, "total_earnings": 750.0,
                    "sessions": [{
                        "hours": 1, "minutes": 29, "earnings": 750.0,
                        "timestamp": "2026-07-04T10:00:00", "source": "clickup",
                        "clickup_id": "e1", "task_name": "T",
                        "project_name": "P", "description": "", "date": "2026-07-04",
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


def test_migrate_backfills_and_archives(tmp_path):
    import migrate_to_sqlite
    from data_manager import DataManager

    json_path = str(tmp_path / "salary_data.json")
    db_path = str(tmp_path / "salary.db")
    _write_json(json_path)

    assert migrate_to_sqlite.migrate(json_path, db_path) is True
    assert not os.path.exists(json_path)                     # archived away
    assert any(p.name.startswith("salary_data.json.migrated-") for p in tmp_path.iterdir())

    dm = DataManager(db_path)
    assert dm.get_rate("42") == 500.0
    assert dm.get_clickup_settings("42")["api_token"] == "pk_SECRET"
    assert dm.is_entry_synced("42", "e1") is True
    ws = dm.get_work_sessions("42")
    # Backfill restores the precise 1.5h day total, NOT the truncated 1h29m.
    assert abs(ws["2026-07-04"]["total_hours"] - 1.5) < 1e-3
    assert abs(ws["2026-07-04"]["total_earnings"] - 750.0) < 1e-6


def test_migrate_is_noop_when_db_exists(tmp_path):
    import migrate_to_sqlite
    json_path = str(tmp_path / "salary_data.json")
    db_path = str(tmp_path / "salary.db")
    _write_json(json_path)
    open(db_path, "w").close()
    assert migrate_to_sqlite.migrate(json_path, db_path) is False
    assert os.path.exists(json_path)                         # untouched


def test_verification_failure_keeps_json(tmp_path, monkeypatch):
    import migrate_to_sqlite
    json_path = str(tmp_path / "salary_data.json")
    db_path = str(tmp_path / "salary.db")
    _write_json(json_path)

    monkeypatch.setattr(migrate_to_sqlite, "_insert_sessions",
                        lambda conn, uid, ws: None)          # force a mismatch
    with pytest.raises(ValueError):
        migrate_to_sqlite.migrate(json_path, db_path)
    assert os.path.exists(json_path)                         # left intact
    assert not os.path.exists(db_path)                       # partial db removed
