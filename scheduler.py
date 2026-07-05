"""Фоновый шедулер: автосинк ClickUp и уведомления (дайджест, сводка, забытый таймер).

Работает в том же процессе, что бот и API (запускается из lifespan в api.py).
Время — локальный TZ сервера, либо APP_TZ (zoneinfo), если задан.
"""

import asyncio
import logging
import os
from datetime import datetime, timedelta
from typing import Any, Dict, Optional
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

KIND_DAILY = "daily"
KIND_WEEKLY = "weekly"
KIND_LONG_TIMER = "long_timer"

MS_PER_HOUR = 3_600_000


def now_local() -> datetime:
    tz_name = os.getenv("APP_TZ")
    if tz_name:
        return datetime.now(ZoneInfo(tz_name)).replace(tzinfo=None)
    return datetime.now()


def should_send_daily(settings: Dict[str, Any], now: datetime, already_sent: bool) -> bool:
    if already_sent or not settings.get("notify_daily_digest"):
        return False
    return now.strftime("%H:%M") >= settings.get("digest_time", "21:00")


def should_send_weekly(settings: Dict[str, Any], now: datetime, already_sent: bool) -> bool:
    if already_sent or not settings.get("notify_weekly"):
        return False
    if now.weekday() != 6:  # воскресенье
        return False
    return now.strftime("%H:%M") >= settings.get("digest_time", "21:00")


def week_ref(now: datetime) -> str:
    iso = now.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def long_timer_exceeded(timer: Dict[str, Any], now_ms: int, threshold_hours: float) -> bool:
    start_ms = int(timer.get("start", 0))
    return (now_ms - start_ms) > threshold_hours * MS_PER_HOUR


class BackgroundScheduler:
    def __init__(self, data_manager, bot):
        self.dm = data_manager
        self.bot = bot
        self.tick_seconds = int(os.getenv("SCHEDULER_TICK_SECONDS", "300"))
        self.autosync_interval = timedelta(
            minutes=int(os.getenv("AUTOSYNC_INTERVAL_MINUTES", "30"))
        )
        self.timer_check_interval = timedelta(
            minutes=int(os.getenv("TIMER_CHECK_INTERVAL_MINUTES", "15"))
        )
        self._last_sync: Dict[str, datetime] = {}
        self._last_timer_check: Dict[str, datetime] = {}

    async def run(self) -> None:
        logger.info("Background scheduler started (tick %ss)", self.tick_seconds)
        while True:
            try:
                await self._tick(now_local())
            except Exception:
                logger.exception("Scheduler tick failed")
            await asyncio.sleep(self.tick_seconds)

    async def _tick(self, now: datetime) -> None:
        for user in self.dm.get_users_for_autosync():
            user_id = user["user_id"]
            try:
                await self._process_user(user, now)
            except Exception:
                logger.exception("Scheduler: user %s failed", user_id)

    async def _process_user(self, user: Dict[str, Any], now: datetime) -> None:
        user_id = user["user_id"]
        if user.get("autosync_enabled") and self._due(self._last_sync, user_id, now, self.autosync_interval):
            self._last_sync[user_id] = now
            await self.dm.sync_clickup_entries(user_id, now - timedelta(days=2), now)

        today_ref = now.strftime("%Y-%m-%d")
        if should_send_daily(user, now, self.dm.was_notified(user_id, KIND_DAILY, today_ref)):
            await self._send_daily_digest(user_id, now, today_ref)

        if should_send_weekly(user, now, self.dm.was_notified(user_id, KIND_WEEKLY, week_ref(now))):
            await self._send_weekly_summary(user_id, now)

        if user.get("notify_long_timer") and self._due(
            self._last_timer_check, user_id, now, self.timer_check_interval
        ):
            self._last_timer_check[user_id] = now
            await self._check_long_timer(user_id, user, now)

    @staticmethod
    def _due(registry: Dict[str, datetime], user_id: str, now: datetime,
             interval: timedelta) -> bool:
        last = registry.get(user_id)
        return last is None or (now - last) >= interval

    async def _send_daily_digest(self, user_id: str, now: datetime, today_ref: str) -> None:
        # форс-синк, чтобы дайджест был по актуальным данным
        try:
            await self.dm.sync_clickup_entries(user_id, now - timedelta(days=1), now)
        except Exception:
            logger.exception("Digest pre-sync failed for %s", user_id)

        day = self.dm.get_work_sessions(user_id).get(today_ref)
        if day:
            time_str = self.dm.format_hours_minutes(day["total_hours"])
            text = (
                f"🌙 Итоги дня ({now.strftime('%d.%m')}):\n\n"
                f"⏱ Время: {time_str}\n"
                f"💰 Заработано: {day['total_earnings']:.0f} руб"
            )
        else:
            text = f"🌙 Итоги дня ({now.strftime('%d.%m')}):\n\nСегодня рабочих сессий не было."

        progress = self.dm.get_month_progress(user_id, now=now)
        if progress["goal"] > 0:
            text += (
                f"\n🎯 Цель месяца: {progress['total']:.0f} из {progress['goal']:.0f} руб "
                f"({progress['percent']}%)"
            )
        await self._notify(user_id, KIND_DAILY, today_ref, text)

    async def _send_weekly_summary(self, user_id: str, now: datetime) -> None:
        work_sessions = self.dm.get_work_sessions(user_id)
        text = self.dm.generate_week_details_report(work_sessions)
        await self._notify(user_id, KIND_WEEKLY, week_ref(now), text)

    async def _check_long_timer(self, user_id: str, user: Dict[str, Any], now: datetime) -> None:
        client = self.dm.get_user_clickup_client(user_id)
        if not client:
            return
        timer: Optional[Dict[str, Any]] = await client.get_current_timer()
        if not timer:
            return
        entry_id = str(timer.get("id"))
        threshold = float(user.get("long_timer_hours") or 4)
        now_ms = int(now.timestamp() * 1000)
        if not long_timer_exceeded(timer, now_ms, threshold):
            return
        if self.dm.was_notified(user_id, KIND_LONG_TIMER, entry_id):
            return
        elapsed_hours = (now_ms - int(timer.get("start", 0))) / MS_PER_HOUR
        # ClickUp отдаёт task='0' (строкой) для таймера без привязки к задаче
        task = timer.get("task")
        task_name = task.get("name", "Без задачи") if isinstance(task, dict) else "Без задачи"
        text = (
            f"⏰ Таймер \"{task_name}\" работает уже "
            f"{self.dm.format_hours_minutes(elapsed_hours)}.\n"
            f"Не забыл остановить?"
        )
        await self._notify(user_id, KIND_LONG_TIMER, entry_id, text)

    async def _notify(self, user_id: str, kind: str, ref: str, text: str) -> None:
        """Отправить сообщение и отметить в notification_log.

        Отметка ставится и при TelegramForbiddenError (бот заблокирован),
        чтобы не ретраить отправку каждый тик."""
        try:
            await self.bot.send_message(chat_id=int(user_id), text=text)
        except Exception as e:
            if type(e).__name__ != "TelegramForbiddenError":
                raise
        self.dm.mark_notified(user_id, kind, ref)
