from datetime import datetime

import pytest
from cryptography.fernet import Fernet

import scheduler
from scheduler import BackgroundScheduler


def _dm(tmp_path, monkeypatch):
    monkeypatch.setenv("ENCRYPTION_KEY", Fernet.generate_key().decode())
    from data_manager import DataManager
    return DataManager(str(tmp_path / "salary.db"))


class FakeBot:
    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text, **kwargs):
        self.sent.append((chat_id, text))


class FakeClient:
    def __init__(self, entries=None, timer=None):
        self._entries = entries or []
        self._timer = timer

    async def get_time_entries(self, start, end):
        return self._entries

    async def get_list(self, list_id):
        return {"name": "Проект X"}

    async def get_current_timer(self):
        return self._timer


# --- чистые функции решений ---

SETTINGS = {
    "notify_daily_digest": 1, "digest_time": "21:00",
    "notify_weekly": 1, "notify_long_timer": 1, "long_timer_hours": 4,
}


def test_should_send_daily_before_and_after_time():
    before = datetime(2026, 7, 6, 20, 59)
    after = datetime(2026, 7, 6, 21, 0)
    assert scheduler.should_send_daily(SETTINGS, before, already_sent=False) is False
    assert scheduler.should_send_daily(SETTINGS, after, already_sent=False) is True
    assert scheduler.should_send_daily(SETTINGS, after, already_sent=True) is False
    off = dict(SETTINGS, notify_daily_digest=0)
    assert scheduler.should_send_daily(off, after, already_sent=False) is False


def test_should_send_weekly_only_sunday():
    sunday = datetime(2026, 7, 5, 21, 30)   # воскресенье
    monday = datetime(2026, 7, 6, 21, 30)
    assert scheduler.should_send_weekly(SETTINGS, sunday, already_sent=False) is True
    assert scheduler.should_send_weekly(SETTINGS, monday, already_sent=False) is False
    assert scheduler.should_send_weekly(SETTINGS, sunday, already_sent=True) is False


def test_week_ref_iso_format():
    assert scheduler.week_ref(datetime(2026, 7, 5)) == "2026-W27"


def test_long_timer_exceeded():
    now_ms = 10 * 3_600_000
    timer = {"id": "run1", "start": str(now_ms - 5 * 3_600_000)}
    assert scheduler.long_timer_exceeded(timer, now_ms, threshold_hours=4) is True
    assert scheduler.long_timer_exceeded(timer, now_ms, threshold_hours=6) is False


# --- интеграционные тики ---

def _entry(entry_id, day_hour_start, hours):
    start = datetime(2026, 7, day_hour_start[0], day_hour_start[1])
    return {
        "id": entry_id,
        "duration": str(int(hours * 3_600_000)),
        "start": str(int(start.timestamp() * 1000)),
        "task": {"name": "Задача", "list": {"id": "L1"}},
        "description": "",
    }


@pytest.mark.asyncio
async def test_tick_autosync_and_daily_digest_once(tmp_path, monkeypatch):
    dm = _dm(tmp_path, monkeypatch)
    dm.set_rate("42", 600.0)
    dm.set_clickup_settings("42", api_token="tok", team_id="t")
    dm.set_notification_settings("42", notify_daily_digest=1)
    client = FakeClient(entries=[_entry("e1", (5, 10), 1.5)])
    monkeypatch.setattr(dm, "get_user_clickup_client", lambda uid: client)

    bot = FakeBot()
    sched = BackgroundScheduler(dm, bot)
    now = datetime(2026, 7, 5, 21, 5)

    await sched._tick(now)
    ws = dm.get_work_sessions("42")
    assert abs(ws["2026-07-05"]["total_hours"] - 1.5) < 1e-9      # автосинк сработал
    daily = [t for _, t in bot.sent if "Итоги дня" in t]
    assert len(daily) == 1
    assert "900" in daily[0]                                        # 1.5h * 600

    await sched._tick(datetime(2026, 7, 5, 21, 20))
    assert len([t for _, t in bot.sent if "Итоги дня" in t]) == 1   # без дубля
    assert len(ws["2026-07-05"]["sessions"]) == 1                   # дедуп синка


