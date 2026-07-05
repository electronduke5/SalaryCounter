from datetime import datetime

import api as api_module
from api import api as api_app, get_current_user
from fastapi.testclient import TestClient


def _client(user_id):
    api_app.dependency_overrides[get_current_user] = lambda: user_id
    return TestClient(api_app)


def _cleanup():
    api_app.dependency_overrides.clear()


def _add_session(user_id, date, hours, earnings, project=None):
    api_module.data_manager.add_synced_session(
        user_id, f"api-{user_id}-{date}-{project}", date, {
            "duration_ms": int(hours * 3_600_000),
            "earnings": earnings,
            "timestamp": f"{date}T10:00:00",
            "project_name": project,
        })


def test_heatmap_endpoint():
    client = _client("api-heat-1")
    try:
        year = datetime.now().year
        _add_session("api-heat-1", f"{year}-03-02", 5, 5000)
        data = client.get(f"/analytics/heatmap?year={year}").json()
        assert data["year"] == year
        days = {d["date"]: d for d in data["days"]}
        assert days[f"{year}-03-02"]["level"] == 3
    finally:
        _cleanup()


def test_projects_endpoint_month_period():
    client = _client("api-proj-1")
    try:
        month = datetime.now().strftime("%Y-%m")
        _add_session("api-proj-1", f"{month}-01", 6, 6000, project="Альфа")
        _add_session("api-proj-1", f"{month}-02", 2, 2000, project=None)
        data = client.get("/analytics/projects?period=month").json()
        names = [p["project_name"] for p in data["projects"]]
        assert names == ["Альфа", "Без проекта"]
        assert data["projects"][0]["share"] == 0.75
    finally:
        _cleanup()


def test_norm_endpoints():
    client = _client("api-norm-1")
    try:
        assert client.put("/user/hours-norm", json={"hours": -1}).status_code == 400
        assert client.put("/user/hours-norm", json={"hours": 160}).status_code == 200
        data = client.get("/analytics/norm").json()
        assert data["norm"] == 160
        assert data["expected_by_today"] is not None
    finally:
        _cleanup()
