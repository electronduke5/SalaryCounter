import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional

import crypto
import db
from clickup_client import ClickUpClient

logger = logging.getLogger(__name__)

DB_FILE = "salary.db"
MS_PER_HOUR = 3_600_000

_CLICKUP_KEYS = ("api_token", "workspace_id", "team_id", "user_id", "username")


class DataManager:
    """Управление данными пользователей и генерация отчётов (хранилище — SQLite)."""

    def __init__(self, db_path: str = DB_FILE):
        self.db_path = db_path
        self.conn = db.get_connection(db_path)

    def ensure_user(self, user_id: str) -> None:
        self.conn.execute(
            "INSERT OR IGNORE INTO users (user_id, rate) VALUES (?, 0)", (user_id,)
        )

    def get_rate(self, user_id: str) -> float:
        row = self.conn.execute(
            "SELECT rate FROM users WHERE user_id = ?", (user_id,)
        ).fetchone()
        return row["rate"] if row else 0.0

    def get_clickup_settings(self, user_id: str) -> Dict[str, Any]:
        row = self.conn.execute(
            "SELECT clickup_api_token, clickup_workspace_id, clickup_team_id, "
            "clickup_user_id, clickup_username FROM users WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        if not row:
            return {k: None for k in _CLICKUP_KEYS}
        token = row["clickup_api_token"]
        return {
            "api_token": crypto.decrypt(token) if token else None,
            "workspace_id": row["clickup_workspace_id"],
            "team_id": row["clickup_team_id"],
            "user_id": row["clickup_user_id"],
            "username": row["clickup_username"],
        }

    def get_work_sessions(self, user_id: str) -> Dict[str, Any]:
        cur = self.conn.execute(
            "SELECT date, duration_ms, earnings, timestamp, source, clickup_id, "
            "task_name, project_name, description FROM work_sessions "
            "WHERE user_id = ? ORDER BY id",
            (user_id,),
        )
        result: Dict[str, Any] = {}
        for row in cur:
            day = result.setdefault(
                row["date"], {"total_hours": 0.0, "total_earnings": 0.0, "sessions": []}
            )
            ms = row["duration_ms"]
            duration_hours = ms / MS_PER_HOUR
            day["sessions"].append({
                "duration_ms": ms,
                "duration_hours": duration_hours,
                "hours": ms // MS_PER_HOUR,
                "minutes": (ms % MS_PER_HOUR) // 60_000,
                "earnings": row["earnings"],
                "timestamp": row["timestamp"],
                "source": row["source"],
                "clickup_id": row["clickup_id"],
                "task_name": row["task_name"],
                "project_name": row["project_name"],
                "description": row["description"],
            })
            day["total_hours"] += duration_hours
            day["total_earnings"] += row["earnings"]
        return result

    def is_entry_synced(self, user_id: str, entry_id: str) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM synced_entries WHERE user_id = ? AND entry_id = ?",
            (user_id, entry_id),
        ).fetchone()
        return row is not None

    def format_hours_minutes(self, total_hours: float) -> str:
        """Форматирование времени в формат 'Xч Yм'"""
        hours = int(total_hours)
        minutes = int((total_hours - hours) * 60)

        if minutes == 0:
            return f"{hours}ч"
        else:
            return f"{hours}ч {minutes}м"

    def get_russian_month_year(self, date) -> str:
        """Получение русского названия месяца и года"""
        months = {
            'January': 'январь', 'February': 'февраль', 'March': 'март',
            'April': 'апрель', 'May': 'май', 'June': 'июнь',
            'July': 'июль', 'August': 'август', 'September': 'сентябрь',
            'October': 'октябрь', 'November': 'ноябрь', 'December': 'декабрь'
        }
        english_month = date.strftime('%B')
        russian_month = months.get(english_month, english_month.lower())
        year = date.strftime('%Y')
        return f"{russian_month} {year}"

    def generate_today_report(self, user_data: Dict[str, Any]) -> str:
        """Генерация отчета за сегодня"""
        today = datetime.now().strftime("%Y-%m-%d")

        if today in user_data["work_sessions"]:
            session = user_data["work_sessions"][today]
            return (
                f"📊 Заработок за сегодня ({datetime.now().strftime('%d.%m.%Y')}):\n\n"
                f"⏰ Отработано: {self.format_hours_minutes(session['total_hours'])}\n"
                f"💰 Заработано: {session['total_earnings']:.2f} руб"
            )
        else:
            return "📊 Сегодня вы еще не добавляли рабочее время"

    def generate_yesterday_report(self, user_data: Dict[str, Any]) -> str:
        """Генерация отчета за вчера"""
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

        if yesterday in user_data["work_sessions"]:
            session = user_data["work_sessions"][yesterday]
            return (
                f"📊 Заработок за вчера ({(datetime.now() - timedelta(days=1)).strftime('%d.%m.%Y')}):\n\n"
                f"⏰ Отработано: {self.format_hours_minutes(session['total_hours'])}\n"
                f"💰 Заработано: {session['total_earnings']:.2f} руб"
            )
        else:
            return "📊 Вчера вы не добавляли рабочее время"

    def generate_week_report(self, user_data: Dict[str, Any]) -> str:
        """Генерация отчета за неделю"""
        today = datetime.now()
        monday = today - timedelta(days=today.weekday())

        total_hours = 0
        total_earnings = 0
        days_worked = 0

        current_date = monday
        while current_date <= today:
            date_str = current_date.strftime("%Y-%m-%d")
            if date_str in user_data["work_sessions"]:
                session = user_data["work_sessions"][date_str]
                total_hours += session["total_hours"]
                total_earnings += session["total_earnings"]
                days_worked += 1
            current_date += timedelta(days=1)

        if days_worked > 0:
            return (
                f"📊 Заработок за неделю (с {monday.strftime('%d.%m')} по {today.strftime('%d.%m')}):\n\n"
                f"📅 Рабочих дней: {days_worked}\n"
                f"⏰ Всего отработано: {self.format_hours_minutes(total_hours)}\n"
                f"💰 Всего заработано: {total_earnings:.2f} руб\n"
                f"📈 Среднее в день: {total_earnings / days_worked:.2f} руб"
            )
        else:
            return f"📊 На этой неделе (с {monday.strftime('%d.%m')} по {today.strftime('%d.%m')}) нет записей о работе"

    def generate_month_report(self, user_data: Dict[str, Any]) -> str:
        """Генерация отчета за текущий календарный месяц"""
        today = datetime.now()
        first_day_of_month = today.replace(day=1)

        if today.month == 12:
            last_day_of_month = today.replace(day=31)
        else:
            last_day_of_month = today.replace(day=1, month=today.month + 1) - timedelta(days=1)

        total_hours = 0
        total_earnings = 0
        days_worked = 0

        current_date = first_day_of_month
        while current_date <= min(today, last_day_of_month):
            date_str = current_date.strftime("%Y-%m-%d")
            if date_str in user_data["work_sessions"]:
                session = user_data["work_sessions"][date_str]
                total_hours += session["total_hours"]
                total_earnings += session["total_earnings"]
                days_worked += 1
            current_date += timedelta(days=1)

        if days_worked > 0:
            month_name = today.strftime("%B %Y")
            return (
                f"📊 Заработок за {month_name}:\n\n"
                f"📅 Рабочих дней: {days_worked}\n"
                f"⏰ Всего отработано: {self.format_hours_minutes(total_hours)}\n"
                f"💰 Всего заработано: {total_earnings:.2f} руб\n"
                f"📈 Среднее в день: {total_earnings / days_worked:.2f} руб"
            )
        else:
            month_name = today.strftime("%B %Y")
            return f"📊 В {month_name} нет записей о работе"

    def generate_week_details_report(self, user_data: Dict[str, Any]) -> str:
        """Генерация детального отчета за неделю"""
        today = datetime.now()
        monday = today - timedelta(days=today.weekday())

        days_names = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]
        total_hours = 0
        total_earnings = 0
        response_lines = [f"📊 Детальный заработок за неделю (с {monday.strftime('%d.%m')} по {today.strftime('%d.%m')}):\n"]

        current_date = monday
        day_index = 0
        while current_date <= today:
            date_str = current_date.strftime("%Y-%m-%d")
            day_name = days_names[day_index]

            if date_str in user_data["work_sessions"]:
                session = user_data["work_sessions"][date_str]
                hours = session["total_hours"]
                earnings = session["total_earnings"]
                total_hours += hours
                total_earnings += earnings
                response_lines.append(f"📅 {day_name} ({current_date.strftime('%d.%m')}): {self.format_hours_minutes(hours)} = {earnings:.2f} руб")
            else:
                response_lines.append(f"📅 {day_name} ({current_date.strftime('%d.%m')}): 0ч = 0 руб")

            current_date += timedelta(days=1)
            day_index += 1

        if total_hours > 0:
            response_lines.extend([
                "",
                f"📊 Итого за неделю:",
                f"⏰ Всего отработано: {self.format_hours_minutes(total_hours)}",
                f"💰 Всего заработано: {total_earnings:.2f} руб"
            ])
        else:
            response_lines.extend(["", "📊 На этой неделе нет записей о работе"])

        return "\n".join(response_lines)

    def generate_month_weeks_report(self, user_data: Dict[str, Any]) -> str:
        """Генерация отчета по неделям в текущем месяце"""
        today = datetime.now()
        first_day_of_month = today.replace(day=1)

        if today.month == 12:
            last_day_of_month = today.replace(day=31)
        else:
            last_day_of_month = today.replace(day=1, month=today.month + 1) - timedelta(days=1)

        weeks_data = []
        total_month_hours = 0
        total_month_earnings = 0
        week_number = 1

        current_start = first_day_of_month

        while current_start <= today and current_start.month == today.month:
            if current_start == first_day_of_month:
                days_until_sunday = (6 - current_start.weekday()) % 7
                week_end = current_start + timedelta(days=days_until_sunday)
            else:
                week_end = current_start + timedelta(days=6)

            week_end = min(week_end, last_day_of_month, today)

            week_hours = 0
            week_earnings = 0

            current_date = current_start
            while current_date <= week_end:
                date_str = current_date.strftime("%Y-%m-%d")
                if date_str in user_data["work_sessions"]:
                    session = user_data["work_sessions"][date_str]
                    week_hours += session["total_hours"]
                    week_earnings += session["total_earnings"]
                current_date += timedelta(days=1)

            if week_hours > 0:
                weeks_data.append({
                    'number': week_number,
                    'start': current_start,
                    'end': week_end,
                    'hours': week_hours,
                    'earnings': week_earnings
                })
                total_month_hours += week_hours
                total_month_earnings += week_earnings

            if current_start == first_day_of_month:
                days_until_sunday = (6 - current_start.weekday()) % 7
                current_start = current_start + timedelta(days=days_until_sunday + 1)
            else:
                current_start += timedelta(days=7)

            week_number += 1

        if weeks_data:
            response_lines = [f"📊 Заработок по неделям в {self.get_russian_month_year(today)}:\n"]

            for week in weeks_data:
                response_lines.append(
                    f"📅 Неделя {week['number']} ({week['start'].strftime('%d.%m')} - {week['end'].strftime('%d.%m')}): "
                    f"{self.format_hours_minutes(week['hours'])} = {week['earnings']:.2f} руб"
                )

            response_lines.extend([
                "",
                f"📊 Итого за месяц:",
                f"📅 Недель с работой: {len(weeks_data)}",
                f"⏰ Всего отработано: {self.format_hours_minutes(total_month_hours)}",
                f"💰 Всего заработано: {total_month_earnings:.2f} руб"
            ])
        else:
            response_lines = [f"📊 В {self.get_russian_month_year(today)} нет записей о работе"]

        return "\n".join(response_lines)

    def generate_prev_month_weeks_report(self, user_data: Dict[str, Any]) -> str:
        """Генерация отчета по неделям в предыдущем месяце"""
        today = datetime.now()

        if today.month == 1:
            prev_month_first = today.replace(year=today.year - 1, month=12, day=1)
        else:
            prev_month_first = today.replace(month=today.month - 1, day=1)

        if prev_month_first.month == 12:
            prev_month_last = prev_month_first.replace(day=31)
        else:
            prev_month_last = prev_month_first.replace(day=1, month=prev_month_first.month + 1) - timedelta(days=1)

        weeks_data = []
        total_month_hours = 0
        total_month_earnings = 0
        week_number = 1

        current_start = prev_month_first

        while current_start <= prev_month_last:
            if current_start == prev_month_first:
                days_until_sunday = (6 - current_start.weekday()) % 7
                week_end = current_start + timedelta(days=days_until_sunday)
            else:
                week_end = current_start + timedelta(days=6)

            week_end = min(week_end, prev_month_last)

            week_hours = 0
            week_earnings = 0

            current_date = current_start
            while current_date <= week_end:
                date_str = current_date.strftime("%Y-%m-%d")
                if date_str in user_data["work_sessions"]:
                    session = user_data["work_sessions"][date_str]
                    week_hours += session["total_hours"]
                    week_earnings += session["total_earnings"]
                current_date += timedelta(days=1)

            if week_hours > 0:
                weeks_data.append({
                    'number': week_number,
                    'start': current_start,
                    'end': week_end,
                    'hours': week_hours,
                    'earnings': week_earnings
                })
                total_month_hours += week_hours
                total_month_earnings += week_earnings

            if current_start == prev_month_first:
                days_until_sunday = (6 - current_start.weekday()) % 7
                current_start = current_start + timedelta(days=days_until_sunday + 1)
            else:
                current_start += timedelta(days=7)

            week_number += 1

        if weeks_data:
            prev_month_name = self.get_russian_month_year(prev_month_first)
            response_lines = [f"📊 Заработок по неделям в {prev_month_name}:\n"]

            for week in weeks_data:
                response_lines.append(
                    f"📅 Неделя {week['number']} ({week['start'].strftime('%d.%m')} - {week['end'].strftime('%d.%m')}): "
                    f"{self.format_hours_minutes(week['hours'])} = {week['earnings']:.2f} руб"
                )

            response_lines.extend([
                "",
                f"📊 Итого за месяц:",
                f"📅 Недель с работой: {len(weeks_data)}",
                f"⏰ Всего отработано: {self.format_hours_minutes(total_month_hours)}",
                f"💰 Всего заработано: {total_month_earnings:.2f} руб"
            ])
        else:
            prev_month_name = self.get_russian_month_year(prev_month_first)
            response_lines = [f"📊 В {prev_month_name} нет записей о работе"]

        return "\n".join(response_lines)

    def generate_year_report(self, user_data: Dict[str, Any]) -> str:
        """Генерация отчета за год по месяцам"""
        current_year = datetime.now().year

        months_data = {}
        total_year_hours = 0
        total_year_earnings = 0

        for date_str, session in user_data["work_sessions"].items():
            try:
                session_date = datetime.strptime(date_str, "%Y-%m-%d")

                if session_date.year == current_year:
                    month_key = session_date.strftime("%Y-%m")

                    if month_key not in months_data:
                        months_data[month_key] = {
                            'hours': 0,
                            'earnings': 0,
                            'date_obj': session_date
                        }

                    months_data[month_key]['hours'] += session["total_hours"]
                    months_data[month_key]['earnings'] += session["total_earnings"]
                    total_year_hours += session["total_hours"]
                    total_year_earnings += session["total_earnings"]

            except ValueError:
                continue

        if months_data:
            response_lines = [f"📊 Заработок по месяцам в {current_year} году:\n"]

            sorted_months = sorted(months_data.items(), key=lambda x: x[1]['date_obj'])

            for month_key, data in sorted_months:
                month_name = self.get_russian_month_year(data['date_obj'])
                response_lines.append(
                    f"📅 {month_name}: {self.format_hours_minutes(data['hours'])} = {data['earnings']:.2f} руб"
                )

            response_lines.extend([
                "",
                f"📊 Итого за {current_year} год:",
                f"📅 Месяцев с работой: {len(months_data)}",
                f"⏰ Всего отработано: {self.format_hours_minutes(total_year_hours)}",
                f"💰 Всего заработано: {total_year_earnings:.2f} руб"
            ])
        else:
            response_lines = [f"📊 В {current_year} году нет записей о работе"]

        return "\n".join(response_lines)

    def get_user_clickup_client(self, user_id: str) -> Optional[ClickUpClient]:
        """Получение ClickUp клиента для конкретного пользователя"""
        settings = self.get_clickup_settings(user_id)
        api_token = settings.get("api_token")
        workspace_id = settings.get("workspace_id")
        if not api_token or not workspace_id:
            return None
        return ClickUpClient(api_token, workspace_id)

    async def validate_clickup_credentials(self, api_token: str, workspace_id: str) -> Dict[str, Any]:
        """Валидация ClickUp credentials и получение информации о пользователе"""
        try:
            client = ClickUpClient(api_token, workspace_id)
            team_id = await client.get_team_id()

            if not team_id:
                return {"success": False, "error": "Не удалось получить доступ к workspace"}

            user_info = await client.get_current_user()
            if not user_info:
                return {"success": False, "error": "Не удалось получить информацию о пользователе"}

            return {
                "success": True,
                "team_id": team_id,
                "user_id": user_info.get('id'),
                "username": user_info.get('username', user_info.get('email', 'Unknown'))
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def group_sessions_by_task(self, sessions: List[Dict]) -> Dict[str, Dict]:
        """Группировка сессий по названиям задач"""
        tasks = {}

        for session in sessions:
            task_name = "Ручная запись"

            if session.get("source") == "clickup":
                task_name = session.get("task_name", "Неизвестная задача")

            if task_name not in tasks:
                tasks[task_name] = {
                    "task_name": task_name,
                    "total_hours": 0,
                    "total_earnings": 0,
                    "sessions_count": 0,
                    "first_session": None,
                    "last_session": None,
                    "sessions": [],
                    "source_type": session.get("source", "manual")
                }

            task_data = tasks[task_name]
            session_hours = session.get("hours", 0) + session.get("minutes", 0) / 60
            session_earnings = session.get("earnings", 0)
            session_timestamp = session.get("timestamp")

            task_data["total_hours"] += session_hours
            task_data["total_earnings"] += session_earnings
            task_data["sessions_count"] += 1
            task_data["sessions"].append(session)

            if session_timestamp:
                if not task_data["first_session"] or session_timestamp < task_data["first_session"]:
                    task_data["first_session"] = session_timestamp
                if not task_data["last_session"] or session_timestamp > task_data["last_session"]:
                    task_data["last_session"] = session_timestamp

        return tasks

    def get_tasks_summary(self, user_id: str, start_date: datetime, end_date: datetime) -> Dict[str, Any]:
        """Получение сводки по задачам за указанный период"""
        user_data = self.get_user_data(user_id)

        all_sessions = []
        current_date = start_date

        while current_date <= end_date:
            date_str = current_date.strftime("%Y-%m-%d")
            if date_str in user_data["work_sessions"]:
                day_sessions = user_data["work_sessions"][date_str]["sessions"]
                for session in day_sessions:
                    session["date"] = date_str
                    all_sessions.append(session)
            current_date += timedelta(days=1)

        if not all_sessions:
            return {
                "tasks": {},
                "total_hours": 0,
                "total_earnings": 0,
                "total_tasks": 0,
                "total_sessions": 0,
                "period_start": start_date,
                "period_end": end_date
            }

        tasks_grouped = self.group_sessions_by_task(all_sessions)

        total_hours = sum(task["total_hours"] for task in tasks_grouped.values())
        total_earnings = sum(task["total_earnings"] for task in tasks_grouped.values())
        total_sessions = sum(task["sessions_count"] for task in tasks_grouped.values())

        return {
            "tasks": tasks_grouped,
            "total_hours": total_hours,
            "total_earnings": total_earnings,
            "total_tasks": len(tasks_grouped),
            "total_sessions": total_sessions,
            "period_start": start_date,
            "period_end": end_date
        }

    def get_days_breakdown(self, user_id: str, start_date: datetime, end_date: datetime) -> List[Dict[str, Any]]:
        """Разбивка по дням за период (для аналитики в вебапп)"""
        user_data = self.get_user_data(user_id)
        weekdays = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]

        days = []
        current = start_date.replace(hour=0, minute=0, second=0, microsecond=0)
        while current.date() <= end_date.date():
            date_str = current.strftime("%Y-%m-%d")
            hours = 0
            earnings = 0
            if date_str in user_data["work_sessions"]:
                session = user_data["work_sessions"][date_str]
                hours = session.get("total_hours", 0)
                earnings = session.get("total_earnings", 0)

            days.append({
                "date": date_str,
                "label": weekdays[current.weekday()],
                "sub": current.strftime("%d.%m"),
                "hours": hours,
                "earnings": earnings,
            })
            current += timedelta(days=1)

        return days

    def get_weeks_breakdown(self, user_id: str, start_date: datetime, end_date: datetime) -> List[Dict[str, Any]]:
        """Разбивка по календарным неделям за период (для аналитики в вебапп)"""
        user_data = self.get_user_data(user_id)

        weeks = []
        number = 1
        current_start = start_date.replace(hour=0, minute=0, second=0, microsecond=0)
        while current_start.date() <= end_date.date():
            # Неделя заканчивается в воскресенье, но не позже конца периода
            days_until_sunday = 6 - current_start.weekday()
            week_end = current_start + timedelta(days=days_until_sunday)
            if week_end.date() > end_date.date():
                week_end = end_date

            week_hours = 0
            week_earnings = 0
            day = current_start
            while day.date() <= week_end.date():
                date_str = day.strftime("%Y-%m-%d")
                if date_str in user_data["work_sessions"]:
                    session = user_data["work_sessions"][date_str]
                    week_hours += session.get("total_hours", 0)
                    week_earnings += session.get("total_earnings", 0)
                day += timedelta(days=1)

            weeks.append({
                "number": number,
                "label": f"Неделя {number}",
                "sub": f"{current_start.strftime('%d.%m')}–{week_end.strftime('%d.%m')}",
                "hours": week_hours,
                "earnings": week_earnings,
            })

            current_start = (week_end + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
            number += 1

        return weeks

    def get_months_breakdown(self, user_id: str, start_date: datetime, end_date: datetime) -> List[Dict[str, Any]]:
        """Разбивка по календарным месяцам за период (для аналитики в вебапп)"""
        user_data = self.get_user_data(user_id)
        month_names = [
            "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
            "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"
        ]

        months = []
        current = start_date.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        while current.date() <= end_date.date():
            # Первый день следующего месяца
            if current.month == 12:
                next_month = current.replace(year=current.year + 1, month=1)
            else:
                next_month = current.replace(month=current.month + 1)

            month_hours = 0
            month_earnings = 0
            for date_str, session in user_data["work_sessions"].items():
                try:
                    day = datetime.strptime(date_str, "%Y-%m-%d")
                except ValueError:
                    continue
                if current.date() <= day.date() < next_month.date() and start_date.date() <= day.date() <= end_date.date():
                    month_hours += session.get("total_hours", 0)
                    month_earnings += session.get("total_earnings", 0)

            months.append({
                "date": current.strftime("%Y-%m"),
                "label": month_names[current.month - 1],
                "sub": current.strftime("%Y"),
                "hours": month_hours,
                "earnings": month_earnings,
            })
            current = next_month

        return months

    def get_period_breakdown(self, user_id: str, start_date: datetime, end_date: datetime) -> Dict[str, Any]:
        """Выбор гранулярности разбивки по длине периода: дни / недели / месяцы"""
        span_days = (end_date.date() - start_date.date()).days
        if span_days <= 14:
            return {"type": "days", "items": self.get_days_breakdown(user_id, start_date, end_date)}
        if span_days <= 92:
            return {"type": "weeks", "items": self.get_weeks_breakdown(user_id, start_date, end_date)}
        return {"type": "months", "items": self.get_months_breakdown(user_id, start_date, end_date)}

    def format_task_summary(self, summary_data: Dict[str, Any]) -> str:
        """Форматирование сводки по задачам для отображения"""
        if not summary_data["tasks"]:
            return "📊 За указанный период задач не найдено"

        start_date = summary_data["period_start"]
        end_date = summary_data["period_end"]

        if start_date.date() == end_date.date():
            period_str = start_date.strftime("%d.%m.%Y")
        else:
            period_str = f"{start_date.strftime('%d.%m')} - {end_date.strftime('%d.%m.%Y')}"

        response_lines = [f"📊 Сводка по задачам за {period_str}:\n"]

        sorted_tasks = sorted(
            summary_data["tasks"].values(),
            key=lambda x: x["total_earnings"],
            reverse=True
        )

        for task in sorted_tasks:
            task_name = task["task_name"]
            total_hours = task["total_hours"]
            total_earnings = task["total_earnings"]
            sessions_count = task["sessions_count"]

            source_emoji = "🔗" if task["source_type"] == "clickup" else "✏️"

            response_lines.append(f"{source_emoji} {task_name}")
            response_lines.append(f"⏱️ Время: {self.format_hours_minutes(total_hours)} ({sessions_count} сессий)")
            response_lines.append(f"💰 Заработок: {total_earnings:.2f} руб")

            if task["first_session"] and task["last_session"]:
                first_date = datetime.fromisoformat(task["first_session"]).strftime("%d.%m")
                last_date = datetime.fromisoformat(task["last_session"]).strftime("%d.%m")
                if first_date == last_date:
                    response_lines.append(f"📅 Дата: {first_date}")
                else:
                    response_lines.append(f"📅 Период: {first_date} - {last_date}")

            response_lines.append("")

        response_lines.extend([
            "═══════════════════════════════════",
            f"📊 ИТОГО: {self.format_hours_minutes(summary_data['total_hours'])} = {summary_data['total_earnings']:.2f} руб",
            f"🎯 Задач: {summary_data['total_tasks']} | 📈 Сессий: {summary_data['total_sessions']}"
        ])

        return "\n".join(response_lines)

    def get_tasks_summary_by_period(self, period_type: str) -> tuple:
        """Унифицированная функция для определения периода и получения дат"""
        now = datetime.now()

        if period_type == "today":
            start_date = now.replace(hour=0, minute=0, second=0, microsecond=0)
            end_date = now
            period_name = "сегодня"
        elif period_type == "yesterday":
            yesterday = now - timedelta(days=1)
            start_date = yesterday.replace(hour=0, minute=0, second=0, microsecond=0)
            end_date = yesterday.replace(hour=23, minute=59, second=59)
            period_name = "вчера"
        elif period_type == "week":
            monday = now - timedelta(days=now.weekday())
            start_date = monday.replace(hour=0, minute=0, second=0, microsecond=0)
            end_date = now
            period_name = "неделю"
        elif period_type == "last_week":
            monday = now - timedelta(days=now.weekday())
            prev_monday = monday - timedelta(days=7)
            start_date = prev_monday.replace(hour=0, minute=0, second=0, microsecond=0)
            end_date = (prev_monday + timedelta(days=6)).replace(hour=23, minute=59, second=59, microsecond=0)
            period_name = "прошлую неделю"
        elif period_type == "month":
            start_date = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            end_date = now
            period_name = "месяц"
        elif period_type == "last_month":
            first_this_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            last_prev_month = first_this_month - timedelta(days=1)
            start_date = last_prev_month.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            end_date = last_prev_month.replace(hour=23, minute=59, second=59, microsecond=0)
            period_name = "прошлый месяц"
        elif period_type == "year":
            start_date = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
            end_date = now
            period_name = "год"
        elif period_type == "last_year":
            start_date = now.replace(year=now.year - 1, month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
            end_date = now.replace(year=now.year - 1, month=12, day=31, hour=23, minute=59, second=59, microsecond=0)
            period_name = "прошлый год"
        elif period_type == "7days":
            start_date = (now - timedelta(days=6)).replace(hour=0, minute=0, second=0, microsecond=0)
            end_date = now
            period_name = "последние 7 дней"
        elif period_type == "30days":
            start_date = (now - timedelta(days=29)).replace(hour=0, minute=0, second=0, microsecond=0)
            end_date = now
            period_name = "последние 30 дней"
        else:
            monday = now - timedelta(days=now.weekday())
            start_date = monday.replace(hour=0, minute=0, second=0, microsecond=0)
            end_date = now
            period_name = "неделю"

        return start_date, end_date, period_name

    @staticmethod
    def _entry_list_id(entry: Dict) -> Optional[str]:
        """Извлекает id списка (проекта) из записи времени ClickUp."""
        location = entry.get('task_location')
        list_id = location.get('list_id') if isinstance(location, dict) else None
        if not list_id:
            task = entry.get('task')
            nested = task.get('list') if isinstance(task, dict) else None
            list_id = nested.get('id') if isinstance(nested, dict) else None
        return str(list_id) if list_id else None

    async def _resolve_list_name(self, clickup_client, list_id: Optional[str], cache: Dict[str, str]) -> str:
        """Возвращает название списка (проекта) по его id, кэшируя результаты."""
        if not list_id:
            return ''
        if list_id in cache:
            return cache[list_id]
        name = ''
        list_info = await clickup_client.get_list(list_id)
        if list_info:
            name = list_info.get('name', '') or ''
        cache[list_id] = name
        return name

    async def sync_clickup_entries(self, user_id: str, start_date: datetime, end_date: datetime) -> Dict[str, Any]:
        """Синхронизация записей ClickUp с данными пользователя"""
        clickup_client = self.get_user_clickup_client(user_id)
        if not clickup_client:
            return {"success": False, "error": "ClickUp не настроен для этого пользователя"}

        user_data = self.get_user_data(user_id)
        list_name_cache: Dict[str, str] = {}

        try:
            clickup_entries = await clickup_client.get_time_entries(start_date, end_date)

            if not clickup_entries:
                return {"success": True, "synced_count": 0, "message": "Записи не найдены"}

            synced_count = 0
            total_hours = 0
            total_earnings = 0

            for entry in clickup_entries:
                entry_id = entry.get('id')
                duration_ms = int(entry.get('duration', 0))

                if duration_ms < 0:
                    continue

                if entry_id in user_data["clickup_synced_entries"]:
                    continue

                duration_hours = duration_ms / (1000 * 60 * 60)
                earnings = duration_hours * user_data["rate"]

                start_timestamp = int(entry.get('start', 0)) / 1000
                entry_date = datetime.fromtimestamp(start_timestamp).strftime("%Y-%m-%d")

                if entry_date not in user_data["work_sessions"]:
                    user_data["work_sessions"][entry_date] = {
                        "total_hours": 0,
                        "total_earnings": 0,
                        "sessions": []
                    }

                project_name = await self._resolve_list_name(
                    clickup_client, self._entry_list_id(entry), list_name_cache
                )

                clickup_session = {
                    "hours": int(duration_hours),
                    "minutes": int((duration_hours % 1) * 60),
                    "earnings": earnings,
                    "timestamp": datetime.fromtimestamp(start_timestamp).isoformat(),
                    "source": "clickup",
                    "clickup_id": entry_id,
                    "task_name": entry.get('task', {}).get('name', 'Неизвестная задача') if entry.get('task') else 'Без задачи',
                    "project_name": project_name,
                    "description": entry.get('description', '')
                }

                user_data["work_sessions"][entry_date]["sessions"].append(clickup_session)
                user_data["work_sessions"][entry_date]["total_hours"] += duration_hours
                user_data["work_sessions"][entry_date]["total_earnings"] += earnings

                user_data["clickup_synced_entries"].add(entry_id)

                synced_count += 1
                total_hours += duration_hours
                total_earnings += earnings

            self.save_data()

            return {
                "success": True,
                "synced_count": synced_count,
                "total_hours": total_hours,
                "total_earnings": total_earnings
            }

        except Exception as e:
            return {"success": False, "error": str(e)}

