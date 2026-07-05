import pytest

from data_manager import DataManager


@pytest.fixture
def dm(tmp_path, monkeypatch):
    monkeypatch.setenv("ENCRYPTION_KEY", "x8mkN2vQ7pL4jR9wT1yU6iO3aS5dF0gHqZcVbEnMxKk=")
    return DataManager(str(tmp_path / "salary.db"))


def test_get_users_for_autosync_only_with_token(dm):
    dm.set_rate("1", 100)  # без токена — не попадает
    dm.set_clickup_settings("2", api_token="tok-2", team_id="t2")
    dm.set_rate("2", 200)

    users = dm.get_users_for_autosync()
    assert [u["user_id"] for u in users] == ["2"]
    u = users[0]
    assert u["rate"] == 200
    assert u["autosync_enabled"] == 1
    assert u["notify_daily_digest"] == 0
    assert u["digest_time"] == "21:00"
    assert u["notify_weekly"] == 0
    assert u["notify_long_timer"] == 1
    assert u["long_timer_hours"] == 4


def test_notification_settings_roundtrip(dm):
    dm.ensure_user("7")
    settings = dm.get_notification_settings("7")
    assert settings["notify_daily_digest"] == 0
    assert settings["digest_time"] == "21:00"

    dm.set_notification_settings(
        "7", notify_daily_digest=1, digest_time="20:30",
        notify_weekly=1, long_timer_hours=2.5, autosync_enabled=0,
    )
    settings = dm.get_notification_settings("7")
    assert settings["notify_daily_digest"] == 1
    assert settings["digest_time"] == "20:30"
    assert settings["notify_weekly"] == 1
    assert settings["long_timer_hours"] == 2.5
    assert settings["autosync_enabled"] == 0


def test_set_notification_settings_ignores_unknown_fields(dm):
    dm.ensure_user("7")
    dm.set_notification_settings("7", rate=999, bogus="x", notify_weekly=1)
    assert dm.get_rate("7") == 0
    assert dm.get_notification_settings("7")["notify_weekly"] == 1


def test_was_notified_and_mark(dm):
    assert dm.was_notified("5", "daily", "2026-07-05") is False
    dm.mark_notified("5", "daily", "2026-07-05")
    assert dm.was_notified("5", "daily", "2026-07-05") is True
    # другой ref / kind / user — не отмечены
    assert dm.was_notified("5", "daily", "2026-07-06") is False
    assert dm.was_notified("5", "weekly", "2026-07-05") is False
    assert dm.was_notified("6", "daily", "2026-07-05") is False
    # повторный mark не падает
    dm.mark_notified("5", "daily", "2026-07-05")
    assert dm.was_notified("5", "daily", "2026-07-05") is True