@pytest.mark.asyncio
async def test_daily_digest_includes_goal_progress(tmp_path, monkeypatch):
    dm = _dm(tmp_path, monkeypatch)
    dm.set_rate("42", 600.0)
    dm.set_clickup_settings("42", api_token="tok", team_id="t")
    dm.set_notification_settings("42", notify_daily_digest=1)
    dm.set_monthly_goal("42", 100000)
    monkeypatch.setattr(dm, "get_user_clickup_client",
                        lambda uid: FakeClient(entries=[_entry("e1", (5, 10), 1.5)]))

    bot = FakeBot()
    await BackgroundScheduler(dm, bot)._tick(datetime(2026, 7, 5, 21, 5))
    digest = next(t for _, t in bot.sent if "Итоги дня" in t)
    assert "Цель" in digest and "1%" in digest


@pytest.mark.asyncio
async def test_tick_weekly_summary_on_sunday(tmp_path, monkeypatch):
    dm = _dm(tmp_path, monkeypatch)
    dm.set_rate("42", 600.0)
    dm.set_clickup_settings("42", api_token="tok", team_id="t")
    dm.set_notification_settings("42", notify_weekly=1)
    monkeypatch.setattr(dm, "get_user_clickup_client", lambda uid: FakeClient())

    bot = FakeBot()
    sched = BackgroundScheduler(dm, bot)
    await sched._tick(datetime(2026, 7, 5, 21, 5))    # воскресенье
    weekly = [t for _, t in bot.sent if "недел" in t.lower()]
    assert len(weekly) == 1
    await sched._tick(datetime(2026, 7, 5, 21, 30))
    assert len([t for _, t in bot.sent if "недел" in t.lower()]) == 1


@pytest.mark.asyncio
async def test_tick_long_timer_alert_once_per_run(tmp_path, monkeypatch):
    dm = _dm(tmp_path, monkeypatch)
    dm.set_rate("42", 600.0)
    dm.set_clickup_settings("42", api_token="tok", team_id="t")
    now = datetime(2026, 7, 6, 15, 0)
    started = int(now.timestamp() * 1000) - 5 * 3_600_000
    timer = {"id": "run9", "start": str(started), "duration": "-1",
             "task": {"name": "Долгая задача"}}
    monkeypatch.setattr(dm, "get_user_clickup_client",
                        lambda uid: FakeClient(timer=timer))

    bot = FakeBot()
    sched = BackgroundScheduler(dm, bot)
    await sched._tick(now)
    alerts = [t for _, t in bot.sent if "Таймер" in t]
    assert len(alerts) == 1 and "Долгая задача" in alerts[0]

    sched2 = BackgroundScheduler(dm, bot)               # рестарт процесса
    await sched2._tick(datetime(2026, 7, 6, 16, 0))
    assert len([t for _, t in bot.sent if "Таймер" in t]) == 1


@pytest.mark.asyncio
async def test_tick_user_error_does_not_break_others(tmp_path, monkeypatch):
    dm = _dm(tmp_path, monkeypatch)
    for uid in ("1", "2"):
        dm.set_rate(uid, 500.0)
        dm.set_clickup_settings(uid, api_token="tok", team_id="t")
        dm.set_notification_settings(uid, notify_daily_digest=1)

    class BrokenClient(FakeClient):
        async def get_time_entries(self, start, end):
            raise RuntimeError("boom")

    clients = {"1": BrokenClient(), "2": FakeClient(entries=[_entry("e2", (6, 10), 2)])}
    monkeypatch.setattr(dm, "get_user_clickup_client", lambda uid: clients[uid])

    bot = FakeBot()
    sched = BackgroundScheduler(dm, bot)
    await sched._tick(datetime(2026, 7, 6, 21, 5))
    assert abs(dm.get_work_sessions("2").get("2026-07-06", {}).get("total_hours", 0) - 2) < 1e-9


@pytest.mark.asyncio
async def test_tick_respects_autosync_disabled(tmp_path, monkeypatch):
    dm = _dm(tmp_path, monkeypatch)
    dm.set_rate("42", 600.0)
    dm.set_clickup_settings("42", api_token="tok", team_id="t")
    dm.set_notification_settings("42", autosync_enabled=0, notify_long_timer=0)
    monkeypatch.setattr(dm, "get_user_clickup_client",
                        lambda uid: FakeClient(entries=[_entry("e1", (6, 10), 1)]))

    sched = BackgroundScheduler(dm, FakeBot())
    await sched._tick(datetime(2026, 7, 6, 12, 0))
    assert dm.get_work_sessions("42") == {}
