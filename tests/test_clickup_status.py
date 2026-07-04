"""Tests for the /clickup/status endpoint's `configured` flag.

Connection state must reflect *stored credentials*, not a live ClickUp API
round-trip, so a transient API failure never hides the connected profile.
"""
import api as api_module
from api import api as api_app, get_current_user
from clickup_client import ClickUpClient
from fastapi.testclient import TestClient


def _store_creds(user_id: str):
    ud = api_module.data_manager.get_user_data(user_id)
    ud["clickup_settings"]["api_token"] = "pk_test"
    ud["clickup_settings"]["workspace_id"] = "999"
    ud["clickup_settings"]["team_id"] = "999"
    ud["clickup_settings"]["username"] = "Tester"
    return ud


def test_configured_true_when_credentials_stored_even_if_api_down(monkeypatch):
    _store_creds("test-status-1")

    async def boom(self):
        raise RuntimeError("ClickUp API down")

    monkeypatch.setattr(ClickUpClient, "get_team_id", boom)

    api_app.dependency_overrides[get_current_user] = lambda: "test-status-1"
    try:
        resp = TestClient(api_app).get("/clickup/status")
    finally:
        api_app.dependency_overrides.clear()

    assert resp.status_code == 200
    data = resp.json()
    assert data["configured"] is True
    assert data["username"] == "Tester"
    assert data["workspace_id"] == "999"
    assert data["active_timer"] is None


def test_configured_false_when_no_credentials(monkeypatch):
    api_app.dependency_overrides[get_current_user] = lambda: "test-status-empty"
    try:
        resp = TestClient(api_app).get("/clickup/status")
    finally:
        api_app.dependency_overrides.clear()

    assert resp.status_code == 200
    assert resp.json()["configured"] is False
