import asyncio
import os
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from dotenv import load_dotenv
import logging

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton,
    MenuButtonWebApp, WebAppInfo
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

from clickup_client import ClickUpClient, retry_with_backoff
from data_manager import DataManager

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBAPP_URL = os.getenv("WEBAPP_URL", "")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class SalaryStates(StatesGroup):
    waiting_for_rate = State()
    waiting_for_clickup_token = State()
    waiting_for_workspace_id = State()
    waiting_for_digest_time = State()
    waiting_for_goal = State()
    waiting_for_bonus_amount = State()
    waiting_for_bonus_date = State()
    waiting_for_bonus_comment = State()


NOTIF_TOGGLE_FIELDS = {
    "daily": "notify_daily_digest",
    "weekly": "notify_weekly",
    "timer": "notify_long_timer",
    "autosync": "autosync_enabled",
}


def parse_bonus_date(value: str) -> Optional[str]:
    """ДД.ММ.ГГГГ или ГГГГ-ММ-ДД → 'YYYY-MM-DD'; None, если не дата."""
    value = (value or "").strip()
    for fmt in ("%d.%m.%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def valid_hhmm(value: str) -> bool:
    parts = value.split(":")
    if len(parts) != 2 or not all(p.isdigit() for p in parts):
        return False
    hours, minutes = int(parts[0]), int(parts[1])
    return 0 <= hours <= 23 and 0 <= minutes <= 59


def build_notifications_view(settings: Dict[str, Any]) -> tuple:
    """Текст и клавиатура экрана /notifications по текущим настройкам."""
    def mark(field):
        return "✅" if settings.get(field) else "❌"

    text = (
        "🔔 Настройки уведомлений и автосинка:\n\n"
        f"{mark('autosync_enabled')} Автосинк ClickUp (фоновый)\n"
        f"{mark('notify_daily_digest')} Вечерний дайджест в {settings.get('digest_time', '21:00')}\n"
        f"{mark('notify_weekly')} Недельная сводка (вс)\n"
        f"{mark('notify_long_timer')} Алерт «забытый таймер» "
        f"(> {settings.get('long_timer_hours', 4):g} ч)\n\n"
        "Нажмите, чтобы переключить:"
    )
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=f"{mark('autosync_enabled')} Автосинк",
            callback_data="notif_toggle_autosync")],
        [InlineKeyboardButton(
            text=f"{mark('notify_daily_digest')} Дайджест",
            callback_data="notif_toggle_daily")],
        [InlineKeyboardButton(
            text=f"{mark('notify_weekly')} Недельная сводка",
            callback_data="notif_toggle_weekly")],
        [InlineKeyboardButton(
            text=f"{mark('notify_long_timer')} Забытый таймер",
            callback_data="notif_toggle_timer")],
        [InlineKeyboardButton(
            text=f"🕘 Время дайджеста: {settings.get('digest_time', '21:00')}",
            callback_data="notif_digest_time")],
    ])
    return text, keyboard


