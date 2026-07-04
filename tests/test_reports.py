from datetime import datetime

from cryptography.fernet import Fernet


def _dm(tmp_path, monkeypatch):
    monkeypatch.setenv("ENCRYPTION_KEY", Fernet.generate_key().decode())
    from data_manager import DataManager
    return DataManager(str(tmp_path / "salary.db"))


def _session(ms, earnings, eid, task):
    return {"duration_ms": ms, "earnings": earnings, "timestamp": "2026-07-04T10:00:00",
            "source": "clickup", "clickup_id": eid, "task_name": task,
            "project_name": "P", "description": ""}


def test_today_report_from_work_sessions(tmp_path, monkeypatch):
    dm = _dm(tmp_path, monkeypatch)
    today = datetime.now().strftime("%Y-%m-%d")
    dm.add_synced_session("42", "e1", today, _session(2 * 3600 * 1000, 1000.0, "e1", "T"))
    text = dm.generate_today_report(dm.get_work_sessions("42"))
    assert "1000.00 руб" in text


def test_tasks_summary_groups_by_task(tmp_path, monkeypatch):
    dm = _dm(tmp_path, monkeypatch)
    day = datetime(2026, 7, 4)
    dm.add_synced_session("42", "e1", "2026-07-04",
                          _session(3600 * 1000, 500.0, "e1", "Задача А"))
    summary = dm.get_tasks_summary("42", day.replace(hour=0),
                                   day.replace(hour=23, minute=59))
    assert summary["total_tasks"] == 1
    assert "Задача А" in summary["tasks"]
    assert abs(summary["total_hours"] - 1.0) < 1e-9
