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
                "/week - заработок за неделю\n"
                "/month - заработок за месяц\n"
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
                "/week - заработок за неделю\n"
                "/month - заработок за месяц\n\n"
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
                    f"⏰ Отработано: {hours}ч {minutes}м ({total_hours:.2f}ч)\n"
                    f"💰 Заработано: {earnings:.2f} руб\n"
                    f"📊 Всего за сегодня: {user_data['work_sessions'][today]['total_hours']:.2f}ч = "
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
                    f"⏰ Отработано: {session['total_hours']:.2f} часов\n"
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
                    f"⏰ Отработано: {session['total_hours']:.2f} часов\n"
                    f"💰 Заработано: {session['total_earnings']:.2f} руб"
                )
            else:
                response = "📊 Вчера вы не добавляли рабочее время"

            await message.answer(response)

        @self.dp.message(Command("week"))
        async def week_command(message: Message):
            user_id = str(message.from_user.id)
            user_data = self.get_user_data(user_id)

            # Последние 7 дней
            total_hours = 0
            total_earnings = 0
            days_worked = 0

            for i in range(7):
                date = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
                if date in user_data["work_sessions"]:
                    session = user_data["work_sessions"][date]
                    total_hours += session["total_hours"]
                    total_earnings += session["total_earnings"]
                    days_worked += 1

            if days_worked > 0:
                response = (
                    f"📊 Заработок за неделю:\n\n"
                    f"📅 Рабочих дней: {days_worked}\n"
                    f"⏰ Всего отработано: {total_hours:.2f} часов\n"
                    f"💰 Всего заработано: {total_earnings:.2f} руб\n"
                    f"📈 Среднее в день: {total_earnings / days_worked:.2f} руб"
                )
            else:
                response = "📊 За последнюю неделю нет записей о работе"

            await message.answer(response)

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
                    f"⏰ Всего отработано: {total_hours:.2f} часов\n"
                    f"💰 Всего заработано: {total_earnings:.2f} руб\n"
                    f"📈 Среднее в день: {total_earnings / days_worked:.2f} руб"
                )
            else:
                response = "📊 За последний месяц нет записей о работе"

            await message.answer(response)

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
