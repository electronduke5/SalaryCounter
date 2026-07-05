from cryptography.fernet import Fernet


def _dm(tmp_path, monkeypatch):
    monkeypatch.setenv("ENCRYPTION_KEY", Fernet.generate_key().decode())
    from data_manager import DataManager
    return DataManager(str(tmp_path / "salary.db"))


def test_rate_round_trip(tmp_path, monkeypatch):
    dm = _dm(tmp_path, monkeypatch)
    dm.set_rate("42", 500.0)
    from data_manager import DataManager
    reopened = DataManager(dm.db_path)
    assert reopened.get_rate("42") == 500.0


def test_synced_entries_persist(tmp_path, monkeypatch):
    dm = _dm(tmp_path, monkeypatch)
    dm.add_synced_session("42", "entry-1", "2026-07-04",
                          {"duration_ms": 3600 * 1000, "earnings": 100.0,
                           "clickup_id": "entry-1", "timestamp": "2026-07-04T10:00:00"})
    from data_manager import DataManager
    reopened = DataManager(dm.db_path)
    assert reopened.is_entry_synced("42", "entry-1") is True
