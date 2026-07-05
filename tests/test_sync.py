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
        "id": "e1", "duration": str(1000 * 60 * 90),        # 1.5h in ms
        "start": str(int(datetime(2026, 7, 4, 10).timestamp() * 1000)),
        "task": {"name": "Задача", "list": {"id": "L1"}},
        "description": "",
    }
    monkeypatch.setattr(dm, "get_user_clickup_client", lambda uid: FakeClient([entry]))

    r1 = await dm.sync_clickup_entries("42", datetime(2026, 7, 1), datetime(2026, 7, 31))
    assert r1["success"] and r1["synced_count"] == 1
    assert abs(r1["total_earnings"] - 900.0) < 1e-6          # 1.5h * 600

    r2 = await dm.sync_clickup_entries("42", datetime(2026, 7, 1), datetime(2026, 7, 31))
    assert r2["synced_count"] == 0                            # already synced

    ws = dm.get_work_sessions("42")
    assert len(ws["2026-07-04"]["sessions"]) == 1
    assert ws["2026-07-04"]["sessions"][0]["project_name"] == "Проект X"
    assert abs(ws["2026-07-04"]["total_hours"] - 1.5) < 1e-9


@pytest.mark.asyncio
async def test_sync_handles_taskless_entry_with_string_task(tmp_path, monkeypatch):
    """ClickUp отдаёт task='0' (строкой) для времени, затреканного без задачи."""
    dm = _dm(tmp_path, monkeypatch)
    dm.set_rate("42", 600.0)
    taskless = {
        "id": "e-taskless", "duration": str(1000 * 60 * 60),
        "start": str(int(datetime(2026, 7, 4, 10).timestamp() * 1000)),
        "task": "0",
        "description": "",
    }
    monkeypatch.setattr(dm, "get_user_clickup_client", lambda uid: FakeClient([taskless]))

    r = await dm.sync_clickup_entries("42", datetime(2026, 7, 1), datetime(2026, 7, 31))
    assert r["success"], r.get("error")
    assert r["synced_count"] == 1
    session = dm.get_work_sessions("42")["2026-07-04"]["sessions"][0]
    assert session["task_name"] == "Без задачи"


@pytest.mark.asyncio
async def test_sync_skips_negative_duration(tmp_path, monkeypatch):
    dm = _dm(tmp_path, monkeypatch)
    dm.set_rate("42", 600.0)
    running = {"id": "run1", "duration": "-1000", "start": "0", "task": None, "description": ""}
    monkeypatch.setattr(dm, "get_user_clickup_client", lambda uid: FakeClient([running]))
    r = await dm.sync_clickup_entries("42", datetime(2026, 7, 1), datetime(2026, 7, 31))
    assert r["success"] and r["synced_count"] == 0
    assert dm.is_entry_synced("42", "run1") is False         # never marked