class SalaryBot:
    def __init__(self, token: str):
        self.bot = Bot(token=token)
        self.dp = Dispatcher(storage=MemoryStorage())
        import migrate_to_sqlite
        migrate_to_sqlite.migrate()
        self.data_manager = DataManager()
        self.setup_handlers()

    def escape_markdown(self, text: str) -> str:
        """Экранирование специальных символов для Telegram Markdown"""
        if not text:
            return ""

        special_chars = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']

        escaped_text = text
        for char in special_chars:
            escaped_text = escaped_text.replace(char, f'\\{char}')

        return escaped_text

    def create_earnings_keyboard(self, current_report: str) -> InlineKeyboardMarkup:
        """Создание клавиатуры для переключения между отчетами о заработке"""
        keyboard = []

        row1 = []
        reports = [
            ("earnings_today", "📊 Сегодня" if current_report == "today" else "Сегодня"),
            ("earnings_yesterday", "📊 Вчера" if current_report == "yesterday" else "Вчера"),
            ("earnings_week", "📊 Неделя" if current_report == "week" else "Неделя"),
            ("earnings_month", "📊 Месяц" if current_report == "month" else "Месяц")
        ]

        for callback_data, text in reports:
            row1.append(InlineKeyboardButton(text=text, callback_data=callback_data))

        keyboard.append(row1[:2])
        keyboard.append(row1[2:])

        row2 = []
        detail_reports = [
            ("earnings_week_details", "📊 Неделя детально" if current_report == "week_details" else "Неделя детально"),
            ("earnings_month_weeks", "📊 Месяц по неделям" if current_report == "month_weeks" else "Месяц по неделям"),
            ("earnings_prev_month_weeks", "📊 Прошлый месяц" if current_report == "prev_month_weeks" else "Прошлый месяц"),
            ("earnings_year", "📊 Год" if current_report == "year" else "Год")
        ]

        for callback_data, text in detail_reports:
            row2.append(InlineKeyboardButton(text=text, callback_data=callback_data))

        keyboard.append(row2[:2])
        keyboard.append(row2[2:])

        return InlineKeyboardMarkup(inline_keyboard=keyboard)

    def create_tasks_analytics_keyboard(self, current_report: str) -> InlineKeyboardMarkup:
        """Создание клавиатуры для переключения между отчетами аналитики задач"""
        keyboard = []

        row1 = []
        reports = [
            ("tasks_summary_today", "📊 Сегодня" if current_report == "today" else "Сегодня"),
            ("tasks_summary_yesterday", "📊 Вчера" if current_report == "yesterday" else "Вчера"),
            ("tasks_summary_week", "📊 Неделя" if current_report == "week" else "Неделя"),
            ("tasks_summary_month", "📊 Месяц" if current_report == "month" else "Месяц")
        ]

        for callback_data, text in reports:
            row1.append(InlineKeyboardButton(text=text, callback_data=callback_data))

        keyboard.append(row1[:2])
        keyboard.append(row1[2:])

        row2 = []
        additional_reports = [
            ("tasks_summary_7days", "📊 7 дней" if current_report == "7days" else "7 дней"),
            ("tasks_summary_30days", "📊 30 дней" if current_report == "30days" else "30 дней")
        ]

        for callback_data, text in additional_reports:
            row2.append(InlineKeyboardButton(text=text, callback_data=callback_data))

        keyboard.append(row2)

        return InlineKeyboardMarkup(inline_keyboard=keyboard)

    async def send_earnings_report(self, message: Message, report_type: str, content: str, show_navigation: bool = True):
        """Универсальная функция для отправки отчетов о заработке с inline кнопками"""
        if show_navigation:
            keyboard = self.create_earnings_keyboard(report_type)
            await message.answer(content, reply_markup=keyboard)
        else:
            await message.answer(content)

    async def send_tasks_analytics_report(self, message: Message, report_type: str, content: str, show_navigation: bool = True):
        """Универсальная функция для отправки отчетов аналитики задач с inline кнопками"""
        if show_navigation:
            keyboard = self.create_tasks_analytics_keyboard(report_type)

            if len(content) > 4000:
                parts = content.split('\n\n')
                current_part = ""

                for part in parts:
                    if len(current_part + part + '\n\n') > 4000:
                        if current_part:
                            await message.answer(current_part)
                            current_part = part + '\n\n'
                        else:
                            await message.answer(part)
                    else:
                        current_part += part + '\n\n'

                if current_part:
                    await message.answer(current_part, reply_markup=keyboard)
                else:
                    await message.answer("📊 Навигация:", reply_markup=keyboard)
            else:
                await message.answer(content, reply_markup=keyboard)
        else:
            await message.answer(content)

    def create_task_keyboard(self, task_data: Dict) -> InlineKeyboardMarkup:
        """Создание inline клавиатуры для задачи"""
        task_id = task_data.get('id')
        current_status = task_data.get('status', {}).get('status', '').lower()

        keyboard = []

        row1 = [
            InlineKeyboardButton(text="📋 Инфо", callback_data=f"task_info_{task_id}"),
        ]

        row1.append(InlineKeyboardButton(text="⏱️ Старт", callback_data=f"timer_start_{task_id}"))
        row1.append(InlineKeyboardButton(text="⏹️ Стоп", callback_data=f"timer_stop_{task_id}"))

        keyboard.append(row1)

        status_buttons = []

        statuses = [
            ("open", "📂 Open"),
            ("in progress", "🔄 Progress"),
            ("review", "👀 Review"),
            ("done", "✅ Done"),
            ("complete", "🏁 Complete")
        ]

        for status_key, status_label in statuses:
            if current_status != status_key:
                status_buttons.append(
                    InlineKeyboardButton(text=status_label, callback_data=f"task_status_{status_key}_{task_id}")
                )

        for i in range(0, len(status_buttons), 2):
            keyboard.append(status_buttons[i:i + 2])

        return InlineKeyboardMarkup(inline_keyboard=keyboard)

    def group_tasks_by_project(self, tasks: List[Dict]) -> Dict[str, List[Dict]]:
        """Группировка задач по проектам"""
        grouped = {}

        for task in tasks:
            project_name = task.get('project_name', 'Неизвестный проект')

            if project_name not in grouped:
                grouped[project_name] = []

            grouped[project_name].append(task)

        return grouped

    def format_task_info(self, task_data: Dict) -> str:
        """Форматирование подробной информации о задаче"""
        name = task_data.get('name', 'Без названия')
        description = task_data.get('description', 'Описание отсутствует')
        status = task_data.get('status', {}).get('status', 'Неизвестен')
        project = task_data.get('project_name', 'Неизвестный проект')
        list_name = task_data.get('list_name', 'Неизвестный список')

        assignees = task_data.get('assignees', [])
        assignee_names = [assignee.get('username', 'Unknown') for assignee in assignees]
        assignee_text = ', '.join(assignee_names) if assignee_names else 'Не назначен'

        due_date = task_data.get('due_date')
        due_text = "Не установлен"
        if due_date:
            try:
                due_timestamp = int(due_date) / 1000
                due_datetime = datetime.fromtimestamp(due_timestamp)
                due_text = due_datetime.strftime('%d.%m.%Y %H:%M')
            except Exception:
                due_text = "Некорректная дата"

        task_url = task_data.get('url', '')

        escaped_name = self.escape_markdown(name)
        escaped_status = self.escape_markdown(status)
        escaped_project = self.escape_markdown(project)
        escaped_list_name = self.escape_markdown(list_name)
        escaped_assignee_text = self.escape_markdown(assignee_text)
        escaped_due_text = self.escape_markdown(due_text)

        info_text = (
            f"📋 *{escaped_name}*\n\n"
            f"📊 *Статус:* {escaped_status}\n"
            f"🏗 *Проект:* {escaped_project}\n"
            f"📁 *Список:* {escaped_list_name}\n"
            f"👤 *Исполнитель:* {escaped_assignee_text}\n"
            f"⏰ *Дедлайн:* {escaped_due_text}\n\n"
        )

        if description and description.strip():
            if len(description) > 200:
                description = description[:200] + "..."
            escaped_description = self.escape_markdown(description)
            info_text += f"📝 *Описание:*\n{escaped_description}\n\n"

        if task_url:
            info_text += f"🔗 [Открыть в ClickUp]({task_url})"

        return info_text

    def get_available_statuses(self) -> List[Dict[str, str]]:
        """Получение списка доступных статусов"""
        return [
            {"key": "all", "name": "🔄 Все", "emoji": "🔄"},
            {"key": "open", "name": "📂 Open", "emoji": "📂"},
            {"key": "in progress", "name": "🔄 In Progress", "emoji": "🔄"},
            {"key": "review", "name": "👀 Review", "emoji": "👀"},
            {"key": "done", "name": "✅ Done", "emoji": "✅"},
            {"key": "complete", "name": "🏁 Complete", "emoji": "🏁"}
        ]

    def filter_tasks_by_status(self, tasks: List[Dict], status_key: str) -> List[Dict]:
        """Фильтрация задач по статусу"""
        logger.info(f"=== ФИЛЬТРАЦИЯ ЗАДАЧ ПО СТАТУСУ ===")
        logger.info(f"Ищем статус: '{status_key}'")
        logger.info(f"Всего задач для фильтрации: {len(tasks)}")

        if status_key == "all":
            return tasks

        filtered_tasks = []

        for i, task in enumerate(tasks):
            task_status_obj = task.get('status', {})
            task_status_name = task_status_obj.get('status', '')
            task_name = task.get('name', 'Без названия')[:50]

            logger.info(f"Задача {i + 1}: '{task_name}' имеет статус: '{task_status_name}'")

            if task_status_name.lower() == status_key.lower():
                filtered_tasks.append(task)
                logger.info(f"  ✅ Задача соответствует фильтру!")
            else:
                logger.info(f"  ❌ Не соответствует: '{task_status_name.lower()}' != '{status_key.lower()}'")

        logger.info(f"Результат фильтрации: найдено {len(filtered_tasks)} из {len(tasks)} задач")

        return filtered_tasks

    async def send_task_with_navigation(self, message, tasks: List[Dict], current_index: int, list_id: str, space_id: str = None, folder_id: str = None):
        """Отправка задачи с навигационными кнопками"""
        if not tasks or current_index >= len(tasks):
            await message.answer("❌ Нет задач для отображения")
            return

        task = tasks[current_index]
        task_name = task.get('name', 'Без названия')
        task_status = task.get('status', {}).get('status', 'Неизвестен')

        assignees = task.get('assignees', [])
        if assignees:
            assignee_name = assignees[0].get('username', 'Неизвестный')
        else:
            assignee_name = 'Не назначен'

        due_date = task.get('due_date')
        due_text = "Не установлен"
        if due_date:
            try:
                due_timestamp = int(due_date) / 1000
                due_datetime = datetime.fromtimestamp(due_timestamp)
                due_text = due_datetime.strftime('%d.%m.%Y')
            except Exception:
                due_text = "Некорректная дата"

        escaped_name = self.escape_markdown(task_name)
        escaped_status = self.escape_markdown(task_status)
        escaped_assignee = self.escape_markdown(assignee_name)
        escaped_due = self.escape_markdown(due_text)

        task_text = (
            f"📋 *{escaped_name}*\n"
            f"📊 Статус: {escaped_status}\n"
            f"👤 Исполнитель: {escaped_assignee}\n"
            f"⏰ Дедлайн: {escaped_due}\n\n"
            f"Задача {current_index + 1} из {len(tasks)}"
        )

        keyboard = self.create_task_navigation_keyboard(tasks, current_index, list_id, space_id, folder_id)

        await message.answer(
            task_text,
            reply_markup=keyboard,
            parse_mode="Markdown"
        )

    def create_task_navigation_keyboard(self, tasks: List[Dict], current_index: int, list_id: str, space_id: str = None, folder_id: str = None) -> InlineKeyboardMarkup:
        """Создание клавиатуры с навигацией по задачам"""
        task = tasks[current_index]
        task_id = task.get('id')
        keyboard = []

        nav_row = []
        if len(tasks) > 1:
            prev_index = (current_index - 1) % len(tasks)
            nav_row.append(InlineKeyboardButton(
                text="◀️ Пред",
                callback_data=f"task_nav_prev_{list_id}_{current_index}_{prev_index}"
            ))

        nav_row.append(InlineKeyboardButton(
            text="📋 Инфо",
            callback_data=f"task_info_{task_id}"
        ))

        if len(tasks) > 1:
            next_index = (current_index + 1) % len(tasks)
            nav_row.append(InlineKeyboardButton(
                text="▶️ След",
                callback_data=f"task_nav_next_{list_id}_{current_index}_{next_index}"
            ))

        keyboard.append(nav_row)

        timer_row = [
            InlineKeyboardButton(text="⏱️ Старт", callback_data=f"timer_start_{task_id}"),
            InlineKeyboardButton(text="⏹️ Стоп", callback_data=f"timer_stop_{task_id}")
        ]
        keyboard.append(timer_row)

        status_row = [
            InlineKeyboardButton(text="🔄 Статус", callback_data=f"task_status_change_{task_id}")
        ]
        keyboard.append(status_row)

        if folder_id:
            back_callback = f"folder_select_{space_id}_{folder_id}"
            back_text = "🔙 К спискам"
        elif space_id:
            back_callback = f"space_select_{space_id}"
            back_text = "🔙 К папкам"
        else:
            back_callback = f"back_to_lists"
            back_text = "🔙 Назад"

        back_row = [
            InlineKeyboardButton(
                text=back_text,
                callback_data=back_callback
            )
        ]
        keyboard.append(back_row)

        return InlineKeyboardMarkup(inline_keyboard=keyboard)

    async def update_task_navigation(self, message, tasks: List[Dict], current_index: int, list_id: str):
        """Обновление сообщения с задачей при навигации"""
        if not tasks or current_index >= len(tasks):
            await message.edit_text("❌ Нет задач для отображения")
            return

        task = tasks[current_index]
        task_name = task.get('name', 'Без названия')
        task_status = task.get('status', {}).get('status', 'Неизвестен')

        assignees = task.get('assignees', [])
        if assignees:
            assignee_name = assignees[0].get('username', 'Неизвестный')
        else:
            assignee_name = 'Не назначен'

        due_date = task.get('due_date')
        due_text = "Не установлен"
        if due_date:
            try:
                due_timestamp = int(due_date) / 1000
                due_datetime = datetime.fromtimestamp(due_timestamp)
                due_text = due_datetime.strftime('%d.%m.%Y')
            except Exception:
                due_text = "Некорректная дата"

        escaped_name = self.escape_markdown(task_name)
        escaped_status = self.escape_markdown(task_status)
        escaped_assignee = self.escape_markdown(assignee_name)
        escaped_due = self.escape_markdown(due_text)

        task_text = (
            f"📋 *{escaped_name}*\n"
            f"📊 Статус: {escaped_status}\n"
            f"👤 Исполнитель: {escaped_assignee}\n"
            f"⏰ Дедлайн: {escaped_due}\n\n"
            f"Задача {current_index + 1} из {len(tasks)}"
        )

        keyboard = self.create_task_navigation_keyboard(tasks, current_index, list_id)

        await message.edit_text(
            task_text,
            reply_markup=keyboard,
            parse_mode="Markdown"
        )

    def month_report_with_bonuses(self, user_id: str) -> str:
        """Месячный отчёт с премиями и целью (единый для /month и inline-кнопок)."""
        progress = self.data_manager.get_month_progress(user_id)
        return self.data_manager.generate_month_report(
            self.data_manager.get_work_sessions(user_id),
            bonus_total=progress["bonus_earnings"],
            goal=progress["goal"],
        )

    async def _set_goal_from_text(self, message: Message, user_id: str, text: str) -> bool:
        try:
            goal = float(text.strip().replace(",", "."))
        except ValueError:
            await message.answer("❌ Введите число, например 250000")
            return False
        if goal < 0:
            await message.answer("❌ Цель не может быть отрицательной")
            return False
        self.data_manager.set_monthly_goal(user_id, goal)
        if goal == 0:
            await message.answer("✅ Цель месяца убрана")
        else:
            progress = self.data_manager.get_month_progress(user_id)
            await message.answer(
                f"✅ Цель месяца: {goal:.0f} руб\n"
                f"💰 Уже набрано: {progress['total']:.0f} руб ({progress['percent']}%)"
            )
        return True

    async def _ask_bonus_comment(self, message: Message, state: FSMContext):
        keyboard = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="⏭ Пропустить", callback_data="bonus_skip_comment")
        ]])
        await message.answer("💬 Комментарий к премии (например, «Q2»):", reply_markup=keyboard)
        await state.set_state(SalaryStates.waiting_for_bonus_comment)

    async def _save_bonus(self, message: Message, user_id: str, state: FSMContext,
                          comment: Optional[str]):
        data = await state.get_data()
        amount, date_str = data["bonus_amount"], data["bonus_date"]
        self.data_manager.add_bonus(user_id, date_str, amount, comment)
        await state.clear()
        date_h = datetime.strptime(date_str, "%Y-%m-%d").strftime("%d.%m.%Y")
        comment_line = f"\n💬 {comment}" if comment else ""
        await message.answer(
            f"✅ Премия добавлена: {amount:.0f} руб, {date_h}{comment_line}\n\n"
            f"Список премий: /bonuses"
        )

    def setup_handlers(self):
        """Настройка обработчиков команд"""

        @self.dp.message(Command("start"))
        async def start_command(message: Message, state: FSMContext):
            user_id = str(message.from_user.id)
            rate = self.data_manager.get_rate(user_id)

            welcome_text = (
                "🎯 Добро пожаловать в бота для подсчета зарплаты!\n\n"
                "Этот бот поможет вам отслеживать рабочее время и рассчитывать заработок.\n\n"
                "📋 Основные команды:\n"
                "/setrate - установить ставку (руб/час)\n"
                "/today - заработок за сегодня\n"
                "/yesterday - заработок за вчера\n"
                "/week - заработок за неделю (с понедельника)\n"
                "/weekdetails - детальный заработок по дням недели\n"
                "/month - заработок за месяц\n"
                "/monthweeks - заработок по неделям в месяце\n"
                "/year - заработок по месяцам в году\n\n"
                "🔗 ClickUp интеграция:\n"
                "/clickup_setup - настроить интеграцию с ClickUp\n"
                "/syncclickup - синхронизировать данные за сегодня\n"
                "/synclast - синхронизировать за последние дни\n"
                "/clickupstatus - статус интеграции\n\n"
                "📊 Аналитика:\n"
                "/tasksummary - сводка по задачам за неделю\n\n"
                "🎯 Управление задачами:\n"
                "/tasks - список задач по проектам\n"
                "/active_task - просмотр активной задачи\n\n"
                "/help - показать полную справку\n\n"
            )

            if rate > 0:
                welcome_text += f"💰 Ваша текущая ставка: {rate} руб/час"
            else:
                welcome_text += "⚠️ Сначала установите свою ставку командой /setrate"

            if WEBAPP_URL:
                welcome_text += "\n\n🌐 Telegram Mini App: /app"

            await message.answer(welcome_text)

        @self.dp.message(Command("app"))
        async def app_command(message: Message):
            if not WEBAPP_URL:
                await message.answer("WEBAPP_URL не настроен")
                return
            kb = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="Открыть приложение", web_app=WebAppInfo(url=WEBAPP_URL))
            ]])
            await message.answer("Открыть приложение:", reply_markup=kb)

        @self.dp.message(Command("help"))
        async def help_command(message: Message):
            help_text = (
                "📋 Справка по командам:\n\n"
                "🏠 Основные команды:\n"
                "/start - главное меню\n"
                "/setrate - установить ставку (руб/час)\n"
                "/goal [сумма] - цель заработка на месяц\n"
                "/bonus - добавить премию\n"
                "/bonuses - список премий за год\n"
                "/today - заработок за сегодня\n"
                "/yesterday - заработок за вчера\n"
                "/week - заработок за неделю (с понедельника)\n"
                "/weekdetails - детальный заработок по дням недели\n"
                "/month - заработок за месяц\n"
                "/monthweeks - заработок по неделям в месяце\n"
                "/year - заработок по месяцам в году\n\n"
                "🔗 ClickUp интеграция:\n"
                "/clickup_setup - пошаговая настройка ClickUp\n"
                "/clickup_token - установить Personal API Token\n"
                "/clickup_workspace - установить Workspace ID\n"
                "/clickup_reset - сбросить настройки ClickUp\n"
                "/syncclickup - синхронизировать данные за сегодня\n"
                "/synclast [дни] - синхронизировать за последние N дней (по умолчанию 7)\n"
                "/clickupstatus - статус интеграции и активные таймеры\n"
                "/notifications - автосинк и уведомления (дайджест, сводка, забытый таймер)\n\n"
                "📊 Аналитика задач:\n"
                "/tasksummary - сводка по задачам за неделю\n"
                "/tasksummary today - сводка за сегодня\n"
                "/tasksummary month - сводка за месяц\n"
                "/tasksummary 7 - сводка за последние 7 дней\n\n"
                "🎯 Управление задачами:\n"
                "/tasks - просмотр всех задач с возможностью управления\n"
                "/active_task - информация об активной задаче с таймером\n\n"
                "💡 Для добавления времени используйте формат: ЧАСЫ МИНУТЫ\n"
                "Например: 8 30 (означает 8 часов 30 минут)\n\n"
                "🔄 ClickUp синхронизация автоматически объединяет данные из ClickUp с вашими ручными записями.\n"
                "Каждый пользователь может настроить свои собственные ClickUp credentials."
            )
            await message.answer(help_text)

        @self.dp.message(Command("setrate"))
        async def set_rate_command(message: Message, state: FSMContext):
            await message.answer("💰 Введите вашу ставку в рублях за час:")
            await state.set_state(SalaryStates.waiting_for_rate)

        @self.dp.message(SalaryStates.waiting_for_rate)
        async def process_rate(message: Message, state: FSMContext):
            try:
                rate = float(message.text)
                if rate <= 0:
                    await message.answer("❌ Ставка должна быть положительным числом!")
                    return

                user_id = str(message.from_user.id)
                self.data_manager.set_rate(user_id, rate)

                await message.answer(f"✅ Ставка установлена: {rate} руб/час")
                await state.clear()

            except ValueError:
                await message.answer("❌ Пожалуйста, введите корректное число!")

        @self.dp.message(Command("goal"))
        async def goal_command(message: Message, state: FSMContext):
            user_id = str(message.from_user.id)
            parts = (message.text or "").split(maxsplit=1)
            if len(parts) == 2:
                await self._set_goal_from_text(message, user_id, parts[1])
                return
            progress = self.data_manager.get_month_progress(user_id)
            if progress["goal"] > 0:
                await message.answer(
                    f"🎯 Цель месяца: {progress['goal']:.0f} руб\n"
                    f"💰 Набрано: {progress['total']:.0f} руб ({progress['percent']}%)\n"
                    f"⏳ Осталось: {progress['remaining']:.0f} руб, "
                    f"дней до конца месяца: {progress['days_left']}\n\n"
                    "Введите новую цель в рублях (0 — убрать цель):"
                )
            else:
                await message.answer("🎯 Цель месяца не задана.\nВведите цель в рублях:")
            await state.set_state(SalaryStates.waiting_for_goal)

        @self.dp.message(SalaryStates.waiting_for_goal)
        async def process_goal(message: Message, state: FSMContext):
            user_id = str(message.from_user.id)
            if await self._set_goal_from_text(message, user_id, message.text or ""):
                await state.clear()

        @self.dp.message(Command("bonus"))
        async def bonus_command(message: Message, state: FSMContext):
            await message.answer("🎁 Введите сумму премии в рублях:")
            await state.set_state(SalaryStates.waiting_for_bonus_amount)

        @self.dp.message(SalaryStates.waiting_for_bonus_amount)
        async def process_bonus_amount(message: Message, state: FSMContext):
            try:
                amount = float((message.text or "").replace(",", "."))
            except ValueError:
                await message.answer("❌ Введите число, например 30000")
                return
            if amount <= 0:
                await message.answer("❌ Сумма должна быть положительной")
                return
            await state.update_data(bonus_amount=amount)
            keyboard = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="📅 Сегодня", callback_data="bonus_date_today")
            ]])
            await message.answer(
                "📅 Введите дату премии (ДД.ММ.ГГГГ) или нажмите кнопку:",
                reply_markup=keyboard,
            )
            await state.set_state(SalaryStates.waiting_for_bonus_date)

        @self.dp.callback_query(F.data == "bonus_date_today", SalaryStates.waiting_for_bonus_date)
        async def bonus_date_today(callback: CallbackQuery, state: FSMContext):
            await state.update_data(bonus_date=datetime.now().strftime("%Y-%m-%d"))
            await self._ask_bonus_comment(callback.message, state)
            await callback.answer()

        @self.dp.message(SalaryStates.waiting_for_bonus_date)
        async def process_bonus_date(message: Message, state: FSMContext):
            date_str = parse_bonus_date(message.text or "")
            if not date_str:
                await message.answer("❌ Неверная дата. Формат: ДД.ММ.ГГГГ, например 05.07.2026")
                return
            await state.update_data(bonus_date=date_str)
            await self._ask_bonus_comment(message, state)

        @self.dp.callback_query(F.data == "bonus_skip_comment", SalaryStates.waiting_for_bonus_comment)
        async def bonus_skip_comment(callback: CallbackQuery, state: FSMContext):
            await self._save_bonus(callback.message, str(callback.from_user.id), state, None)
            await callback.answer()

        @self.dp.message(SalaryStates.waiting_for_bonus_comment)
        async def process_bonus_comment(message: Message, state: FSMContext):
            comment = (message.text or "").strip() or None
            await self._save_bonus(message, str(message.from_user.id), state, comment)

        @self.dp.message(Command("bonuses"))
        async def bonuses_command(message: Message):
            user_id = str(message.from_user.id)
            year = datetime.now().year
            bonuses = self.data_manager.get_bonuses(
                user_id, start_date=f"{year}-01-01", end_date=f"{year}-12-31"
            )
            if not bonuses:
                await message.answer(f"🎁 В {year} году премий пока нет. Добавить: /bonus")
                return
            total = sum(b["amount"] for b in bonuses)
            lines = [f"🎁 Премии за {year} год (итого {total:.0f} руб):\n"]
            keyboard_rows = []
            for b in bonuses:
                date_h = datetime.strptime(b["date"], "%Y-%m-%d").strftime("%d.%m.%Y")
                comment = f" — {b['comment']}" if b["comment"] else ""
                lines.append(f"• {date_h}: {b['amount']:.0f} руб{comment}")
                keyboard_rows.append([InlineKeyboardButton(
                    text=f"🗑 Удалить {date_h} ({b['amount']:.0f} руб)",
                    callback_data=f"bonus_del_{b['id']}",
                )])
            await message.answer(
                "\n".join(lines),
                reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard_rows),
            )

        @self.dp.callback_query(F.data.startswith("bonus_del_"))
        async def bonus_delete_callback(callback: CallbackQuery):
            user_id = str(callback.from_user.id)
            bonus_id = int(callback.data.removeprefix("bonus_del_"))
            if self.data_manager.delete_bonus(user_id, bonus_id):
                await callback.answer("Премия удалена")
                await callback.message.edit_text(
                    callback.message.text + "\n\n🗑 Премия удалена. Обновить список: /bonuses"
                )
            else:
                await callback.answer("Премия не найдена", show_alert=True)

        @self.dp.message(Command("notifications"))
        async def notifications_command(message: Message):
            user_id = str(message.from_user.id)
            settings = self.data_manager.get_notification_settings(user_id)
            text, keyboard = build_notifications_view(settings)
            await message.answer(text, reply_markup=keyboard)

        @self.dp.callback_query(F.data.startswith("notif_toggle_"))
        async def notif_toggle_callback(callback: CallbackQuery):
            user_id = str(callback.from_user.id)
            key = callback.data.removeprefix("notif_toggle_")
            field = NOTIF_TOGGLE_FIELDS.get(key)
            if not field:
                await callback.answer()
                return
            settings = self.data_manager.get_notification_settings(user_id)
            self.data_manager.set_notification_settings(
                user_id, **{field: 0 if settings.get(field) else 1}
            )
            settings = self.data_manager.get_notification_settings(user_id)
            text, keyboard = build_notifications_view(settings)
            await callback.message.edit_text(text, reply_markup=keyboard)
            await callback.answer()

        @self.dp.callback_query(F.data == "notif_digest_time")
        async def notif_digest_time_callback(callback: CallbackQuery, state: FSMContext):
            await callback.message.answer(
                "🕘 Введите время дайджеста в формате ЧЧ:ММ (например, 21:00):"
            )
            await state.set_state(SalaryStates.waiting_for_digest_time)
            await callback.answer()

        @self.dp.message(SalaryStates.waiting_for_digest_time)
        async def process_digest_time(message: Message, state: FSMContext):
            value = (message.text or "").strip()
            if not valid_hhmm(value):
                await message.answer("❌ Неверный формат. Введите время как ЧЧ:ММ, например 21:00")
                return
            user_id = str(message.from_user.id)
            hours, minutes = value.split(":")
            normalized = f"{int(hours):02d}:{int(minutes):02d}"
            self.data_manager.set_notification_settings(user_id, digest_time=normalized)
            await state.clear()
            settings = self.data_manager.get_notification_settings(user_id)
            text, keyboard = build_notifications_view(settings)
            await message.answer(f"✅ Время дайджеста: {normalized}")
            await message.answer(text, reply_markup=keyboard)

        @self.dp.message(Command("clickup_setup"))
        async def clickup_setup_command(message: Message):
            await message.answer(
                "🔗 Настройка ClickUp интеграции\n\n"
                "Для настройки интеграции с ClickUp вам понадобится:\n"
                "1️⃣ Personal API Token\n"
                "2️⃣ Workspace ID\n\n"
                "📋 Пошаговая инструкция:\n"
                "1. Откройте ClickUp в браузере\n"
                "2. Нажмите на аватар → Settings → Apps\n"
                "3. Нажмите 'Generate' для создания Personal API Token\n"
                "4. Скопируйте токен и отправьте командой /clickup_token\n"
                "5. Найдите Workspace ID в URL (цифры после /team/)\n"
                "6. Отправьте Workspace ID командой /clickup_workspace\n\n"
                "💡 После настройки используйте /clickupstatus для проверки"
            )

        @self.dp.message(Command("clickup_token"))
        async def clickup_token_command(message: Message, state: FSMContext):
            await message.answer("🔑 Отправьте ваш Personal API Token из ClickUp:\n\n"
                                 "Токен должен начинаться с 'pk_' и содержать цифры и буквы.\n"
                                 "Пример: pk_12345_ABCDEFGHIJK...")
            await state.set_state(SalaryStates.waiting_for_clickup_token)

        @self.dp.message(SalaryStates.waiting_for_clickup_token)
        async def process_clickup_token(message: Message, state: FSMContext):
            token = message.text.strip()

            if not token.startswith('pk_') or len(token) < 20:
                await message.answer("❌ Неверный формат токена! Токен должен начинаться с 'pk_' и содержать не менее 20 символов.")
                return

            user_id = str(message.from_user.id)
            self.data_manager.set_clickup_settings(user_id, api_token=token)

            await message.answer("✅ API Token сохранен!\n\n"
                                 "Теперь отправьте Workspace ID командой /clickup_workspace")
            await state.clear()

        @self.dp.message(Command("clickup_workspace"))
        async def clickup_workspace_command(message: Message, state: FSMContext):
            await message.answer("🏢 Отправьте ваш Workspace ID из ClickUp:\n\n"
                                 "Это числовой ID, который можно найти в URL ClickUp.\n"
                                 "Пример: 9015893221")
            await state.set_state(SalaryStates.waiting_for_workspace_id)

        @self.dp.message(SalaryStates.waiting_for_workspace_id)
        async def process_workspace_id(message: Message, state: FSMContext):
            workspace_id = message.text.strip()

            if not workspace_id.isdigit() or len(workspace_id) < 8:
                await message.answer("❌ Неверный формат Workspace ID! ID должен содержать только цифры и быть не менее 8 символов.")
                return

            user_id = str(message.from_user.id)

            api_token = self.data_manager.get_clickup_settings(user_id).get("api_token")
            if not api_token:
                await message.answer("❌ Сначала установите API токен командой /clickup_token")
                return

            await message.answer("🔄 Проверяю подключение к ClickUp...")

            validation_result = await self.data_manager.validate_clickup_credentials(api_token, workspace_id)

            if validation_result["success"]:
                self.data_manager.set_clickup_settings(
                    user_id,
                    workspace_id=workspace_id,
                    team_id=validation_result["team_id"],
                    user_id=validation_result["user_id"],
                    username=validation_result["username"],
                )

                await message.answer(f"✅ ClickUp интеграция настроена успешно!\n\n"
                                     f"👤 Пользователь: {validation_result['username']}\n"
                                     f"🏢 Team ID: {validation_result['team_id']}\n\n"
                                     f"Теперь вы можете использовать:\n"
                                     f"/tasks - управление задачами\n"
                                     f"/active_task - активная задача\n"
                                     f"/syncclickup - синхронизация за сегодня\n"
                                     f"/synclast - синхронизация за последние дни")
            else:
                await message.answer(f"❌ Ошибка подключения: {validation_result['error']}\n\n"
                                     f"Проверьте правильность API токена и Workspace ID.")

            await state.clear()

        @self.dp.message(Command("clickup_reset"))
        async def clickup_reset_command(message: Message):
            user_id = str(message.from_user.id)
            self.data_manager.clear_clickup_settings(user_id)

            await message.answer("🗑 Настройки ClickUp сброшены.\n\n"
                                 "Для повторной настройки используйте /clickup_setup")

        @self.dp.message(Command("clickup_refresh"))
        async def clickup_refresh_command(message: Message):
            user_id = str(message.from_user.id)
            clickup_client = self.data_manager.get_user_clickup_client(user_id)

            if not clickup_client:
                await message.answer("❌ ClickUp не настроен для вашего аккаунта\n\nИспользуйте /clickup_setup для настройки")
                return

            await message.answer("🔄 Обновляю информацию о пользователе ClickUp...")

            try:
                current_user = await clickup_client.get_current_user()

                if not current_user or not current_user.get('id'):
                    await message.answer("❌ Не удалось получить информацию о пользователе из ClickUp API\n\n"
                                         "Проверьте:\n"
                                         "• Корректность API токена\n"
                                         "• Доступ к интернету\n"
                                         "• Статус ClickUp API")
                    return

                self.data_manager.set_clickup_settings(
                    user_id,
                    user_id=current_user.get('id'),
                    username=current_user.get('username', current_user.get('email', 'Unknown')),
                )

                await message.answer(f"✅ Информация о пользователе обновлена!\n\n"
                                     f"👤 Имя пользователя: {self.data_manager.get_clickup_settings(user_id)['username']}\n"
                                     f"🆔 User ID: {current_user.get('id')}\n\n"
                                     f"Теперь команда /tasks будет показывать только ваши задачи.")

            except Exception as e:
                logger.error(f"Ошибка при обновлении информации о пользователе: {e}")
                await message.answer(f"❌ Ошибка обновления: {str(e)}\n\n"
                                     f"Попробуйте позже или обратитесь к администратору.")

        @self.dp.message(Command("tasksummary"))
        async def task_summary_command(message: Message):
            user_id = str(message.from_user.id)
            rate = self.data_manager.get_rate(user_id)

            if rate <= 0:
                await message.answer("❌ Сначала установите ставку командой /setrate")
                return

            command_parts = message.text.strip().split()
            period = "week"

            if len(command_parts) > 1:
                period_arg = command_parts[1].lower()
                if period_arg.isdigit():
                    days = int(period_arg)
                    if days <= 0 or days > 365:
                        await message.answer("❌ Количество дней должно быть от 1 до 365")
                        return
                    if days == 7:
                        period = "7days"
                    elif days == 30:
                        period = "30days"
                    else:
                        now = datetime.now()
                        start_date = (now - timedelta(days=days - 1)).replace(hour=0, minute=0, second=0, microsecond=0)
                        end_date = now
                        period_name = f"последние {days} дней"

                        await message.answer(f"📊 Анализирую задачи за {period_name}...")
                        summary = self.data_manager.get_tasks_summary(user_id, start_date, end_date)
                        formatted_summary = self.data_manager.format_task_summary(summary)
                        await self.send_tasks_analytics_report(message, "custom", formatted_summary, show_navigation=False)
                        return
                else:
                    period = period_arg

            try:
                start_date, end_date, period_name = self.data_manager.get_tasks_summary_by_period(period)
            except Exception:
                await message.answer("❌ Неверный период. Используйте: today, yesterday, week, month или число дней\n\n"
                                     "Примеры:\n"
                                     "/tasksummary - за неделю\n"
                                     "/tasksummary today - за сегодня\n"
                                     "/tasksummary month - за месяц\n"
                                     "/tasksummary 7 - за последние 7 дней")
                return

            await message.answer(f"📊 Анализирую задачи за {period_name}...")

            summary = self.data_manager.get_tasks_summary(user_id, start_date, end_date)

            formatted_summary = self.data_manager.format_task_summary(summary)
            await self.send_tasks_analytics_report(message, period, formatted_summary)

        @self.dp.message(Command("syncclickup"))
        async def sync_clickup_command(message: Message):
            user_id = str(message.from_user.id)
            rate = self.data_manager.get_rate(user_id)

            if not self.data_manager.get_user_clickup_client(user_id):
                await message.answer("❌ ClickUp не настроен для вашего аккаунта\n\nИспользуйте /clickup_setup для настройки")
                return

            if rate <= 0:
                await message.answer("❌ Сначала установите ставку командой /setrate")
                return

            await message.answer("🔄 Синхронизирую данные ClickUp за сегодня...")

            today = datetime.now()
            start_of_today = today.replace(hour=0, minute=0, second=0, microsecond=0)

            result = await self.data_manager.sync_clickup_entries(user_id, start_of_today, today)

            if result["success"]:
                if result["synced_count"] > 0:
                    response = (
                        f"✅ Синхронизация завершена!\n\n"
                        f"📥 Синхронизировано записей: {result['synced_count']}\n"
                        f"⏰ Всего времени: {self.data_manager.format_hours_minutes(result['total_hours'])}\n"
                        f"💰 Заработано: {result['total_earnings']:.2f} руб"
                    )
                else:
                    response = result.get("message", "✅ Новых записей для синхронизации не найдено")
            else:
                response = f"❌ Ошибка синхронизации: {result['error']}"

            await message.answer(response)

        @self.dp.message(Command("synclast"))
        async def sync_last_command(message: Message):
            user_id = str(message.from_user.id)
            rate = self.data_manager.get_rate(user_id)

            if not self.data_manager.get_user_clickup_client(user_id):
                await message.answer("❌ ClickUp не настроен для вашего аккаунта\n\nИспользуйте /clickup_setup для настройки")
                return

            if rate <= 0:
                await message.answer("❌ Сначала установите ставку командой /setrate")
                return

            command_parts = message.text.strip().split()
            days = 7
            if len(command_parts) > 1:
                try:
                    days = int(command_parts[1])
                    if days <= 0 or days > 30:
                        await message.answer("❌ Количество дней должно быть от 1 до 30")
                        return
                except ValueError:
                    await message.answer("❌ Введите корректное количество дней")
                    return

            await message.answer(f"🔄 Синхронизирую данные ClickUp за последние {days} дней...")

            end_date = datetime.now()
            start_date = end_date - timedelta(days=days)

            result = await self.data_manager.sync_clickup_entries(user_id, start_date, end_date)

            if result["success"]:
                if result["synced_count"] > 0:
                    response = (
                        f"✅ Синхронизация завершена!\n\n"
                        f"📅 Период: {days} дней\n"
                        f"📥 Синхронизировано записей: {result['synced_count']}\n"
                        f"⏰ Всего времени: {self.data_manager.format_hours_minutes(result['total_hours'])}\n"
                        f"💰 Заработано: {result['total_earnings']:.2f} руб"
                    )
                else:
                    response = result.get("message", "✅ Новых записей для синхронизации не найдено")
            else:
                response = f"❌ Ошибка синхронизации: {result['error']}"

            await message.answer(response)

        @self.dp.message(Command("clickupstatus"))
        async def clickup_status_command(message: Message):
            user_id = str(message.from_user.id)
            clickup_client = self.data_manager.get_user_clickup_client(user_id)

            if not clickup_client:
                await message.answer("❌ ClickUp не настроен для вашего аккаунта\n\nИспользуйте /clickup_setup для настройки")
                return

            await message.answer("🔍 Проверяю статус ClickUp...")

            team_id = await clickup_client.get_team_id()
            if not team_id:
                await message.answer("❌ Не удалось подключиться к ClickUp. Проверьте настройки API.")
                return

            current_timer = await clickup_client.get_current_timer()

            clickup_settings = self.data_manager.get_clickup_settings(user_id)
            clickup_username = clickup_settings.get("username", "Неизвестно")
            clickup_user_id = clickup_settings.get("user_id")

            response = "✅ ClickUp интеграция активна\n\n"
            response += f"👤 Пользователь: {clickup_username}\n"
            response += f"🏢 Team ID: {team_id}\n"

            if clickup_user_id:
                response += f"🆔 User ID: ✅ Настроен\n"
            else:
                response += f"🆔 User ID: ❌ Отсутствует\n"
                response += f"⚠️ *Рекомендация:* Используйте /clickup_refresh\n"

            if current_timer:
                task_name = "Неизвестная задача"
                if current_timer.get('task'):
                    task_name = current_timer['task'].get('name', task_name)

                start_time = datetime.fromtimestamp(int(current_timer.get('start', 0)) / 1000)
                response += f"\n⏳ Активный таймер:\n📋 Задача: {task_name}\n🕐 Запущен: {start_time.strftime('%H:%M %d.%m.%Y')}"
            else:
                response += "\n⏹ Активных таймеров нет"

            synced_count = self.data_manager.count_synced_entries(user_id)
            response += f"\n\n📊 Синхронизировано записей: {synced_count}"

            if not clickup_user_id:
                response += f"\n\n💡 *Информация:*\nБез User ID команда /tasks будет показывать все задачи вместо только ваших."

            await message.answer(response)

        @self.dp.message(Command("today"))
        async def today_command(message: Message):
            user_id = str(message.from_user.id)
            content = self.data_manager.generate_today_report(
                self.data_manager.get_work_sessions(user_id))
            await self.send_earnings_report(message, "today", content)

        @self.dp.message(Command("yesterday"))
        async def yesterday_command(message: Message):
            user_id = str(message.from_user.id)
            content = self.data_manager.generate_yesterday_report(
                self.data_manager.get_work_sessions(user_id))
            await self.send_earnings_report(message, "yesterday", content)

        @self.dp.message(Command("week"))
        async def week_command(message: Message):
            user_id = str(message.from_user.id)
            content = self.data_manager.generate_week_report(
                self.data_manager.get_work_sessions(user_id))
            await self.send_earnings_report(message, "week", content)

        @self.dp.message(Command("weekdetails"))
        async def week_details_command(message: Message):
            user_id = str(message.from_user.id)
            content = self.data_manager.generate_week_details_report(
                self.data_manager.get_work_sessions(user_id))
            await self.send_earnings_report(message, "week_details", content)

        @self.dp.message(Command("month"))
        async def month_command(message: Message):
            user_id = str(message.from_user.id)
            content = self.month_report_with_bonuses(user_id)
            await self.send_earnings_report(message, "month", content)

        @self.dp.message(Command("monthweeks"))
        async def month_weeks_command(message: Message):
            user_id = str(message.from_user.id)
            content = self.data_manager.generate_month_weeks_report(
                self.data_manager.get_work_sessions(user_id))
            await self.send_earnings_report(message, "month_weeks", content)

        @self.dp.message(Command("prevmonthweeks"))
        async def prev_month_weeks_command(message: Message):
            user_id = str(message.from_user.id)
            content = self.data_manager.generate_prev_month_weeks_report(
                self.data_manager.get_work_sessions(user_id))
            await self.send_earnings_report(message, "prev_month_weeks", content)

        @self.dp.message(Command("year"))
        async def year_command(message: Message):
            user_id = str(message.from_user.id)
            content = self.data_manager.generate_year_report(
                self.data_manager.get_work_sessions(user_id))
            await self.send_earnings_report(message, "year", content)

        @self.dp.message(Command("tasks"))
        async def tasks_command(message: Message):
            user_id = str(message.from_user.id)
            clickup_client = self.data_manager.get_user_clickup_client(user_id)

            if not clickup_client:
                await message.answer("❌ ClickUp не настроен для вашего аккаунта\n\nИспользуйте /clickup_setup для настройки")
                return

            await message.answer("🔄 Загружаю рабочие пространства из ClickUp...")

            spaces = await clickup_client.get_spaces()

            if not spaces:
                await message.answer("📋 У вас нет доступных рабочих пространств в ClickUp")
                return

            keyboard = []
            for space in spaces:
                space_id = space.get('id')
                space_name = space.get('name', 'Неизвестное пространство')

                if len(space_name) > 35:
                    display_name = space_name[:35] + "..."
                else:
                    display_name = space_name

                keyboard.append([
                    InlineKeyboardButton(
                        text=f"🏢 {display_name}",
                        callback_data=f"space_select_{space_id}"
                    )
                ])

            keyboard_markup = InlineKeyboardMarkup(inline_keyboard=keyboard)

            spaces_text = (
                f"🏢 *Рабочие пространства*\n\n"
                f"Найдено пространств: {len(spaces)}\n"
                f"Выберите пространство для просмотра папок:"
            )

            await message.answer(
                spaces_text,
                reply_markup=keyboard_markup,
                parse_mode="Markdown"
            )

        @self.dp.message(Command("active_task"))
        async def active_task_command(message: Message):
            user_id = str(message.from_user.id)
            clickup_client = self.data_manager.get_user_clickup_client(user_id)

            if not clickup_client:
                await message.answer("❌ ClickUp не настроен для вашего аккаунта\n\nИспользуйте /clickup_setup для настройки")
                return

            await message.answer("🔍 Проверяю активные таймеры...")

            current_timer = await clickup_client.get_current_timer()

            if not current_timer:
                await message.answer("⏹ Активных таймеров не найдено")
                return

            task_id = current_timer.get('task', {}).get('id')
            if not task_id:
                await message.answer("❌ Не удалось получить информацию о задаче")
                return

            task_details = await clickup_client.get_task_details(task_id)
            if not task_details:
                await message.answer("❌ Не удалось загрузить детали задачи")
                return

            start_time = datetime.fromtimestamp(int(current_timer.get('start', 0)) / 1000)
            current_time = datetime.now()
            working_time = current_time - start_time

            hours = int(working_time.total_seconds() // 3600)
            minutes = int((working_time.total_seconds() % 3600) // 60)
            time_text = f"{hours}ч {minutes}м"

            task_name = task_details.get('name', 'Неизвестная задача')
            project_name = (task_details.get('project_name') or
                            task_details.get('space', {}).get('name') or
                            'Неизвестный проект')
            status = task_details.get('status', {}).get('status', 'Неизвестен')

            active_text = (
                f"⏱️ *Активная задача*\n\n"
                f"📋 *Название:* {task_name}\n"
                f"🏗 *Проект:* {project_name}\n"
                f"📊 *Статус:* {status}\n"
                f"🕐 *Время работы:* {time_text}\n"
                f"🎯 *Начато:* {start_time.strftime('%H:%M %d.%m.%Y')}"
            )

            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [
                    InlineKeyboardButton(text="📋 Подробнее", callback_data=f"task_info_{task_id}"),
                    InlineKeyboardButton(text="⏹️ Остановить", callback_data=f"timer_stop_{task_id}")
                ]
            ])

            await message.answer(active_text, reply_markup=keyboard, parse_mode="Markdown")

        # Callback handlers
        @self.dp.callback_query(F.data.startswith("task_info_"))
        async def handle_task_info(callback: CallbackQuery):
            task_id = callback.data.split("_")[-1]
            user_id = str(callback.from_user.id)
            clickup_client = self.data_manager.get_user_clickup_client(user_id)

            if not clickup_client:
                await callback.answer("❌ ClickUp не настроен", show_alert=True)
                return

            task_details = await clickup_client.get_task_details(task_id)
            if not task_details:
                await callback.answer("❌ Не удалось загрузить задачу", show_alert=True)
                return

            info_text = self.format_task_info(task_details)

            back_keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔙 Назад", callback_data=f"task_back_{task_id}")]
            ])

            await callback.message.edit_text(
                info_text,
                reply_markup=back_keyboard,
                parse_mode="Markdown"
            )
            await callback.answer()

        @self.dp.callback_query(F.data.startswith("task_back_"))
        async def handle_task_back(callback: CallbackQuery):
            task_id = callback.data.split("_")[-1]
            user_id = str(callback.from_user.id)
            clickup_client = self.data_manager.get_user_clickup_client(user_id)

            if not clickup_client:
                await callback.answer("❌ ClickUp не настроен", show_alert=True)
                return

            task_details = await clickup_client.get_task_details(task_id)
            if not task_details:
                await callback.answer("❌ Не удалось загрузить задачу", show_alert=True)
                return

            task_name = task_details.get('name', 'Без названия')
            task_status = task_details.get('status', {}).get('status', 'Неизвестен')

            if len(task_name) > 50:
                display_name = task_name[:50] + "..."
            else:
                display_name = task_name

            keyboard = self.create_task_keyboard(task_details)

            await callback.message.edit_text(
                f"📋 *{display_name}*\n📊 {task_status}",
                reply_markup=keyboard,
                parse_mode="Markdown"
            )
            await callback.answer()

        @self.dp.callback_query(F.data.startswith("timer_start_"))
        async def handle_timer_start(callback: CallbackQuery):
            task_id = callback.data.split("_")[-1]
            user_id = str(callback.from_user.id)
            clickup_client = self.data_manager.get_user_clickup_client(user_id)

            if not clickup_client:
                await callback.answer("❌ ClickUp не настроен", show_alert=True)
                return

            await callback.answer("⏱️ Запуск таймера...")

            success = await clickup_client.start_timer(task_id)

            if success:
                task_details = await clickup_client.get_task_details(task_id)
                if task_details:
                    task_name = task_details.get('name', 'Без названия')
                    keyboard = self.create_task_keyboard(task_details)

                    await callback.message.edit_text(
                        f"📋 *{task_name}*\n📊 {task_details.get('status', {}).get('status', 'Неизвестен')}\n⏱️ *Таймер запущен!*",
                        reply_markup=keyboard,
                        parse_mode="Markdown"
                    )
                else:
                    await callback.message.edit_text("✅ Таймер запущен!")
            else:
                await callback.message.edit_text("❌ Не удалось запустить таймер")

        @self.dp.callback_query(F.data.startswith("timer_stop_"))
        async def handle_timer_stop(callback: CallbackQuery):
            task_id = callback.data.split("_")[-1]
            user_id = str(callback.from_user.id)
            clickup_client = self.data_manager.get_user_clickup_client(user_id)

            if not clickup_client:
                await callback.answer("❌ ClickUp не настроен", show_alert=True)
                return

            await callback.answer("⏹️ Остановка таймера...")

            success = await clickup_client.stop_timer()

            if success:
                task_details = await clickup_client.get_task_details(task_id)
                if task_details:
                    task_name = task_details.get('name', 'Без названия')
                    keyboard = self.create_task_keyboard(task_details)

                    await callback.message.edit_text(
                        f"📋 *{task_name}*\n📊 {task_details.get('status', {}).get('status', 'Неизвестен')}\n⏹️ *Таймер остановлен!*",
                        reply_markup=keyboard,
                        parse_mode="Markdown"
                    )
                else:
                    await callback.message.edit_text("✅ Таймер остановлен!")
            else:
                await callback.message.edit_text("❌ Не удалось остановить таймер")

        @self.dp.callback_query(F.data.startswith("task_status_"))
        async def handle_status_change(callback: CallbackQuery):
            parts = callback.data.split("_")
            new_status = parts[2]
            task_id = parts[3]

            user_id = str(callback.from_user.id)
            clickup_client = self.data_manager.get_user_clickup_client(user_id)

            if not clickup_client:
                await callback.answer("❌ ClickUp не настроен", show_alert=True)
                return

            await callback.answer(f"🔄 Изменение статуса на {new_status}...")

            success = await clickup_client.update_task_status(task_id, new_status)

            if success:
                task_details = await clickup_client.get_task_details(task_id)
                if task_details:
                    task_name = task_details.get('name', 'Без названия')
                    current_status = task_details.get('status', {}).get('status', 'Неизвестен')
                    keyboard = self.create_task_keyboard(task_details)

                    await callback.message.edit_text(
                        f"📋 *{task_name}*\n📊 {current_status}\n✅ *Статус обновлен!*",
                        reply_markup=keyboard,
                        parse_mode="Markdown"
                    )
                else:
                    await callback.message.edit_text(f"✅ Статус изменен на {new_status}!")
            else:
                await callback.message.edit_text("❌ Не удалось изменить статус")

        @self.dp.callback_query(F.data.startswith("space_select_"))
        async def handle_space_select(callback: CallbackQuery):
            space_id = callback.data.split("_", 2)[2]
            user_id = str(callback.from_user.id)
            clickup_client = self.data_manager.get_user_clickup_client(user_id)

            if not clickup_client:
                await callback.answer("❌ ClickUp не настроен", show_alert=True)
                return

            await callback.answer("📁 Загрузка папок...")

            folders = await clickup_client.get_folders(space_id)

            spaces = await clickup_client.get_spaces()
            space_name = "Неизвестное пространство"
            for space in spaces:
                if space.get('id') == space_id:
                    space_name = space.get('name', space_name)
                    break

            if not folders:
                lists = await clickup_client.get_lists(space_id)

                if not lists:
                    back_keyboard = InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(
                            text="🔙 Назад к пространствам",
                            callback_data="back_to_spaces"
                        )]
                    ])

                    await callback.message.edit_text(
                        f"🏢 *{space_name}*\n\n📋 В этом пространстве нет папок и списков",
                        reply_markup=back_keyboard,
                        parse_mode="Markdown"
                    )
                    return

                keyboard = []
                for list_item in lists:
                    list_id = list_item.get('id')
                    list_name = list_item.get('name', 'Неизвестный список')

                    if len(list_name) > 35:
                        display_name = list_name[:35] + "..."
                    else:
                        display_name = list_name

                    keyboard.append([
                        InlineKeyboardButton(
                            text=f"📋 {display_name}",
                            callback_data=f"list_select_{space_id}_none_{list_id}"
                        )
                    ])

                keyboard.append([
                    InlineKeyboardButton(
                        text="🔙 Назад к пространствам",
                        callback_data="back_to_spaces"
                    )
                ])

                keyboard_markup = InlineKeyboardMarkup(inline_keyboard=keyboard)

                lists_text = (
                    f"🏢 *{space_name}*\n\n"
                    f"📋 Найдено списков: {len(lists)}\n"
                    f"Выберите список для просмотра задач:"
                )

                await callback.message.edit_text(
                    lists_text,
                    reply_markup=keyboard_markup,
                    parse_mode="Markdown"
                )
                return

            keyboard = []
            for folder in folders:
                folder_id = folder.get('id')
                folder_name = folder.get('name', 'Неизвестная папка')

                if len(folder_name) > 35:
                    display_name = folder_name[:35] + "..."
                else:
                    display_name = folder_name

                keyboard.append([
                    InlineKeyboardButton(
                        text=f"📁 {display_name}",
                        callback_data=f"folder_select_{space_id}_{folder_id}"
                    )
                ])

            root_lists = await clickup_client.get_lists(space_id)
            for list_item in root_lists:
                list_id = list_item.get('id')
                list_name = list_item.get('name', 'Неизвестный список')

                if len(list_name) > 35:
                    display_name = list_name[:35] + "..."
                else:
                    display_name = list_name

                keyboard.append([
                    InlineKeyboardButton(
                        text=f"📋 {display_name}",
                        callback_data=f"list_select_{space_id}_none_{list_id}"
                    )
                ])

            keyboard.append([
                InlineKeyboardButton(
                    text="🔙 Назад к пространствам",
                    callback_data="back_to_spaces"
                )
            ])

            keyboard_markup = InlineKeyboardMarkup(inline_keyboard=keyboard)

            folders_text = (
                f"🏢 *{space_name}*\n\n"
                f"📁 Найдено папок: {len(folders)}\n"
                f"📋 Списков в корне: {len(root_lists)}\n"
                f"Выберите папку или список:"
            )

            await callback.message.edit_text(
                folders_text,
                reply_markup=keyboard_markup,
                parse_mode="Markdown"
            )

        @self.dp.callback_query(F.data.startswith("folder_select_"))
        async def handle_folder_select(callback: CallbackQuery):
            parts = callback.data.split("_", 3)
            space_id = parts[2]
            folder_id = parts[3]

            user_id = str(callback.from_user.id)
            clickup_client = self.data_manager.get_user_clickup_client(user_id)

            if not clickup_client:
                await callback.answer("❌ ClickUp не настроен", show_alert=True)
                return

            await callback.answer("📋 Загрузка списков...")

            lists = await clickup_client.get_lists(space_id, folder_id)

            folders = await clickup_client.get_folders(space_id)
            folder_name = "Неизвестная папка"
            for folder in folders:
                if folder.get('id') == folder_id:
                    folder_name = folder.get('name', folder_name)
                    break

            if not lists:
                back_keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(
                        text="🔙 Назад к папкам",
                        callback_data=f"space_select_{space_id}"
                    )]
                ])

                await callback.message.edit_text(
                    f"📁 *{folder_name}*\n\n📋 В этой папке нет списков",
                    reply_markup=back_keyboard,
                    parse_mode="Markdown"
                )
                return

            keyboard = []
            for list_item in lists:
                list_id = list_item.get('id')
                list_name = list_item.get('name', 'Неизвестный список')

                if len(list_name) > 35:
                    display_name = list_name[:35] + "..."
                else:
                    display_name = list_name

                keyboard.append([
                    InlineKeyboardButton(
                        text=f"📋 {display_name}",
                        callback_data=f"list_select_{space_id}_{folder_id}_{list_id}"
                    )
                ])

            keyboard.append([
                InlineKeyboardButton(
                    text="🔙 Назад к папкам",
                    callback_data=f"space_select_{space_id}"
                )
            ])

            keyboard_markup = InlineKeyboardMarkup(inline_keyboard=keyboard)

            lists_text = (
                f"📁 *{folder_name}*\n\n"
                f"📋 Найдено списков: {len(lists)}\n"
                f"Выберите список для просмотра задач:"
            )

            await callback.message.edit_text(
                lists_text,
                reply_markup=keyboard_markup,
                parse_mode="Markdown"
            )

        @self.dp.callback_query(F.data.startswith("list_select_"))
        async def handle_list_select(callback: CallbackQuery):
            parts = callback.data.split("_", 4)
            space_id = parts[2]
            folder_id = parts[3] if parts[3] != 'none' else None
            list_id = parts[4]

            user_id = str(callback.from_user.id)
            clickup_client = self.data_manager.get_user_clickup_client(user_id)

            if not clickup_client:
                await callback.answer("❌ ClickUp не настроен", show_alert=True)
                return

            await callback.answer("🔄 Загрузка всех задач проекта...")

            try:
                tasks = await clickup_client.get_tasks(list_id)

                if not tasks:
                    if folder_id:
                        lists = await clickup_client.get_lists(space_id, folder_id)
                    else:
                        lists = await clickup_client.get_lists(space_id)

                    list_name = "Неизвестный список"
                    for list_item in lists:
                        if list_item.get('id') == list_id:
                            list_name = list_item.get('name', list_name)
                            break

                    escaped_list_name = self.escape_markdown(list_name)

                    if folder_id:
                        back_callback = f"folder_select_{space_id}_{folder_id}"
                        back_text = "🔙 Назад к спискам"
                    else:
                        back_callback = f"space_select_{space_id}"
                        back_text = "🔙 Назад к папкам"

                    back_keyboard = InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(
                            text=back_text,
                            callback_data=back_callback
                        )]
                    ])

                    await callback.message.edit_text(
                        f"📋 *{escaped_list_name}*\n\n❌ В этом списке нет задач",
                        reply_markup=back_keyboard,
                        parse_mode="Markdown"
                    )
                    return

                list_name = tasks[0].get('list', {}).get('name', 'Неизвестный список')
                escaped_list_name = self.escape_markdown(list_name)

                header_text = (
                    f"📋 *{escaped_list_name}*\n"
                    f"📄 Всего задач: {len(tasks)}\n\n"
                    f"Навигация по задачам:"
                )

                if folder_id:
                    back_callback = f"folder_select_{space_id}_{folder_id}"
                    back_text = "🔙 Назад к спискам"
                else:
                    back_callback = f"space_select_{space_id}"
                    back_text = "🔙 Назад к папкам"

                back_keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(
                        text=back_text,
                        callback_data=back_callback
                    )]
                ])

                await callback.message.edit_text(
                    header_text,
                    reply_markup=back_keyboard,
                    parse_mode="Markdown"
                )

                current_index = 0
                await self.send_task_with_navigation(callback.message, tasks, current_index, list_id, space_id, folder_id)

            except Exception as e:
                logger.error(f"Ошибка при получении задач: {e}")
                await callback.message.edit_text(f"❌ Ошибка загрузки задач: {str(e)}")

        @self.dp.callback_query(F.data.startswith("task_nav_prev_"))
        async def handle_task_nav_prev(callback: CallbackQuery):
            parts = callback.data.split("_")
            list_id = parts[3]
            current_index = int(parts[4])
            prev_index = int(parts[5])

            user_id = str(callback.from_user.id)
            clickup_client = self.data_manager.get_user_clickup_client(user_id)

            if not clickup_client:
                await callback.answer("❌ ClickUp не настроен", show_alert=True)
                return

            await callback.answer("◀️ Предыдущая задача")

            try:
                tasks = await clickup_client.get_tasks(list_id)

                if tasks and prev_index < len(tasks):
                    await self.update_task_navigation(callback.message, tasks, prev_index, list_id)
                else:
                    await callback.message.edit_text("❌ Ошибка навигации по задачам")

            except Exception as e:
                logger.error(f"Ошибка навигации к предыдущей задаче: {e}")
                await callback.message.edit_text(f"❌ Ошибка: {str(e)}")

        @self.dp.callback_query(F.data.startswith("task_nav_next_"))
        async def handle_task_nav_next(callback: CallbackQuery):
            parts = callback.data.split("_")
            list_id = parts[3]
            current_index = int(parts[4])
            next_index = int(parts[5])

            user_id = str(callback.from_user.id)
            clickup_client = self.data_manager.get_user_clickup_client(user_id)

            if not clickup_client:
                await callback.answer("❌ ClickUp не настроен", show_alert=True)
                return

            await callback.answer("▶️ Следующая задача")

            try:
                tasks = await clickup_client.get_tasks(list_id)

                if tasks and next_index < len(tasks):
                    await self.update_task_navigation(callback.message, tasks, next_index, list_id)
                else:
                    await callback.message.edit_text("❌ Ошибка навигации по задачам")

            except Exception as e:
                logger.error(f"Ошибка навигации к следующей задаче: {e}")
                await callback.message.edit_text(f"❌ Ошибка: {str(e)}")

        @self.dp.callback_query(F.data.startswith("task_status_change_"))
        async def handle_task_status_change(callback: CallbackQuery):
            task_id = callback.data.split("_")[-1]

            await callback.answer("🔄 Выберите новый статус")

            keyboard = []
            statuses = [
                ("open", "📂 Open"),
                ("in progress", "🔄 In Progress"),
                ("review", "👀 Review"),
                ("done", "✅ Done"),
                ("complete", "🏁 Complete")
            ]

            for status_key, status_label in statuses:
                keyboard.append([
                    InlineKeyboardButton(
                        text=status_label,
                        callback_data=f"task_status_{status_key}_{task_id}"
                    )
                ])

            keyboard.append([
                InlineKeyboardButton(text="🔙 Назад", callback_data=f"task_back_{task_id}")
            ])

            status_keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard)

            await callback.message.edit_text(
                "🔄 Выберите новый статус для задачи:",
                reply_markup=status_keyboard
            )

        # Earnings report callbacks
        @self.dp.callback_query(F.data == "earnings_today")
        async def handle_earnings_today(callback: CallbackQuery):
            user_id = str(callback.from_user.id)
            content = self.data_manager.generate_today_report(
                self.data_manager.get_work_sessions(user_id))

            keyboard = self.create_earnings_keyboard("today")
            await callback.message.edit_text(content, reply_markup=keyboard)
            await callback.answer()

        @self.dp.callback_query(F.data == "earnings_yesterday")
        async def handle_earnings_yesterday(callback: CallbackQuery):
            user_id = str(callback.from_user.id)
            content = self.data_manager.generate_yesterday_report(
                self.data_manager.get_work_sessions(user_id))

            keyboard = self.create_earnings_keyboard("yesterday")
            await callback.message.edit_text(content, reply_markup=keyboard)
            await callback.answer()

        @self.dp.callback_query(F.data == "earnings_week")
        async def handle_earnings_week(callback: CallbackQuery):
            user_id = str(callback.from_user.id)
            content = self.data_manager.generate_week_report(
                self.data_manager.get_work_sessions(user_id))

            keyboard = self.create_earnings_keyboard("week")
            await callback.message.edit_text(content, reply_markup=keyboard)
            await callback.answer()

        @self.dp.callback_query(F.data == "earnings_month")
        async def handle_earnings_month(callback: CallbackQuery):
            user_id = str(callback.from_user.id)
            content = self.month_report_with_bonuses(user_id)

            keyboard = self.create_earnings_keyboard("month")
            await callback.message.edit_text(content, reply_markup=keyboard)
            await callback.answer()

        @self.dp.callback_query(F.data == "earnings_week_details")
        async def handle_earnings_week_details(callback: CallbackQuery):
            user_id = str(callback.from_user.id)
            content = self.data_manager.generate_week_details_report(
                self.data_manager.get_work_sessions(user_id))

            keyboard = self.create_earnings_keyboard("week_details")
            await callback.message.edit_text(content, reply_markup=keyboard)
            await callback.answer()

        @self.dp.callback_query(F.data == "earnings_month_weeks")
        async def handle_earnings_month_weeks(callback: CallbackQuery):
            user_id = str(callback.from_user.id)
            content = self.data_manager.generate_month_weeks_report(
                self.data_manager.get_work_sessions(user_id))

            keyboard = self.create_earnings_keyboard("month_weeks")
            await callback.message.edit_text(content, reply_markup=keyboard)
            await callback.answer()

        @self.dp.callback_query(F.data == "earnings_prev_month_weeks")
        async def handle_earnings_prev_month_weeks(callback: CallbackQuery):
            user_id = str(callback.from_user.id)
            content = self.data_manager.generate_prev_month_weeks_report(
                self.data_manager.get_work_sessions(user_id))

            keyboard = self.create_earnings_keyboard("prev_month_weeks")
            await callback.message.edit_text(content, reply_markup=keyboard)
            await callback.answer()

        @self.dp.callback_query(F.data == "earnings_year")
        async def handle_earnings_year(callback: CallbackQuery):
            user_id = str(callback.from_user.id)
            content = self.data_manager.generate_year_report(
                self.data_manager.get_work_sessions(user_id))

            keyboard = self.create_earnings_keyboard("year")
            await callback.message.edit_text(content, reply_markup=keyboard)
            await callback.answer()

        # Task analytics callbacks
        @self.dp.callback_query(F.data == "tasks_summary_today")
        async def handle_tasks_summary_today(callback: CallbackQuery):
            user_id = str(callback.from_user.id)
            rate = self.data_manager.get_rate(user_id)

            if rate <= 0:
                await callback.answer("❌ Сначала установите ставку командой /setrate", show_alert=True)
                return

            start_date, end_date, period_name = self.data_manager.get_tasks_summary_by_period("today")
            summary = self.data_manager.get_tasks_summary(user_id, start_date, end_date)
            content = self.data_manager.format_task_summary(summary)

            keyboard = self.create_tasks_analytics_keyboard("today")
            await callback.message.edit_text(content, reply_markup=keyboard)
            await callback.answer()

        @self.dp.callback_query(F.data == "tasks_summary_yesterday")
        async def handle_tasks_summary_yesterday(callback: CallbackQuery):
            user_id = str(callback.from_user.id)
            rate = self.data_manager.get_rate(user_id)

            if rate <= 0:
                await callback.answer("❌ Сначала установите ставку командой /setrate", show_alert=True)
                return

            start_date, end_date, period_name = self.data_manager.get_tasks_summary_by_period("yesterday")
            summary = self.data_manager.get_tasks_summary(user_id, start_date, end_date)
            content = self.data_manager.format_task_summary(summary)

            keyboard = self.create_tasks_analytics_keyboard("yesterday")
            await callback.message.edit_text(content, reply_markup=keyboard)
            await callback.answer()

        @self.dp.callback_query(F.data == "tasks_summary_week")
        async def handle_tasks_summary_week(callback: CallbackQuery):
            user_id = str(callback.from_user.id)
            rate = self.data_manager.get_rate(user_id)

            if rate <= 0:
                await callback.answer("❌ Сначала установите ставку командой /setrate", show_alert=True)
                return

            start_date, end_date, period_name = self.data_manager.get_tasks_summary_by_period("week")
            summary = self.data_manager.get_tasks_summary(user_id, start_date, end_date)
            content = self.data_manager.format_task_summary(summary)

            keyboard = self.create_tasks_analytics_keyboard("week")
            await callback.message.edit_text(content, reply_markup=keyboard)
            await callback.answer()

        @self.dp.callback_query(F.data == "tasks_summary_month")
        async def handle_tasks_summary_month(callback: CallbackQuery):
            user_id = str(callback.from_user.id)
            rate = self.data_manager.get_rate(user_id)

            if rate <= 0:
                await callback.answer("❌ Сначала установите ставку командой /setrate", show_alert=True)
                return

            start_date, end_date, period_name = self.data_manager.get_tasks_summary_by_period("month")
            summary = self.data_manager.get_tasks_summary(user_id, start_date, end_date)
            content = self.data_manager.format_task_summary(summary)

            keyboard = self.create_tasks_analytics_keyboard("month")
            await callback.message.edit_text(content, reply_markup=keyboard)
            await callback.answer()

        @self.dp.callback_query(F.data == "tasks_summary_7days")
        async def handle_tasks_summary_7days(callback: CallbackQuery):
            user_id = str(callback.from_user.id)
            rate = self.data_manager.get_rate(user_id)

            if rate <= 0:
                await callback.answer("❌ Сначала установите ставку командой /setrate", show_alert=True)
                return

            start_date, end_date, period_name = self.data_manager.get_tasks_summary_by_period("7days")
            summary = self.data_manager.get_tasks_summary(user_id, start_date, end_date)
            content = self.data_manager.format_task_summary(summary)

            keyboard = self.create_tasks_analytics_keyboard("7days")
            await callback.message.edit_text(content, reply_markup=keyboard)
            await callback.answer()

        @self.dp.callback_query(F.data == "tasks_summary_30days")
        async def handle_tasks_summary_30days(callback: CallbackQuery):
            user_id = str(callback.from_user.id)
            rate = self.data_manager.get_rate(user_id)

            if rate <= 0:
                await callback.answer("❌ Сначала установите ставку командой /setrate", show_alert=True)
                return

            start_date, end_date, period_name = self.data_manager.get_tasks_summary_by_period("30days")
            summary = self.data_manager.get_tasks_summary(user_id, start_date, end_date)
            content = self.data_manager.format_task_summary(summary)

            keyboard = self.create_tasks_analytics_keyboard("30days")
            await callback.message.edit_text(content, reply_markup=keyboard)
            await callback.answer()

    async def start_bot(self):
        """Запуск бота"""
        print("🤖 Бот запущен!")

        if WEBAPP_URL:
            try:
                await self.bot.set_chat_menu_button(
                    menu_button=MenuButtonWebApp(
                        text="Salary App",
                        web_app=WebAppInfo(url=WEBAPP_URL)
                    )
                )
                logger.info(f"Menu button set to WebApp: {WEBAPP_URL}")
            except Exception as e:
                logger.warning(f"Failed to set menu button: {e}")

        await self.dp.start_polling(self.bot)


async def main():
    bot = SalaryBot(BOT_TOKEN)
    await bot.start_bot()


if __name__ == "__main__":
    asyncio.run(main())
