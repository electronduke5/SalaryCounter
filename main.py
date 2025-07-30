import asyncio
import json
import os
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from dotenv import load_dotenv
import aiohttp
import logging

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

load_dotenv()
# Замените на ваш токен бота
BOT_TOKEN = os.getenv("BOT_TOKEN")
CLICKUP_API_TOKEN = os.getenv("CLICKUP_API_TOKEN")
CLICKUP_WORKSPACE_ID = os.getenv("CLICKUP_WORKSPACE_ID")

# Файл для хранения данных
DATA_FILE = "salary_data.json"

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def retry_with_backoff(func, max_retries=3, backoff_factor=1):
    """Retry decorator with exponential backoff"""
    for attempt in range(max_retries):
        try:
            return await func()
        except aiohttp.ClientError as e:
            if attempt == max_retries - 1:
                raise e
            wait_time = backoff_factor * (2 ** attempt)
            logger.warning(f"Attempt {attempt + 1} failed, retrying in {wait_time}s: {e}")
            await asyncio.sleep(wait_time)
        except Exception as e:
            # Для других ошибок не повторяем
            raise e


class ClickUpClient:
    """Клиент для работы с ClickUp API"""
    
    def __init__(self, api_token: str, workspace_id: str):
        self.api_token = api_token
        self.workspace_id = workspace_id
        self.base_url = "https://api.clickup.com/api/v2"
        self.team_id = None
        
    def _get_headers(self) -> Dict[str, str]:
        """Получение заголовков для API запросов"""
        return {
            "Authorization": self.api_token,
            "Content-Type": "application/json"
        }
    
    async def get_team_id(self) -> Optional[str]:
        """Получение team_id из workspace_id"""
        if self.team_id:
            return self.team_id
        
        async def _fetch_team_id():
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
                url = f"{self.base_url}/team"
                headers = self._get_headers()
                logger.info(f"ClickUp API request: GET {url}")
                logger.info(f"Headers: {headers}")
                
                async with session.get(url, headers=headers) as response:
                    response_text = await response.text()
                    logger.info(f"ClickUp API response: {response.status}")
                    logger.info(f"Response body: {response_text}")
                    
                    if response.status == 200:
                        data = await response.json()
                        teams = data.get('teams', [])
                        logger.info(f"Available teams: {[team.get('id') for team in teams]}")
                        logger.info(f"Looking for workspace_id: {self.workspace_id}")
                        
                        for team in teams:
                            if team.get('id') == self.workspace_id:
                                self.team_id = self.workspace_id
                                logger.info(f"Found matching team_id: {self.team_id}")
                                return self.team_id
                        # Если не найден точно, берем первый доступный
                        if teams:
                            self.team_id = teams[0]['id']
                            logger.info(f"Using first available team_id: {self.team_id}")
                            return self.team_id
                        logger.warning("No teams available")
                    elif response.status == 401:
                        raise ValueError("Неверный API токен ClickUp")
                    elif response.status == 403:
                        raise ValueError("Нет доступа к API ClickUp")
                    else:
                        raise aiohttp.ClientError(f"HTTP {response.status}: {response_text}")
                    return None
        
        try:
            result = await retry_with_backoff(_fetch_team_id)
            return result
        except Exception as e:
            logger.error(f"Ошибка получения team_id: {e}")
            return None
    
    async def get_time_entries(self, start_date: datetime, end_date: datetime) -> List[Dict]:
        """Получение записей времени за указанный период"""
        team_id = await self.get_team_id()
        if not team_id:
            return []
        
        async def _fetch_time_entries():
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as session:
                url = f"{self.base_url}/team/{team_id}/time_entries"
                params = {
                    'start_date': int(start_date.timestamp() * 1000),
                    'end_date': int(end_date.timestamp() * 1000)
                }
                headers = self._get_headers()
                
                logger.info(f"ClickUp API request: GET {url}")
                logger.info(f"Params: {params}")
                logger.info(f"Headers: {headers}")
                
                async with session.get(url, headers=headers, params=params) as response:
                    response_text = await response.text()
                    logger.info(f"ClickUp API response: {response.status}")
                    logger.info(f"Response body length: {len(response_text)}")
                    
                    if response.status == 200:
                        data = await response.json()
                        entries = data.get('data', [])
                        logger.info(f"Retrieved {len(entries)} time entries")
                        return entries
                    elif response.status == 401:
                        raise ValueError("Неверный API токен ClickUp")
                    elif response.status == 403:
                        raise ValueError("Нет доступа к записям времени")
                    elif response.status == 429:
                        raise aiohttp.ClientError("Превышен лимит запросов API")
                    else:
                        raise aiohttp.ClientError(f"HTTP {response.status}: {response_text}")
        
        try:
            return await retry_with_backoff(_fetch_time_entries)
        except Exception as e:
            logger.error(f"Ошибка получения записей времени: {e}")
            return []
    
    async def get_current_timer(self) -> Optional[Dict]:
        """Получение текущего запущенного таймера (запись с отрицательной продолжительностью)"""
        # Получаем записи за последние 24 часа
        end_date = datetime.now()
        start_date = end_date - timedelta(days=1)
        
        entries = await self.get_time_entries(start_date, end_date)
        for entry in entries:
            if int(entry.get('duration', 0)) < 0:
                return entry
        return None


