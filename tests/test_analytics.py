from datetime import datetime

import pytest
from cryptography.fernet import Fernet


@pytest.fixture
def dm(tmp_path, monkeypatch):
    monkeypatch.setenv("ENCRYPTION_KEY", Fernet.generate_key().decode())
    from data_manager import DataManager
    return DataManager(str(tmp_path / "salary.db"))


def _add(dm, user_id, date, hours, earnings, project=None, entry=None):
    dm.add_synced_session(user_id, entry or f"e-{date}-{hours}-{project}", date, {
        "duration_ms": int(hours * 3_600_000),
        "earnings": earnings,
        "timestamp": f"{date}T10:00:00",
        "project_name": project,
    })


def test_activity_heatmap_levels_and_year_bounds(dm):
    _add(dm, "42", "2026-07-01", 1, 1000)     # < 2ч → level 1
    _add(dm, "42", "2026-07-02", 3, 3000)     # < 4ч → level 2
    _add(dm, "42", "2026-07-03", 5, 5000)     # < 6ч → level 3
    _add(dm, "42", "2026-07-04", 8, 8000)     # ≥ 6ч → level 4
    _add(dm, "42", "2025-12-31", 8, 8000)     # другой год — не входит

    days = dm.get_activity_heatmap("42", 2026)
    by_date = {d["date"]: d for d in days}
    assert "2025-12-31" not in by_date
    assert by_date["2026-07-01"]["level"] == 1
    assert by_date["2026-07-02"]["level"] == 2
    assert by_date["2026-07-03"]["level"] == 3
    assert by_date["2026-07-04"]["level"] == 4
    assert by_date["2026-07-04"]["hours"] == 8
    assert by_date["2026-07-04"]["earnings"] == 8000


def test_activity_heatmap_empty_year(dm):
    dm.ensure_user("42")
    assert dm.get_activity_heatmap("42", 2020) == []


def test_projects_breakdown_shares_and_fallback_name(dm):
    _add(dm, "42", "2026-07-01", 6, 6000, project="Альфа")
    _add(dm, "42", "2026-07-02", 3, 3000, project="Альфа", entry="a2")
    _add(dm, "42", "2026-07-02", 1, 1000, project=None, entry="n1")
    _add(dm, "42", "2026-06-01", 8, 8000, project="Прошлый", entry="old")

    items = dm.get_projects_breakdown(
        "42", datetime(2026, 7, 1), datetime(2026, 7, 31))
    assert [i["project_name"] for i in items] == ["Альфа", "Без проекта"]
    alpha = items[0]
    assert alpha["hours"] == 9
    assert alpha["earnings"] == 9000
    assert abs(alpha["share"] - 0.9) < 1e-9
    assert items[1]["share"] == pytest.approx(0.1)


def test_hours_norm_stats(dm):
    dm.ensure_user("42")
    dm.set_hours_norm("42", 160)
    assert dm.get_hours_norm("42") == 160

    _add(dm, "42", "2026-07-01", 8, 8000)
    _add(dm, "42", "2026-07-02", 8, 8000, entry="d2")

    # 5 июля из 31 дня месяца
    stats = dm.get_hours_norm_stats("42", now=datetime(2026, 7, 5))
    assert stats["norm"] == 160
    assert stats["actual_hours"] == 16
    assert stats["expected_by_today"] == pytest.approx(160 * 5 / 31)
    assert stats["diff"] == pytest.approx(16 - 160 * 5 / 31)


def test_hours_norm_stats_without_norm(dm):
    dm.ensure_user("42")
    stats = dm.get_hours_norm_stats("42", now=datetime(2026, 7, 5))
    assert stats["norm"] == 0
    assert stats["expected_by_today"] is None
    assert stats["diff"] is None
