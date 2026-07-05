from datetime import datetime

import pytest
from cryptography.fernet import Fernet


@pytest.fixture
def dm(tmp_path, monkeypatch):
    monkeypatch.setenv("ENCRYPTION_KEY", Fernet.generate_key().decode())
    from data_manager import DataManager
    return DataManager(str(tmp_path / "salary.db"))


def _add_session(dm, user_id, date, hours, earnings):
    dm.add_synced_session(user_id, f"e-{date}-{hours}", date, {
        "duration_ms": int(hours * 3_600_000),
        "earnings": earnings,
        "timestamp": f"{date}T10:00:00",
    })


def test_bonus_crud_and_sum(dm):
    b1 = dm.add_bonus("42", "2026-07-01", 30000, "Q2 премия")
    b2 = dm.add_bonus("42", "2026-04-01", 25000, None)
    assert isinstance(b1, int) and b1 != b2

    all_bonuses = dm.get_bonuses("42")
    assert len(all_bonuses) == 2
    july = dm.get_bonuses("42", start_date="2026-07-01", end_date="2026-07-31")
    assert len(july) == 1
    assert july[0]["amount"] == 30000
    assert july[0]["comment"] == "Q2 премия"

    assert dm.sum_bonuses("42", "2026-07-01", "2026-07-31") == 30000
    assert dm.sum_bonuses("42", "2026-01-01", "2026-12-31") == 55000
    assert dm.sum_bonuses("42", "2026-08-01", "2026-08-31") == 0


def test_delete_bonus_checks_owner(dm):
    bid = dm.add_bonus("42", "2026-07-01", 1000, None)
    assert dm.delete_bonus("99", bid) is False       # чужая премия
    assert dm.get_bonuses("42")
    assert dm.delete_bonus("42", bid) is True
    assert dm.get_bonuses("42") == []
    assert dm.delete_bonus("42", bid) is False       # уже удалена


def test_monthly_goal_roundtrip(dm):
    dm.ensure_user("42")
    assert dm.get_monthly_goal("42") == 0
    dm.set_monthly_goal("42", 250000)
    assert dm.get_monthly_goal("42") == 250000
    dm.set_monthly_goal("42", 0)
    assert dm.get_monthly_goal("42") == 0


def test_get_month_progress(dm):
    dm.set_rate("42", 1000)
    dm.set_monthly_goal("42", 100000)
    _add_session(dm, "42", "2026-07-03", 8, 8000)
    _add_session(dm, "42", "2026-07-04", 10, 10000)
    _add_session(dm, "42", "2026-06-30", 8, 8000)     # прошлый месяц — не считается
    dm.add_bonus("42", "2026-07-01", 30000, "Q2")
    dm.add_bonus("42", "2026-05-05", 5000, None)      # не этот месяц

    p = dm.get_month_progress("42", now=datetime(2026, 7, 5, 12, 0))
    assert p["hours_earnings"] == 18000
    assert p["bonus_earnings"] == 30000
    assert p["total"] == 48000
    assert p["goal"] == 100000
    assert p["percent"] == 48
    assert p["remaining"] == 52000
    assert p["days_left"] == 26                        # 31 - 5


def test_get_month_progress_without_goal(dm):
    dm.set_rate("42", 1000)
    _add_session(dm, "42", "2026-07-03", 1, 1000)
    p = dm.get_month_progress("42", now=datetime(2026, 7, 5))
    assert p["goal"] == 0
    assert p["percent"] is None
    assert p["total"] == 1000


def test_month_report_includes_bonuses_and_goal(dm):
    dm.set_rate("42", 1000)
    today = datetime.now().strftime("%Y-%m-%d")
    _add_session(dm, "42", today, 8, 8000)
    ws = dm.get_work_sessions("42")

    report = dm.generate_month_report(ws, bonus_total=30000, goal=100000)
    assert "по часам" in report and "8000" in report
    assert "Премии" in report and "30000" in report
    assert "Итого" in report and "38000" in report
    assert "Цель" in report and "38%" in report

    plain = dm.generate_month_report(ws)
    assert "Премии" not in plain and "Цель" not in plain