class SalaryStates(StatesGroup):
    waiting_for_rate = State()
    waiting_for_time = State()
    waiting_for_clickup_token = State()
    waiting_for_workspace_id = State()


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
                    data = json.load(f)
                    # Конвертируем lists обратно в sets
                    for user_id, user_data in data.items():
                        if "clickup_synced_entries" in user_data and isinstance(user_data["clickup_synced_entries"], list):
                            user_data["clickup_synced_entries"] = set(user_data["clickup_synced_entries"])
                    return data
            except:
                return {}
        return {}

    def save_data(self):
        """Сохранение данных в файл"""
        # Конвертируем sets в lists для JSON сериализации
        data_to_save = {}
        for user_id, user_data in self.data.items():
            data_to_save[user_id] = user_data.copy()
            if "clickup_synced_entries" in data_to_save[user_id]:
                data_to_save[user_id]["clickup_synced_entries"] = list(data_to_save[user_id]["clickup_synced_entries"])
        
        with open(DATA_FILE, 'w', encoding='utf-8') as f:
            json.dump(data_to_save, f, ensure_ascii=False, indent=2)

    def get_user_data(self, user_id: str) -> Dict[str, Any]:
        """Получение данных пользователя"""
        if user_id not in self.data:
            self.data[user_id] = {
                "rate": 0,
                "work_sessions": {},
                "clickup_synced_entries": set(),  # Для отслеживания уже синхронизированных записей
                "clickup_settings": {
                    "api_token": None,
                    "workspace_id": None,
                    "team_id": None
                }
            }
        
        # Обновление структуры для старых пользователей
        if "clickup_synced_entries" not in self.data[user_id]:
            self.data[user_id]["clickup_synced_entries"] = set()
        
        if "clickup_settings" not in self.data[user_id]:
            self.data[user_id]["clickup_settings"] = {
                "api_token": None,
                "workspace_id": None,
                "team_id": None
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

    def get_user_clickup_client(self, user_id: str) -> Optional[ClickUpClient]:
        """Получение ClickUp клиента для конкретного пользователя"""
        user_data = self.get_user_data(user_id)
        clickup_settings = user_data.get("clickup_settings", {})
        
        api_token = clickup_settings.get("api_token")
        workspace_id = clickup_settings.get("workspace_id")
        
        if not api_token or not workspace_id:
            return None
            
        return ClickUpClient(api_token, workspace_id)

    async def validate_clickup_credentials(self, api_token: str, workspace_id: str) -> Dict[str, Any]:
        """Валидация ClickUp credentials"""
        try:
            client = ClickUpClient(api_token, workspace_id)
            team_id = await client.get_team_id()
            
            if team_id:
                return {"success": True, "team_id": team_id}
            else:
                return {"success": False, "error": "Не удалось получить доступ к workspace"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def sync_clickup_entries(self, user_id: str, start_date: datetime, end_date: datetime) -> Dict[str, Any]:
        """Синхронизация записей ClickUp с данными пользователя"""
        clickup_client = self.get_user_clickup_client(user_id)
        if not clickup_client:
            return {"success": False, "error": "ClickUp не настроен для этого пользователя"}
        
        user_data = self.get_user_data(user_id)
        
        try:
            # Получаем записи из ClickUp
            clickup_entries = await clickup_client.get_time_entries(start_date, end_date)
            
            if not clickup_entries:
                return {"success": True, "synced_count": 0, "message": "Записи не найдены"}
            
            synced_count = 0
            total_hours = 0
            total_earnings = 0
            
            for entry in clickup_entries:
                entry_id = entry.get('id')
                duration_ms = int(entry.get('duration', 0))
                
                # Пропускаем запущенные таймеры (отрицательная продолжительность) 
                if duration_ms < 0:
                    continue
                
                # Проверяям, не была ли уже синхронизирована эта запись
                if entry_id in user_data["clickup_synced_entries"]:
                    continue
                
                # Конвертируем миллисекунды в часы
                duration_hours = duration_ms / (1000 * 60 * 60)
                earnings = duration_hours * user_data["rate"]
                
                # Получаем дату записи
                start_timestamp = int(entry.get('start', 0)) / 1000
                entry_date = datetime.fromtimestamp(start_timestamp).strftime("%Y-%m-%d")
                
                # Создаем или обновляем сессию для этой даты
                if entry_date not in user_data["work_sessions"]:
                    user_data["work_sessions"][entry_date] = {
                        "total_hours": 0,
                        "total_earnings": 0,
                        "sessions": []
                    }
                
                # Добавляем ClickUp запись
                clickup_session = {
                    "hours": int(duration_hours),
                    "minutes": int((duration_hours % 1) * 60),
                    "earnings": earnings,
                    "timestamp": datetime.fromtimestamp(start_timestamp).isoformat(),
                    "source": "clickup",
                    "clickup_id": entry_id,
                    "task_name": entry.get('task', {}).get('name', 'Неизвестная задача') if entry.get('task') else 'Без задачи',
                    "description": entry.get('description', '')
                }
                
                user_data["work_sessions"][entry_date]["sessions"].append(clickup_session)
                user_data["work_sessions"][entry_date]["total_hours"] += duration_hours
                user_data["work_sessions"][entry_date]["total_earnings"] += earnings
                
                # Отмечаем запись как синхронизированную
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

    def setup_handlers(self):
        """Настройка обработчиков команд"""

        @self.dp.message(Command("start"))
        async def start_command(message: Message, state: FSMContext):
            user_id = str(message.from_user.id)
            user_data = self.get_user_data(user_id)

            welcome_text = (
                "🎯 Добро пожаловать в бота для подсчета зарплаты!\n\n"
                "Этот бот поможет вам отслеживать рабочее время и рассчитывать заработок.\n\n"
                "📋 Основные команды:\n"
                "/setrate - установить ставку (руб/час)\n"
                "/addtime - добавить отработанное время\n"
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
                "/help - показать полную справку\n\n"
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
                "🏠 Основные команды:\n"
                "/start - главное меню\n"
                "/setrate - установить ставку (руб/час)\n"
                "/addtime - добавить отработанное время\n"
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
                "/clickupstatus - статус интеграции и активные таймеры\n\n"
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
                    "timestamp": datetime.now().isoformat(),
                    "source": "manual"
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
            
            # Валидация формата токена
            if not token.startswith('pk_') or len(token) < 20:
                await message.answer("❌ Неверный формат токена! Токен должен начинаться с 'pk_' и содержать не менее 20 символов.")
                return
            
            user_id = str(message.from_user.id)
            user_data = self.get_user_data(user_id)
            user_data["clickup_settings"]["api_token"] = token
            self.save_data()
            
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
            
            # Валидация workspace ID
            if not workspace_id.isdigit() or len(workspace_id) < 8:
                await message.answer("❌ Неверный формат Workspace ID! ID должен содержать только цифры и быть не менее 8 символов.")
                return
            
            user_id = str(message.from_user.id)
            user_data = self.get_user_data(user_id)
            
            # Получаем API токен для валидации
            api_token = user_data["clickup_settings"].get("api_token")
            if not api_token:
                await message.answer("❌ Сначала установите API токен командой /clickup_token")
                return
            
            await message.answer("🔄 Проверяю подключение к ClickUp...")
            
            # Валидируем credentials
            validation_result = await self.validate_clickup_credentials(api_token, workspace_id)
            
            if validation_result["success"]:
                user_data["clickup_settings"]["workspace_id"] = workspace_id
                user_data["clickup_settings"]["team_id"] = validation_result["team_id"]
                self.save_data()
                
                await message.answer(f"✅ ClickUp интеграция настроена успешно!\n\n"
                                    f"🏢 Team ID: {validation_result['team_id']}\n\n"
                                    f"Теперь вы можете использовать:\n"
                                    f"/syncclickup - синхронизация за сегодня\n"
                                    f"/synclast - синхронизация за последние дни")
            else:
                await message.answer(f"❌ Ошибка подключения: {validation_result['error']}\n\n"
                                    f"Проверьте правильность API токена и Workspace ID.")
            
            await state.clear()

        @self.dp.message(Command("clickup_reset"))
        async def clickup_reset_command(message: Message):
            user_id = str(message.from_user.id)
            user_data = self.get_user_data(user_id)
            
            user_data["clickup_settings"] = {
                "api_token": None,
                "workspace_id": None,
                "team_id": None
            }
            self.save_data()
            
            await message.answer("🗑 Настройки ClickUp сброшены.\n\n"
                                "Для повторной настройки используйте /clickup_setup")

        @self.dp.message(Command("syncclickup"))
        async def sync_clickup_command(message: Message):
            user_id = str(message.from_user.id)
            user_data = self.get_user_data(user_id)
            
            if not self.get_user_clickup_client(user_id):
                await message.answer("❌ ClickUp не настроен для вашего аккаунта\n\nИспользуйте /clickup_setup для настройки")
                return
            
            if user_data["rate"] <= 0:
                await message.answer("❌ Сначала установите ставку командой /setrate")
                return
                
            await message.answer("🔄 Синхронизирую данные ClickUp за сегодня...")
            
            # Синхронизация за сегодня
            today = datetime.now()
            start_of_today = today.replace(hour=0, minute=0, second=0, microsecond=0)
            
            result = await self.sync_clickup_entries(user_id, start_of_today, today)
            
            if result["success"]:
                if result["synced_count"] > 0:
                    response = (
                        f"✅ Синхронизация завершена!\n\n"
                        f"📥 Синхронизировано записей: {result['synced_count']}\n"
                        f"⏰ Всего времени: {self.format_hours_minutes(result['total_hours'])}\n"
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
            user_data = self.get_user_data(user_id)
            
            if not self.get_user_clickup_client(user_id):
                await message.answer("❌ ClickUp не настроен для вашего аккаунта\n\nИспользуйте /clickup_setup для настройки")
                return
            
            if user_data["rate"] <= 0:
                await message.answer("❌ Сначала установите ставку командой /setrate")
                return
            
            # Получаем количество дней из команды (по умолчанию 7)
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
            
            # Синхронизация за последние N дней
            end_date = datetime.now()
            start_date = end_date - timedelta(days=days)
            
            result = await self.sync_clickup_entries(user_id, start_date, end_date)
            
            if result["success"]:
                if result["synced_count"] > 0:
                    response = (
                        f"✅ Синхронизация завершена!\n\n"
                        f"📅 Период: {days} дней\n"
                        f"📥 Синхронизировано записей: {result['synced_count']}\n"
                        f"⏰ Всего времени: {self.format_hours_minutes(result['total_hours'])}\n"
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
            clickup_client = self.get_user_clickup_client(user_id)
            
            if not clickup_client:
                await message.answer("❌ ClickUp не настроен для вашего аккаунта\n\nИспользуйте /clickup_setup для настройки")
                return
            
            await message.answer("🔍 Проверяю статус ClickUp...")
            
            # Проверяем подключение
            team_id = await clickup_client.get_team_id()
            if not team_id:
                await message.answer("❌ Не удалось подключиться к ClickUp. Проверьте настройки API.")
                return
            
            # Проверяем активные таймеры
            current_timer = await clickup_client.get_current_timer()
            
            response = "✅ ClickUp интеграция активна\n\n"
            response += f"🏢 Team ID: {team_id}\n"
            
            if current_timer:
                task_name = "Неизвестная задача"
                if current_timer.get('task'):
                    task_name = current_timer['task'].get('name', task_name)
                
                start_time = datetime.fromtimestamp(int(current_timer.get('start', 0)) / 1000)
                response += f"\n⏳ Активный таймер:\n📋 Задача: {task_name}\n🕐 Запущен: {start_time.strftime('%H:%M %d.%m.%Y')}"
            else:
                response += "\n⏹ Активных таймеров нет"
            
            user_data = self.get_user_data(user_id)
            synced_count = len(user_data.get("clickup_synced_entries", set()))
            response += f"\n\n📊 Синхронизировано записей: {synced_count}"
            
            await message.answer(response)

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

            # Получить первый и последний день текущего месяца
            today = datetime.now()
            first_day_of_month = today.replace(day=1)
            
            # Последний день месяца
            if today.month == 12:
                last_day_of_month = today.replace(day=31)
            else:
                last_day_of_month = today.replace(day=1, month=today.month+1) - timedelta(days=1)
            
            weeks_data = []
            total_month_hours = 0
            total_month_earnings = 0
            week_number = 1
            
            current_start = first_day_of_month
            
            # Проходим по неделям внутри месяца
            while current_start <= today and current_start.month == today.month:
                # Определяем конец недели
                if current_start == first_day_of_month:
                    # Первая неделя: от 1 числа до ближайшего воскресенья
                    days_until_sunday = (6 - current_start.weekday()) % 7
                    week_end = current_start + timedelta(days=days_until_sunday)
                else:
                    # Обычная неделя: 7 дней от понедельника
                    week_end = current_start + timedelta(days=6)
                
                # Ограничиваем концом месяца и сегодняшним днем
                week_end = min(week_end, last_day_of_month, today)
                
                week_hours = 0
                week_earnings = 0
                
                # Подсчет для текущей недели
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
                
                # Переход к следующей неделе
                if current_start == first_day_of_month:
                    # После первой недели переходим к понедельнику
                    days_until_sunday = (6 - current_start.weekday()) % 7
                    current_start = current_start + timedelta(days=days_until_sunday + 1)
                else:
                    # Обычный переход на следующий понедельник
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

            await message.answer("\n".join(response_lines))

        @self.dp.message(Command("year"))
        async def year_command(message: Message):
            user_id = str(message.from_user.id)
            user_data = self.get_user_data(user_id)

            # Получить текущий год
            current_year = datetime.now().year
            
            # Словарь для хранения данных по месяцам
            months_data = {}
            total_year_hours = 0
            total_year_earnings = 0
            
            # Проходим по всем рабочим сессиям пользователя
            for date_str, session in user_data["work_sessions"].items():
                try:
                    session_date = datetime.strptime(date_str, "%Y-%m-%d")
                    
                    # Проверяем, что дата относится к текущему году
                    if session_date.year == current_year:
                        # Получаем ключ месяца в формате YYYY-MM
                        month_key = session_date.strftime("%Y-%m")
                        
                        if month_key not in months_data:
                            months_data[month_key] = {
                                'hours': 0,
                                'earnings': 0,
                                'date_obj': session_date  # Для сортировки
                            }
                        
                        months_data[month_key]['hours'] += session["total_hours"]
                        months_data[month_key]['earnings'] += session["total_earnings"]
                        total_year_hours += session["total_hours"]
                        total_year_earnings += session["total_earnings"]
                        
                except ValueError:
                    # Пропускаем некорректные даты
                    continue
            
            if months_data:
                response_lines = [f"📊 Заработок по месяцам в {current_year} году:\n"]
                
                # Сортируем месяцы по дате
                sorted_months = sorted(months_data.items(), key=lambda x: x[1]['date_obj'])
                
                for month_key, data in sorted_months:
                    month_name = self.get_russian_month_year(data['date_obj'])
                    response_lines.append(
                        f"📅 {month_name}: {self.format_hours_minutes(data['hours'])} = {data['earnings']:.2f} руб"
                    )
                
                response_lines.extend([
                    "",
                    f"📊 Итого за год:",
                    f"📅 Месяцев с работой: {len(months_data)}",
                    f"⏰ Всего отработано: {self.format_hours_minutes(total_year_hours)}",
                    f"💰 Всего заработано: {total_year_earnings:.2f} руб",
                    f"📈 Среднее в месяц: {total_year_earnings / len(months_data):.2f} руб"
                ])
            else:
                response_lines = [f"📊 В {current_year} году нет записей о работе"]

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
