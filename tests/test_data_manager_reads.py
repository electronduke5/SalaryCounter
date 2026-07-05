from cryptography.fernet import Fernet


def _dm(tmp_path, monkeypatch):
    monkeypatch.setenv("ENCRYPTION_KEY", Fernet.generate_key().decode())
    from data_manager import DataManager
    return DataManager(str(tmp_path / "salary.db"))


def test_defaults_for_new_user(tmp_path, monkeypatch):
    dm = _dm(tmp_path, monkeypatch)
    dm.ensure_user("42")
    assert dm.get_rate("42") == 0
    assert dm.get_work_sessions("42") == {}
    settings = dm.get_clickup_settings("42")
    assert settings["api_token"] is None
    assert settings["workspace_id"] is None


def test_is_entry_synced_false_when_absent(tmp_path, monkeypatch):
    dm = _dm(tmp_path, monkeypatch)
    dm.ensure_user("42")
    assert dm.is_entry_synced("42", "e1") is False


def test_read_from_another_thread(tmp_path, monkeypatch):
    import threading
    dm = _dm(tmp_path, monkeypatch)
    dm.ensure_user("42")
    result = {}
    def worker():
        result["rate"] = dm.get_rate("42")   # different thread than the connection was created in
    t = threading.Thread(target=worker)
    t.start(); t.join()
    assert result["rate"] == 0
