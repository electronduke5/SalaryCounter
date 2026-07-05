from datetime import datetime

from api import api as api_app, get_current_user
from fastapi.testclient import TestClient


def _client(user_id):
    api_app.dependency_overrides[get_current_user] = lambda: user_id
    return TestClient(api_app)


def _cleanup():
    api_app.dependency_overrides.clear()


def test_goal_get_put_roundtrip():
    client = _client("api-goal-1")
    try:
        resp = client.get("/user/goal")
        assert resp.status_code == 200
        assert resp.json()["goal"] == 0

        resp = client.put("/user/goal", json={"goal": 150000})
        assert resp.status_code == 200

        data = client.get("/user/goal").json()
        assert data["goal"] == 150000
        assert data["progress"]["goal"] == 150000
        assert "percent" in data["progress"]

        assert client.put("/user/goal", json={"goal": -5}).status_code == 400
    finally:
        _cleanup()


def test_bonuses_crud_and_ownership():
    client = _client("api-bonus-1")
    try:
        resp = client.post("/bonuses", json={
            "date": "2026-07-01", "amount": 30000, "comment": "Q2"})
        assert resp.status_code == 200
        bonus_id = resp.json()["id"]

        items = client.get("/bonuses", params={"year": 2026}).json()["bonuses"]
        assert len(items) == 1 and items[0]["amount"] == 30000

        assert client.post("/bonuses", json={
            "date": "2026-07-01", "amount": -1, "comment": None}).status_code == 400
        assert client.post("/bonuses", json={
            "date": "07.01.2026", "amount": 100, "comment": None}).status_code == 400

        assert client.delete(f"/bonuses/{bonus_id}").status_code == 200
        assert client.delete(f"/bonuses/{bonus_id}").status_code == 404
    finally:
        _cleanup()


def test_earnings_month_includes_bonus_and_goal():
    client = _client("api-month-1")
    try:
        client.put("/user/goal", json={"goal": 100000})
        today_month = datetime.now().strftime("%Y-%m")
        client.post("/bonuses", json={
            "date": f"{today_month}-01", "amount": 30000, "comment": None})

        data = client.get("/earnings/month").json()
        assert data["bonus_earnings"] == 30000
        assert data["total_with_bonuses"] == data["total_earnings"] + 30000
        assert data["goal"] == 100000
        assert data["goal_percent"] == 30
    finally:
        _cleanup()


def test_notification_settings_endpoint():
    client = _client("api-notif-1")
    try:
        data = client.get("/user/notifications").json()
        assert data["notify_daily_digest"] == 0
        assert data["digest_time"] == "21:00"

        resp = client.put("/user/notifications", json={
            "notify_daily_digest": 1, "digest_time": "20:15"})
        assert resp.status_code == 200
        data = client.get("/user/notifications").json()
        assert data["notify_daily_digest"] == 1
        assert data["digest_time"] == "20:15"

        assert client.put("/user/notifications",
                          json={"digest_time": "25:99"}).status_code == 400
    finally:
        _cleanup()
