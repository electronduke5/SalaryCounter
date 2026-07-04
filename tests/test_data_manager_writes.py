import pytest
from cryptography.fernet import Fernet


def _dm(tmp_path, monkeypatch):
    monkeypatch.setenv("ENCRYPTION_KEY", Fernet.generate_key().decode())
    from data_manager import DataManager
    return DataManager(str(tmp_path / "salary.db"))


def _session(ms, earnings, eid):
    return {"duration_ms": ms, "earnings": earnings, "timestamp": "2026-07-04T10:00:00",
            "source": "clickup", "clickup_id": eid, "task_name": "T",
            "project_name": "P", "description": ""}


def test_set_rate(tmp_path, monkeypatch):
    dm = _dm(tmp_path, monkeypatch)
    dm.set_rate("42", 500.0)
    assert dm.get_rate("42") == 500.0


def test_token_stored_encrypted(tmp_path, monkeypatch):
    dm = _dm(tmp_path, monkeypatch)
    dm.set_clickup_settings("42", api_token="pk_SECRET", workspace_id="ws1")
    raw = dm.conn.execute(
        "SELECT clickup_api_token FROM users WHERE user_id='42'").fetchone()[0]
    assert raw != "pk_SECRET"
    assert dm.get_clickup_settings("42")["api_token"] == "pk_SECRET"
    assert dm.get_clickup_settings("42")["workspace_id"] == "ws1"


def test_clear_clickup_settings(tmp_path, monkeypatch):
    dm = _dm(tmp_path, monkeypatch)
    dm.set_clickup_settings("42", api_token="pk_SECRET", workspace_id="ws1")
    dm.clear_clickup_settings("42")
    s = dm.get_clickup_settings("42")
    assert s["api_token"] is None and s["workspace_id"] is None


def test_add_synced_session_aggregates_and_dedups(tmp_path, monkeypatch):
    dm = _dm(tmp_path, monkeypatch)
    added1 = dm.add_synced_session("42", "e1", "2026-07-04",
                                   _session(90 * 60 * 1000, 750.0, "e1"))  # 1.5h
    assert added1 is True
    added2 = dm.add_synced_session("42", "e1", "2026-07-04",
                                   _session(90 * 60 * 1000, 750.0, "e1"))
    assert added2 is False                                   # already synced
    ws = dm.get_work_sessions("42")
    assert len(ws["2026-07-04"]["sessions"]) == 1            # not double-inserted
    assert abs(ws["2026-07-04"]["total_hours"] - 1.5) < 1e-9
    assert ws["2026-07-04"]["total_earnings"] == 750.0
    assert dm.is_entry_synced("42", "e1") is True


def test_count_synced_entries(tmp_path, monkeypatch):
    dm = _dm(tmp_path, monkeypatch)
    assert dm.count_synced_entries("42") == 0
    dm.add_synced_session("42", "e1", "2026-07-04",
                           _session(60 * 60 * 1000, 500.0, "e1"))
    dm.add_synced_session("42", "e2", "2026-07-04",
                           _session(60 * 60 * 1000, 500.0, "e2"))
    assert dm.count_synced_entries("42") == 2
    # duplicate entry_id must not double-count
    dm.add_synced_session("42", "e1", "2026-07-04",
                           _session(60 * 60 * 1000, 500.0, "e1"))
    assert dm.count_synced_entries("42") == 2
    # other users unaffected
    assert dm.count_synced_entries("99") == 0


def test_data_manager_requires_encryption_key(tmp_path, monkeypatch):
    monkeypatch.delenv("ENCRYPTION_KEY", raising=False)
    from data_manager import DataManager
    with pytest.raises(RuntimeError):
        DataManager(str(tmp_path / "x.db"))
