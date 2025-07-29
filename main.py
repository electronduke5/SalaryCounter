import asyncio
import json
import os
from datetime import datetime, timedelta
from typing import Dict, Any
from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

load_dotenv()
# Замените на ваш токен бота
BOT_TOKEN = os.getenv("BOT_TOKEN")

# Файл для хранения данных
DATA_FILE = "salary_data.json"


class SalaryStates(StatesGroup):
    waiting_for_rate = State()
    waiting_for_time = State()


class SalaryBot:
    def __init__(self, token: str):
        self.bot = Bot(token=token)
        self.dp = Dispatcher(storage=MemoryStorage())
        self.data = self.load_data()
        self.setup_handlers()

    def load_data(self) -> Dict[str, Any]:
        """Загрузка данных из файла"""
        if os.path.exists(DATA_FILE):
            try:
                with open(DATA_FILE, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except:
                return {}
        return {}

    def save_data(self):
        """Сохранение данных в файл"""
        with open(DATA_FILE, 'w', encoding='utf-8') as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)

    def get_user_data(self, user_id: str) -> Dict[str, Any]:
        """Получение данных пользователя"""
        if user_id not in self.data:
            self.data[user_id] = {
                "rate": 0,
                "work_sessions": {}
            }
        return self.data[user_id]

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

    def setup_handlers(self):
        """Настройка обработчиков команд"""

        @self.dp.message(Command("start"))
        async def start_command(message: Message, state: FSMContext):
            user_id = str(message.from_user.id)
            user_data = self.get_user_data(user_id)

            welcome_text = (
                "🎯 Добро пожаловать в бота для подсчета зарплаты!\n\n"
                "Этот бот поможет вам отслеживать рабочее время и рассчитывать заработок.\n\n"
                "📋 Доступные команды:\n"
                "/setrate - установить ставку (руб/час)\n"
                "/addtime - добавить отработанное время\n"
                "/today - заработок за сегодня\n"
                "/yesterday - заработок за вчера\n"
                "/week - заработок за неделю (с понедельника)\n"
                "/weekdetails - детальный заработок по дням недели\n"
                "/month - заработок за месяц\n"
                "/monthweeks - заработок по неделям в месяце\n"
                "/help - показать эту справку\n\n"
            )

            if user_data["rate"] > 0:
                welcome_text += f"💰 Ваша текущая ставка: {user_data['rate']} руб/час"
            else:
                welcome_text += "⚠️ Сначала установите свою ставку командой /setrate"

            await message.answer(welcome_text)

        @self.dp.message(Command("help"))
        async def help_command(message: Message):
            help_text = (
                "📋 Справка по командам:\n\n"
                "/start - главное меню\n"
                "/setrate - установить ставку (руб/час)\n"
                "/addtime - добавить отработанное время\n"
                "/today - заработок за сегодня\n"
                "/yesterday - заработок за вчера\n"
                "/week - заработок за неделю (с понедельника)\n"
                "/weekdetails - детальный заработок по дням недели\n"
                "/month - заработок за месяц\n"
                "/monthweeks - заработок по неделям в месяце\n\n"
                "💡 Для добавления времени используйте формат: ЧАСЫ МИНУТЫ\n"
                "Например: 8 30 (означает 8 часов 30 минут)"
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
                user_data = self.get_user_data(user_id)
                user_data["rate"] = rate
                self.save_data()

                await message.answer(f"✅ Ставка установлена: {rate} руб/час")
                await state.clear()

            except ValueError:
                await message.answer("❌ Пожалуйста, введите корректное число!")

        @self.dp.message(Command("addtime"))
        async def add_time_command(message: Message, state: FSMContext):
            user_id = str(message.from_user.id)
            user_data = self.get_user_data(user_id)

            if user_data["rate"] <= 0:
                await message.answer("❌ Сначала установите ставку командой /setrate")
                return

            await message.answer("⏰ Введите отработанное время в формате: ЧАСЫ МИНУТЫ\nНапример: 8 30")
            await state.set_state(SalaryStates.waiting_for_time)

        @self.dp.message(SalaryStates.waiting_for_time)
        async def process_time(message: Message, state: FSMContext):
            try:
                parts = message.text.strip().split()
                if len(parts) != 2:
                    await message.answer("❌ Используйте формат: ЧАСЫ МИНУТЫ\nНапример: 8 30")
                    return

                hours = int(parts[0])
                minutes = int(parts[1])

                if hours < 0 or minutes < 0 or minutes >= 60:
                    await message.answer("❌ Некорректное время! Часы ≥ 0, минуты от 0 до 59")
                    return

                user_id = str(message.from_user.id)
                user_data = self.get_user_data(user_id)

                # Расчет заработка
                total_hours = hours + minutes / 60
                earnings = total_hours * user_data["rate"]

                # Сохранение данных за сегодня
                today = datetime.now().strftime("%Y-%m-%d")
                if today not in user_data["work_sessions"]:
                    user_data["work_sessions"][today] = {
                        "total_hours": 0,
                        "total_earnings": 0,
                        "sessions": []
                    }

                user_data["work_sessions"][today]["total_hours"] += total_hours
                user_data["work_sessions"][today]["total_earnings"] += earnings
                user_data["work_sessions"][today]["sessions"].append({
                    "hours": hours,
                    "minutes": minutes,
                    "earnings": earnings,
                    "timestamp": datetime.now().isoformat()
                })

                self.save_data()

                response = (
                    f"✅ Время добавлено!\n\n"
                    f"⏰ Отработано: {hours}ч {minutes}м ({self.format_hours_minutes(total_hours)})\n"
                    f"💰 Заработано: {earnings:.2f} руб\n"
                    f"📊 Всего за сегодня: {self.format_hours_minutes(user_data['work_sessions'][today]['total_hours'])} = "
                    f"{user_data['work_sessions'][today]['total_earnings']:.2f} руб"
                )

                await message.answer(response)
                await state.clear()

            except ValueError:
                await message.answer("❌ Пожалуйста, введите корректные числа!")

        @self.dp.message(Command("today"))
        async def today_command(message: Message):
            user_id = str(message.from_user.id)
            user_data = self.get_user_data(user_id)

            today = datetime.now().strftime("%Y-%m-%d")

            if today in user_data["work_sessions"]:
                session = user_data["work_sessions"][today]
                response = (
                    f"📊 Заработок за сегодня ({datetime.now().strftime('%d.%m.%Y')}):\n\n"
                    f"⏰ Отработано: {self.format_hours_minutes(session['total_hours'])}\n"
                    f"💰 Заработано: {session['total_earnings']:.2f} руб"
                )
            else:
                response = "📊 Сегодня вы еще не добавляли рабочее время"

            await message.answer(response)

        @self.dp.message(Command("yesterday"))
        async def yesterday_command(message: Message):
            user_id = str(message.from_user.id)
            user_data = self.get_user_data(user_id)

            yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

            if yesterday in user_data["work_sessions"]:
                session = user_data["work_sessions"][yesterday]
                response = (
                    f"📊 Заработок за вчера ({(datetime.now() - timedelta(days=1)).strftime('%d.%m.%Y')}):\n\n"
                    f"⏰ Отработано: {self.format_hours_minutes(session['total_hours'])}\n"
                    f"💰 Заработано: {session['total_earnings']:.2f} руб"
                )
            else:
                response = "📊 Вчера вы не добавляли рабочее время"

            await message.answer(response)

        @self.dp.message(Command("week"))
        async def week_command(message: Message):
            user_id = str(message.from_user.id)
            user_data = self.get_user_data(user_id)

            # Найти понедельник текущей недели
            today = datetime.now()
            monday = today - timedelta(days=today.weekday())
            
            total_hours = 0
            total_earnings = 0
            days_worked = 0

            # Подсчет с понедельника до сегодня
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
                response = (
                    f"📊 Заработок за неделю (с {monday.strftime('%d.%m')} по {today.strftime('%d.%m')}):\n\n"
                    f"📅 Рабочих дней: {days_worked}\n"
                    f"⏰ Всего отработано: {self.format_hours_minutes(total_hours)}\n"
                    f"💰 Всего заработано: {total_earnings:.2f} руб\n"
                    f"📈 Среднее в день: {total_earnings / days_worked:.2f} руб"
                )
            else:
                response = f"📊 На этой неделе (с {monday.strftime('%d.%m')} по {today.strftime('%d.%m')}) нет записей о работе"

            await message.answer(response)

        @self.dp.message(Command("weekdetails"))
        async def week_details_command(message: Message):
            user_id = str(message.from_user.id)
            user_data = self.get_user_data(user_id)

            # Найти понедельник текущей недели
            today = datetime.now()
            monday = today - timedelta(days=today.weekday())
            
            days_names = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]
            total_hours = 0
            total_earnings = 0
            response_lines = [f"📊 Детальный заработок за неделю (с {monday.strftime('%d.%m')} по {today.strftime('%d.%m')}):\n"]

            # Проход по каждому дню недели
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

            await message.answer("\n".join(response_lines))

        @self.dp.message(Command("month"))
        async def month_command(message: Message):
            user_id = str(message.from_user.id)
            user_data = self.get_user_data(user_id)

            # Последние 30 дней
            total_hours = 0
            total_earnings = 0
            days_worked = 0

            for i in range(30):
                date = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
                if date in user_data["work_sessions"]:
                    session = user_data["work_sessions"][date]
                    total_hours += session["total_hours"]
                    total_earnings += session["total_earnings"]
                    days_worked += 1

            if days_worked > 0:
                response = (
                    f"📊 Заработок за месяц:\n\n"
                    f"📅 Рабочих дней: {days_worked}\n"
                    f"⏰ Всего отработано: {self.format_hours_minutes(total_hours)}\n"
                    f"💰 Всего заработано: {total_earnings:.2f} руб\n"
                    f"📈 Среднее в день: {total_earnings / days_worked:.2f} руб"
                )
            else:
                response = "📊 За последний месяц нет записей о работе"

            await message.answer(response)

        @self.dp.message(Command("monthweeks"))
        async def month_weeks_command(message: Message):
            user_id = str(message.from_user.id)
            user_data = self.get_user_data(user_id)

            # Получить первый день текущего месяца
            today = datetime.now()
            first_day_of_month = today.replace(day=1)
            
            # Найти понедельник первой недели месяца
            first_monday = first_day_of_month - timedelta(days=first_day_of_month.weekday())
            
            weeks_data = []
            total_month_hours = 0
            total_month_earnings = 0
            week_number = 1
            
            current_monday = first_monday
            
            # Проходим по неделям месяца
            while current_monday.month <= today.month and current_monday <= today:
                # Определяем конец недели (воскресенье)
                sunday = current_monday + timedelta(days=6)
                
                # Если воскресенье в следующем месяце, ограничиваем последним днем текущего месяца
                if sunday.month > today.month:
                    last_day_of_month = today.replace(day=1, month=today.month+1) - timedelta(days=1) if today.month < 12 else today.replace(day=31)
                    sunday = min(sunday, last_day_of_month)
                
                # Если воскресенье больше сегодня, ограничиваем сегодняшним днем
                if sunday > today:
                    sunday = today
                
                week_hours = 0
                week_earnings = 0
                
                # Подсчет для текущей недели
                current_date = current_monday
                while current_date <= sunday:
                    date_str = current_date.strftime("%Y-%m-%d")
                    if date_str in user_data["work_sessions"]:
                        session = user_data["work_sessions"][date_str]
                        week_hours += session["total_hours"]
                        week_earnings += session["total_earnings"]
                    current_date += timedelta(days=1)
                
                if week_hours > 0:
                    weeks_data.append({
                        'number': week_number,
                        'start': current_monday,
                        'end': sunday,
                        'hours': week_hours,
                        'earnings': week_earnings
                    })
                    total_month_hours += week_hours
                    total_month_earnings += week_earnings
                
                current_monday += timedelta(days=7)
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

            await message.answer("\n".join(response_lines))

    async def start_bot(self):
        """Запуск бота"""
        print("🤖 Бот запущен!")
        await self.dp.start_polling(self.bot)


# Функция для запуска бота
async def main():
    bot = SalaryBot(BOT_TOKEN)
    await bot.start_bot()


if __name__ == "__main__":
    asyncio.run(main())
