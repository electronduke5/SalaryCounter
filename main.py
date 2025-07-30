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
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
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
    
    async def get_current_user(self) -> Optional[Dict]:
        """Получение информации о текущем пользователе"""
        async def _fetch_user():
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
                url = f"{self.base_url}/user"
                headers = self._get_headers()
                
                logger.info(f"ClickUp API request: GET {url}")
                
                async with session.get(url, headers=headers) as response:
                    response_text = await response.text()
                    logger.info(f"ClickUp API response: {response.status}")
                    
                    if response.status == 200:
                        user_data = await response.json()
                        user = user_data.get('user', {})
                        logger.info(f"Retrieved current user: {user.get('username', 'Unknown')}")
                        return user
                    else:
                        raise aiohttp.ClientError(f"HTTP {response.status}: {response_text}")
        
        try:
            return await retry_with_backoff(_fetch_user)
        except Exception as e:
            logger.error(f"Ошибка получения информации о пользователе: {e}")
            return None
    
    async def get_spaces(self) -> List[Dict]:
        """Получение списка пространств (spaces) в команде"""
        team_id = await self.get_team_id()
        if not team_id:
            return []
        
        async def _fetch_spaces():
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
                url = f"{self.base_url}/team/{team_id}/space"
                headers = self._get_headers()
                
                logger.info(f"ClickUp API request: GET {url}")
                
                async with session.get(url, headers=headers) as response:
                    response_text = await response.text()
                    logger.info(f"ClickUp API response: {response.status}")
                    
                    if response.status == 200:
                        data = await response.json()
                        spaces = data.get('spaces', [])
                        logger.info(f"Retrieved {len(spaces)} spaces")
                        return spaces
                    else:
                        raise aiohttp.ClientError(f"HTTP {response.status}: {response_text}")
        
        try:
            return await retry_with_backoff(_fetch_spaces)
        except Exception as e:
            logger.error(f"Ошибка получения пространств: {e}")
            return []
    
    async def get_folders(self, space_id: str) -> List[Dict]:
        """Получение списка папок в пространстве"""
        async def _fetch_folders():
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
                url = f"{self.base_url}/space/{space_id}/folder"
                headers = self._get_headers()
                
                logger.info(f"ClickUp API request: GET {url}")
                
                async with session.get(url, headers=headers) as response:
                    response_text = await response.text()
                    logger.info(f"ClickUp API response: {response.status}")
                    
                    if response.status == 200:
                        data = await response.json()
                        folders = data.get('folders', [])
                        logger.info(f"Retrieved {len(folders)} folders")
                        return folders
                    else:
                        raise aiohttp.ClientError(f"HTTP {response.status}: {response_text}")
        
        try:
            return await retry_with_backoff(_fetch_folders)
        except Exception as e:
            logger.error(f"Ошибка получения папок: {e}")
            return []
    
    async def get_lists(self, space_id: str, folder_id: str = None) -> List[Dict]:
        """Получение списков в пространстве или папке"""
        async def _fetch_lists():
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
                if folder_id:
                    url = f"{self.base_url}/folder/{folder_id}/list"
                else:
                    url = f"{self.base_url}/space/{space_id}/list"
                
                headers = self._get_headers()
                
                logger.info(f"ClickUp API request: GET {url}")
                
                async with session.get(url, headers=headers) as response:
                    response_text = await response.text()
                    logger.info(f"ClickUp API response: {response.status}")
                    
                    if response.status == 200:
                        data = await response.json()
                        lists = data.get('lists', [])
                        logger.info(f"Retrieved {len(lists)} lists")
                        return lists
                    else:
                        raise aiohttp.ClientError(f"HTTP {response.status}: {response_text}")
        
        try:
            return await retry_with_backoff(_fetch_lists)
        except Exception as e:
            logger.error(f"Ошибка получения списков: {e}")
            return []
    
    async def get_tasks(self, list_id: str, assignee_id: str = None) -> List[Dict]:
        """Получение задач из списка"""
        async def _fetch_tasks():
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as session:
                url = f"{self.base_url}/list/{list_id}/task"
                headers = self._get_headers()
                params = {}
                
                if assignee_id:
                    params['assignees[]'] = assignee_id
                
                logger.info(f"ClickUp API request: GET {url}")
                logger.info(f"Params: {params}")
                
                async with session.get(url, headers=headers, params=params) as response:
                    response_text = await response.text()
                    logger.info(f"ClickUp API response: {response.status}")
                    
                    if response.status == 200:
                        data = await response.json()
                        tasks = data.get('tasks', [])
                        logger.info(f"Retrieved {len(tasks)} tasks")
                        return tasks
                    else:
                        raise aiohttp.ClientError(f"HTTP {response.status}: {response_text}")
        
        try:
            return await retry_with_backoff(_fetch_tasks)
        except Exception as e:
            logger.error(f"Ошибка получения задач: {e}")
            return []
    
    async def get_task_details(self, task_id: str) -> Optional[Dict]:
        """Получение подробной информации о задаче"""
        async def _fetch_task():
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
                url = f"{self.base_url}/task/{task_id}"
                headers = self._get_headers()
                
                logger.info(f"ClickUp API request: GET {url}")
                
                async with session.get(url, headers=headers) as response:
                    response_text = await response.text()
                    logger.info(f"ClickUp API response: {response.status}")
                    
                    if response.status == 200:
                        task = await response.json()
                        logger.info(f"Retrieved task details: {task.get('name', 'Unknown')}")
                        return task
                    else:
                        raise aiohttp.ClientError(f"HTTP {response.status}: {response_text}")
        
        try:
            return await retry_with_backoff(_fetch_task)
        except Exception as e:
            logger.error(f"Ошибка получения информации о задаче: {e}")
            return None
    
    async def update_task_status(self, task_id: str, status: str) -> bool:
        """Обновление статуса задачи"""
        async def _update_status():
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
                url = f"{self.base_url}/task/{task_id}"
                headers = self._get_headers()
                data = {"status": status}
                
                logger.info(f"ClickUp API request: PUT {url}")
                logger.info(f"Data: {data}")
                
                async with session.put(url, headers=headers, json=data) as response:
                    response_text = await response.text()
                    logger.info(f"ClickUp API response: {response.status}")
                    
                    if response.status == 200:
                        logger.info(f"Task status updated to: {status}")
                        return True
                    else:
                        raise aiohttp.ClientError(f"HTTP {response.status}: {response_text}")
        
        try:
            return await retry_with_backoff(_update_status)
        except Exception as e:
            logger.error(f"Ошибка обновления статуса задачи: {e}")
            return False
    
    async def start_timer(self, task_id: str) -> bool:
        """Запуск таймера для задачи"""
        team_id = await self.get_team_id()
        if not team_id:
            return False
        
        async def _start_timer():
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
                url = f"{self.base_url}/team/{team_id}/time_entries/start"
                headers = self._get_headers()
                data = {"tid": task_id}
                
                logger.info(f"ClickUp API request: POST {url}")
                logger.info(f"Data: {data}")
                
                async with session.post(url, headers=headers, json=data) as response:
                    response_text = await response.text()
                    logger.info(f"ClickUp API response: {response.status}")
                    
                    if response.status == 200:
                        logger.info(f"Timer started for task: {task_id}")
                        return True
                    else:
                        raise aiohttp.ClientError(f"HTTP {response.status}: {response_text}")
        
        try:
            return await retry_with_backoff(_start_timer)
        except Exception as e:
            logger.error(f"Ошибка запуска таймера: {e}")
            return False
    
    async def stop_timer(self) -> bool:
        """Остановка текущего таймера"""
        team_id = await self.get_team_id()
        if not team_id:
            return False
        
        async def _stop_timer():
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
                url = f"{self.base_url}/team/{team_id}/time_entries/stop"
                headers = self._get_headers()
                
                logger.info(f"ClickUp API request: POST {url}")
                
                async with session.post(url, headers=headers) as response:
                    response_text = await response.text()
                    logger.info(f"ClickUp API response: {response.status}")
                    
                    if response.status == 200:
                        logger.info("Timer stopped")
                        return True
                    else:
                        raise aiohttp.ClientError(f"HTTP {response.status}: {response_text}")
        
        try:
            return await retry_with_backoff(_stop_timer)
        except Exception as e:
            logger.error(f"Ошибка остановки таймера: {e}")
            return False
    
    async def get_user_tasks(self, assignee_id: str = None) -> List[Dict]:
        """Получение всех задач пользователя из всех списков"""
        all_tasks = []
        
        # Получаем все пространства
        spaces = await self.get_spaces()
        
        for space in spaces:
            space_id = space.get('id')
            
            # Получаем списки напрямую из пространства
            lists = await self.get_lists(space_id)
            
            # Получаем папки и их списки
            folders = await self.get_folders(space_id)
            for folder in folders:
                folder_lists = await self.get_lists(space_id, folder.get('id'))
                lists.extend(folder_lists)
            
            # Получаем задачи из всех списков
            for list_item in lists:
                list_id = list_item.get('id')
                tasks = await self.get_tasks(list_id, assignee_id)
                
                # Добавляем информацию о проекте
                for task in tasks:
                    task['project_name'] = space.get('name', 'Unknown Project')
                    task['list_name'] = list_item.get('name', 'Unknown List')
                
                all_tasks.extend(tasks)
        
        return all_tasks


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
                    "team_id": None,
                    "user_id": None,
                    "username": None
                }
            }
        
        # Обновление структуры для старых пользователей
        if "clickup_synced_entries" not in self.data[user_id]:
            self.data[user_id]["clickup_synced_entries"] = set()
        
        if "clickup_settings" not in self.data[user_id]:
            self.data[user_id]["clickup_settings"] = {
                "api_token": None,
                "workspace_id": None,
                "team_id": None,
                "user_id": None,
                "username": None
            }
        
        # Добавляем новые поля для старых пользователей
        if "user_id" not in self.data[user_id]["clickup_settings"]:
            self.data[user_id]["clickup_settings"]["user_id"] = None
        if "username" not in self.data[user_id]["clickup_settings"]:
            self.data[user_id]["clickup_settings"]["username"] = None
            
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
        """Валидация ClickUp credentials и получение информации о пользователе"""
        try:
            client = ClickUpClient(api_token, workspace_id)
            team_id = await client.get_team_id()
            
            if not team_id:
                return {"success": False, "error": "Не удалось получить доступ к workspace"}
            
            # Получаем информацию о текущем пользователе
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
            # Получаем название задачи
            task_name = "Ручная запись"  # По умолчанию для ручных записей
            
            if session.get("source") == "clickup":
                task_name = session.get("task_name", "Неизвестная задача")
            
            # Инициализируем задачу если её ещё нет
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
            
            # Добавляем данные сессии к задаче
            task_data = tasks[task_name]
            session_hours = session.get("hours", 0) + session.get("minutes", 0) / 60
            session_earnings = session.get("earnings", 0)
            session_timestamp = session.get("timestamp")
            
            task_data["total_hours"] += session_hours
            task_data["total_earnings"] += session_earnings
            task_data["sessions_count"] += 1
            task_data["sessions"].append(session)
            
            # Обновляем временные рамки
            if session_timestamp:
                if not task_data["first_session"] or session_timestamp < task_data["first_session"]:
                    task_data["first_session"] = session_timestamp
                if not task_data["last_session"] or session_timestamp > task_data["last_session"]:
                    task_data["last_session"] = session_timestamp
        
        return tasks

    def get_tasks_summary(self, user_id: str, start_date: datetime, end_date: datetime) -> Dict[str, Any]:
        """Получение сводки по задачам за указанный период"""
        user_data = self.get_user_data(user_id)
        
        # Собираем все сессии за указанный период
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
        
        # Группируем сессии по задачам
        tasks_grouped = self.group_sessions_by_task(all_sessions)
        
        # Считаем общую статистику
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

    def create_task_keyboard(self, task_data: Dict) -> InlineKeyboardMarkup:
        """Создание inline клавиатуры для задачи"""
        task_id = task_data.get('id')
        current_status = task_data.get('status', {}).get('status', '').lower()
        
        keyboard = []
        
        # Первая строка: Инфо и управление таймером
        row1 = [
            InlineKeyboardButton(text="📋 Инфо", callback_data=f"task_info_{task_id}"),
        ]
        
        # Проверяем, есть ли активный таймер (более универсальная проверка)
        # В ClickUp активный таймер может быть у задачи с любым статусом
        row1.append(InlineKeyboardButton(text="⏱️ Старт", callback_data=f"timer_start_{task_id}"))
        row1.append(InlineKeyboardButton(text="⏹️ Стоп", callback_data=f"timer_stop_{task_id}"))
        
        keyboard.append(row1)
        
        # Вторая строка: Статусы
        status_buttons = []
        
        # Основные статусы с эмодзи (используем статусы из ClickUp)
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
        
        # Разбиваем кнопки статусов на строки по 2
        for i in range(0, len(status_buttons), 2):
            keyboard.append(status_buttons[i:i+2])
        
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
        
        # Исполнители
        assignees = task_data.get('assignees', [])
        assignee_names = [assignee.get('username', 'Unknown') for assignee in assignees]
        assignee_text = ', '.join(assignee_names) if assignee_names else 'Не назначен'
        
        # Дедлайн
        due_date = task_data.get('due_date')
        due_text = "Не установлен"
        if due_date:
            try:
                due_timestamp = int(due_date) / 1000
                due_datetime = datetime.fromtimestamp(due_timestamp)
                due_text = due_datetime.strftime('%d.%m.%Y %H:%M')
            except:
                due_text = "Некорректная дата"
        
        # URL задачи
        task_url = task_data.get('url', '')
        
        info_text = (
            f"📋 *{name}*\n\n"
            f"📊 *Статус:* {status}\n"
            f"🏗 *Проект:* {project}\n"
            f"📁 *Список:* {list_name}\n"
            f"👤 *Исполнитель:* {assignee_text}\n"
            f"⏰ *Дедлайн:* {due_text}\n\n"
        )
        
        if description and description.strip():
            # Ограничиваем длину описания
            if len(description) > 200:
                description = description[:200] + "..."
            info_text += f"📝 *Описание:*\n{description}\n\n"
        
        if task_url:
            info_text += f"🔗 [Открыть в ClickUp]({task_url})"
        
        return info_text
    
    async def get_user_tasks_grouped(self, user_id: str) -> Dict[str, Any]:
        """Получение задач пользователя, сгруппированных по проектам"""
        clickup_client = self.get_user_clickup_client(user_id)
        if not clickup_client:
            return {"success": False, "error": "ClickUp не настроен"}
        
        try:
            # Получаем все задачи пользователя
            all_tasks = await clickup_client.get_user_tasks()
            
            if not all_tasks:
                return {"success": True, "tasks": {}, "total": 0}
            
            # Группируем по проектам
            grouped_tasks = self.group_tasks_by_project(all_tasks)
            
            return {
                "success": True,
                "tasks": grouped_tasks,
                "total": len(all_tasks)
            }
            
        except Exception as e:
            logger.error(f"Ошибка получения задач: {e}")
            return {"success": False, "error": str(e)}
    
    async def get_user_projects(self, user_id: str) -> Dict[str, Any]:
        """Получение списка проектов пользователя"""
        clickup_client = self.get_user_clickup_client(user_id)
        if not clickup_client:
            return {"success": False, "error": "ClickUp не настроен"}
        
        try:
            # Получаем все задачи для определения проектов
            all_tasks = await clickup_client.get_user_tasks()
            
            if not all_tasks:
                return {"success": True, "projects": [], "total": 0}
            
            # Извлекаем уникальные проекты
            projects = {}
            for task in all_tasks:
                project_name = task.get('project_name', 'Неизвестный проект')
                project_id = task.get('space', {}).get('id', 'unknown')
                
                if project_id not in projects:
                    projects[project_id] = {
                        'id': project_id,
                        'name': project_name,
                        'task_count': 0
                    }
                
                projects[project_id]['task_count'] += 1
            
            return {
                "success": True,
                "projects": list(projects.values()),
                "total": len(projects)
            }
            
        except Exception as e:
            logger.error(f"Ошибка получения проектов: {e}")
            return {"success": False, "error": str(e)}
    
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
    
    def filter_tasks_by_project_and_status(self, all_tasks: List[Dict], project_id: str, status: str) -> List[Dict]:
        """Фильтрация задач по проекту и статусу"""
        filtered_tasks = []
        
        for task in all_tasks:
            # Фильтр по проекту
            task_project_id = task.get('space', {}).get('id', 'unknown')
            if project_id != 'all' and task_project_id != project_id:
                continue
            
            # Фильтр по статусу
            task_status = task.get('status', {}).get('status', '').lower()
            if status != 'all' and task_status != status:
                continue
            
            filtered_tasks.append(task)
        
        return filtered_tasks
    
    def create_projects_keyboard(self, projects: List[Dict]) -> InlineKeyboardMarkup:
        """Создание клавиатуры для выбора проекта"""
        keyboard = []
        
        for project in projects:
            project_id = project['id']
            project_name = project['name']
            task_count = project['task_count']
            
            # Ограничиваем длину названия проекта
            if len(project_name) > 30:
                display_name = project_name[:30] + "..."
            else:
                display_name = project_name
            
            button_text = f"🏗 {display_name} ({task_count})"
            keyboard.append([
                InlineKeyboardButton(
                    text=button_text,
                    callback_data=f"project_select_{project_id}"
                )
            ])
        
        return InlineKeyboardMarkup(inline_keyboard=keyboard)
    
    def create_status_keyboard(self, project_id: str) -> InlineKeyboardMarkup:
        """Создание клавиатуры для выбора статуса"""
        keyboard = []
        statuses = self.get_available_statuses()
        
        # Добавляем кнопки статусов по 2 в строке
        for i in range(0, len(statuses), 2):
            row = []
            for j in range(2):
                if i + j < len(statuses):
                    status = statuses[i + j]
                    row.append(
                        InlineKeyboardButton(
                            text=status['name'],
                            callback_data=f"status_select_{project_id}_{status['key']}"
                        )
                    )
            keyboard.append(row)
        
        # Кнопка "Назад к проектам"
        keyboard.append([
            InlineKeyboardButton(
                text="🔙 Назад к проектам",
                callback_data="back_to_projects"
            )
        ])
        
        return InlineKeyboardMarkup(inline_keyboard=keyboard)

    def format_task_summary(self, summary_data: Dict[str, Any]) -> str:
        """Форматирование сводки по задачам для отображения"""
        if not summary_data["tasks"]:
            return "📊 За указанный период задач не найдено"
        
        # Заголовок с периодом
        start_date = summary_data["period_start"]
        end_date = summary_data["period_end"]
        
        if start_date.date() == end_date.date():
            period_str = start_date.strftime("%d.%m.%Y")
        else:
            period_str = f"{start_date.strftime('%d.%m')} - {end_date.strftime('%d.%m.%Y')}"
        
        response_lines = [f"📊 Сводка по задачам за {period_str}:\n"]
        
        # Сортируем задачи по заработку (по убыванию)
        sorted_tasks = sorted(
            summary_data["tasks"].values(), 
            key=lambda x: x["total_earnings"], 
            reverse=True
        )
        
        # Добавляем информацию по каждой задаче
        for task in sorted_tasks:
            task_name = task["task_name"]
            total_hours = task["total_hours"]
            total_earnings = task["total_earnings"]
            sessions_count = task["sessions_count"]
            
            # Эмодзи в зависимости от источника
            source_emoji = "🔗" if task["source_type"] == "clickup" else "✏️"
            
            response_lines.append(f"{source_emoji} {task_name}")
            response_lines.append(f"⏱️ Время: {self.format_hours_minutes(total_hours)} ({sessions_count} сессий)")
            response_lines.append(f"💰 Заработок: {total_earnings:.2f} руб")
            
            # Добавляем период работы над задачей
            if task["first_session"] and task["last_session"]:
                first_date = datetime.fromisoformat(task["first_session"]).strftime("%d.%m")
                last_date = datetime.fromisoformat(task["last_session"]).strftime("%d.%m")
                if first_date == last_date:
                    response_lines.append(f"📅 Дата: {first_date}")
                else:
                    response_lines.append(f"📅 Период: {first_date} - {last_date}")
            
            response_lines.append("")  # Пустая строка между задачами
        
        # Итоговая статистика
        response_lines.extend([
            "═══════════════════════════════════",
            f"📊 ИТОГО: {self.format_hours_minutes(summary_data['total_hours'])} = {summary_data['total_earnings']:.2f} руб",
            f"🎯 Задач: {summary_data['total_tasks']} | 📈 Сессий: {summary_data['total_sessions']}"
        ])
        
        return "\n".join(response_lines)

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
                "📊 Аналитика:\n"
                "/tasksummary - сводка по задачам за неделю\n\n"
                "🎯 Управление задачами:\n"
                "/tasks - список задач по проектам\n"
                "/active_task - просмотр активной задачи\n\n"
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
                user_data["clickup_settings"]["user_id"] = validation_result["user_id"]
                user_data["clickup_settings"]["username"] = validation_result["username"]
                self.save_data()
                
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
            user_data = self.get_user_data(user_id)
            
            user_data["clickup_settings"] = {
                "api_token": None,
                "workspace_id": None,
                "team_id": None
            }
            self.save_data()
            
            await message.answer("🗑 Настройки ClickUp сброшены.\n\n"
                                "Для повторной настройки используйте /clickup_setup")

        @self.dp.message(Command("tasksummary"))
        async def task_summary_command(message: Message):
            user_id = str(message.from_user.id)
            user_data = self.get_user_data(user_id)
            
            if user_data["rate"] <= 0:
                await message.answer("❌ Сначала установите ставку командой /setrate")
                return
            
            # Парсим аргументы команды для определения периода
            command_parts = message.text.strip().split()
            period = "week"  # По умолчанию неделя
            
            if len(command_parts) > 1:
                period = command_parts[1].lower()
            
            # Определяем временной период
            now = datetime.now()
            
            if period == "today":
                start_date = now.replace(hour=0, minute=0, second=0, microsecond=0)
                end_date = now
                period_name = "сегодня"
            elif period == "yesterday":
                yesterday = now - timedelta(days=1)
                start_date = yesterday.replace(hour=0, minute=0, second=0, microsecond=0)
                end_date = yesterday.replace(hour=23, minute=59, second=59)
                period_name = "вчера"
            elif period == "week":
                # Неделя с понедельника
                monday = now - timedelta(days=now.weekday())
                start_date = monday.replace(hour=0, minute=0, second=0, microsecond=0)
                end_date = now
                period_name = "неделю"
            elif period == "month":
                # Текущий месяц
                start_date = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
                end_date = now
                period_name = "месяц"
            elif period.isdigit():
                # Последние N дней
                days = int(period)
                if days <= 0 or days > 365:
                    await message.answer("❌ Количество дней должно быть от 1 до 365")
                    return
                start_date = (now - timedelta(days=days-1)).replace(hour=0, minute=0, second=0, microsecond=0)
                end_date = now
                period_name = f"последние {days} дней"
            else:
                await message.answer("❌ Неверный период. Используйте: today, yesterday, week, month или число дней\n\n"
                                    "Примеры:\n"
                                    "/tasksummary - за неделю\n"
                                    "/tasksummary today - за сегодня\n"
                                    "/tasksummary month - за месяц\n"
                                    "/tasksummary 7 - за последние 7 дней")
                return
            
            await message.answer(f"📊 Анализирую задачи за {period_name}...")
            
            # Получаем сводку по задачам
            summary = self.get_tasks_summary(user_id, start_date, end_date)
            
            # Форматируем и отправляем результат
            formatted_summary = self.format_task_summary(summary)
            
            # Если сообщение слишком длинное, разбиваем на части
            if len(formatted_summary) > 4000:
                # Отправляем по частям
                parts = formatted_summary.split('\n\n')
                current_part = ""
                
                for part in parts:
                    if len(current_part + part + '\n\n') > 4000:
                        if current_part:
                            await message.answer(current_part)
                            current_part = part + '\n\n'
                        else:
                            # Если даже одна часть слишком длинная
                            await message.answer(part)
                    else:
                        current_part += part + '\n\n'
                
                if current_part:
                    await message.answer(current_part)
            else:
                await message.answer(formatted_summary)

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

        @self.dp.message(Command("tasks"))
        async def tasks_command(message: Message):
            user_id = str(message.from_user.id)
            clickup_client = self.get_user_clickup_client(user_id)
            
            if not clickup_client:
                await message.answer("❌ ClickUp не настроен для вашего аккаунта\n\nИспользуйте /clickup_setup для настройки")
                return
            
            await message.answer("🔄 Загружаю рабочие пространства из ClickUp...")
            
            # Получаем spaces пользователя
            spaces = await clickup_client.get_spaces()
            
            if not spaces:
                await message.answer("📋 У вас нет доступных рабочих пространств в ClickUp")
                return
            
            # Создаем клавиатуру с spaces
            keyboard = []
            for space in spaces:
                space_id = space.get('id')
                space_name = space.get('name', 'Неизвестное пространство')
                
                # Ограничиваем длину названия
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
            clickup_client = self.get_user_clickup_client(user_id)
            
            if not clickup_client:
                await message.answer("❌ ClickUp не настроен для вашего аккаунта\n\nИспользуйте /clickup_setup для настройки")
                return
            
            await message.answer("🔍 Проверяю активные таймеры...")
            
            # Получаем текущий таймер
            current_timer = await clickup_client.get_current_timer()
            
            if not current_timer:
                await message.answer("⏹ Активных таймеров не найдено")
                return
            
            # Получаем подробную информацию о задаче
            task_id = current_timer.get('task', {}).get('id')
            if not task_id:
                await message.answer("❌ Не удалось получить информацию о задаче")
                return
            
            task_details = await clickup_client.get_task_details(task_id)
            if not task_details:
                await message.answer("❌ Не удалось загрузить детали задачи")
                return
            
            # Время работы
            start_time = datetime.fromtimestamp(int(current_timer.get('start', 0)) / 1000)
            current_time = datetime.now()
            working_time = current_time - start_time
            
            # Форматируем время работы
            hours = int(working_time.total_seconds() // 3600)
            minutes = int((working_time.total_seconds() % 3600) // 60)
            time_text = f"{hours}ч {minutes}м"
            
            # Создаем сообщение
            task_name = task_details.get('name', 'Неизвестная задача')
            # Пытаемся получить имя проекта из разных источников
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
            
            # Создаем клавиатуру для управления
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [
                    InlineKeyboardButton(text="📋 Подробнее", callback_data=f"task_info_{task_id}"),
                    InlineKeyboardButton(text="⏹️ Остановить", callback_data=f"timer_stop_{task_id}")
                ]
            ])
            
            await message.answer(active_text, reply_markup=keyboard, parse_mode="Markdown")
        
        # Обработчики callback запросов
        @self.dp.callback_query(F.data.startswith("task_info_"))
        async def handle_task_info(callback: CallbackQuery):
            task_id = callback.data.split("_")[-1]
            user_id = str(callback.from_user.id)
            clickup_client = self.get_user_clickup_client(user_id)
            
            if not clickup_client:
                await callback.answer("❌ ClickUp не настроен", show_alert=True)
                return
            
            # Получаем подробную информацию о задаче
            task_details = await clickup_client.get_task_details(task_id)
            if not task_details:
                await callback.answer("❌ Не удалось загрузить задачу", show_alert=True)
                return
            
            # Форматируем информацию
            info_text = self.format_task_info(task_details)
            
            # Создаем кнопку "Назад"
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
            clickup_client = self.get_user_clickup_client(user_id)
            
            if not clickup_client:
                await callback.answer("❌ ClickUp не настроен", show_alert=True)
                return
            
            # Получаем информацию о задаче для восстановления исходного сообщения
            task_details = await clickup_client.get_task_details(task_id)
            if not task_details:
                await callback.answer("❌ Не удалось загрузить задачу", show_alert=True)
                return
            
            task_name = task_details.get('name', 'Без названия')
            task_status = task_details.get('status', {}).get('status', 'Неизвестен')
            
            # Ограничиваем длину названия
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
            clickup_client = self.get_user_clickup_client(user_id)
            
            if not clickup_client:
                await callback.answer("❌ ClickUp не настроен", show_alert=True)
                return
            
            await callback.answer("⏱️ Запуск таймера...")
            
            # Запускаем таймер
            success = await clickup_client.start_timer(task_id)
            
            if success:
                # Получаем обновленную информацию о задаче
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
            clickup_client = self.get_user_clickup_client(user_id)
            
            if not clickup_client:
                await callback.answer("❌ ClickUp не настроен", show_alert=True)
                return
            
            await callback.answer("⏹️ Остановка таймера...")
            
            # Останавливаем таймер
            success = await clickup_client.stop_timer()
            
            if success:
                # Получаем обновленную информацию о задаче
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
            clickup_client = self.get_user_clickup_client(user_id)
            
            if not clickup_client:
                await callback.answer("❌ ClickUp не настроен", show_alert=True)
                return
            
            await callback.answer(f"🔄 Изменение статуса на {new_status}...")
            
            # Обновляем статус задачи
            success = await clickup_client.update_task_status(task_id, new_status)
            
            if success:
                # Получаем обновленную информацию о задаче
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
        
        # Новые обработчики для пошаговой навигации
        @self.dp.callback_query(F.data.startswith("space_select_"))
        async def handle_space_select(callback: CallbackQuery):
            space_id = callback.data.split("_", 2)[2]  # space_select_{space_id}
            user_id = str(callback.from_user.id)
            clickup_client = self.get_user_clickup_client(user_id)
            
            if not clickup_client:
                await callback.answer("❌ ClickUp не настроен", show_alert=True)
                return
            
            await callback.answer("📁 Загрузка папок...")
            
            # Получаем folders в выбранном space
            folders = await clickup_client.get_folders(space_id)
            
            # Получаем информацию о space для отображения
            spaces = await clickup_client.get_spaces()
            space_name = "Неизвестное пространство"
            for space in spaces:
                if space.get('id') == space_id:
                    space_name = space.get('name', space_name)
                    break
            
            if not folders:
                # Если нет папок, показываем списки напрямую из space
                lists = await clickup_client.get_lists(space_id)
                
                if not lists:
                    # Создаем кнопку назад
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
                
                # Показываем списки напрямую
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
                
                # Кнопка назад
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
            
            # Показываем папки
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
            
            # Добавляем списки из корня space (без папок)
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
            
            # Кнопка назад
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
            parts = callback.data.split("_", 3)  # folder_select_{space_id}_{folder_id}
            space_id = parts[2]
            folder_id = parts[3]
            
            user_id = str(callback.from_user.id)
            clickup_client = self.get_user_clickup_client(user_id)
            
            if not clickup_client:
                await callback.answer("❌ ClickUp не настроен", show_alert=True)
                return
            
            await callback.answer("📋 Загрузка списков...")
            
            # Получаем lists в выбранной folder
            lists = await clickup_client.get_lists(space_id, folder_id)
            
            # Получаем информацию о folder для отображения
            folders = await clickup_client.get_folders(space_id)
            folder_name = "Неизвестная папка"
            for folder in folders:
                if folder.get('id') == folder_id:
                    folder_name = folder.get('name', folder_name)
                    break
            
            if not lists:
                # Создаем кнопку назад
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
            
            # Показываем списки
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
            
            # Кнопка назад
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
            parts = callback.data.split("_", 4)  # list_select_{space_id}_{folder_id}_{list_id}
            space_id = parts[2]
            folder_id = parts[3] if parts[3] != 'none' else None
            list_id = parts[4]
            
            user_id = str(callback.from_user.id)
            clickup_client = self.get_user_clickup_client(user_id)
            
            if not clickup_client:
                await callback.answer("❌ ClickUp не настроен", show_alert=True)
                return
            
            await callback.answer("📊 Выбор статуса...")
            
            # Получаем информацию о списке для отображения
            if folder_id:
                lists = await clickup_client.get_lists(space_id, folder_id)
            else:
                lists = await clickup_client.get_lists(space_id)
            
            list_name = "Неизвестный список"
            for list_item in lists:
                if list_item.get('id') == list_id:
                    list_name = list_item.get('name', list_name)
                    break
            
            # Создаем клавиатуру для выбора статуса
            keyboard = []
            statuses = self.get_available_statuses()
            
            # Добавляем кнопки статусов по 2 в строке
            for i in range(0, len(statuses), 2):
                row = []
                for j in range(2):
                    if i + j < len(statuses):
                        status = statuses[i + j]
                        row.append(
                            InlineKeyboardButton(
                                text=status['name'],
                                callback_data=f"final_status_select_{list_id}_{status['key']}"
                            )
                        )
                keyboard.append(row)
            
            # Кнопка "Назад"
            if folder_id:
                back_callback = f"folder_select_{space_id}_{folder_id}"
                back_text = "🔙 Назад к спискам"
            else:
                back_callback = f"space_select_{space_id}"
                back_text = "🔙 Назад к папкам"
            
            keyboard.append([
                InlineKeyboardButton(
                    text=back_text,
                    callback_data=back_callback
                )
            ])
            
            keyboard_markup = InlineKeyboardMarkup(inline_keyboard=keyboard)
            
            status_text = (
                f"📋 *{list_name}*\n\n"
                f"Выберите статус задач для просмотра:"
            )
            
            await callback.message.edit_text(
                status_text,
                reply_markup=keyboard_markup,
                parse_mode="Markdown"
            )
        
        @self.dp.callback_query(F.data.startswith("final_status_select_"))
        async def handle_final_status_select(callback: CallbackQuery):
            parts = callback.data.split("_", 3)  # final_status_select_{list_id}_{status}
            list_id = parts[2]
            status = parts[3]
            
            user_id = str(callback.from_user.id)
            clickup_client = self.get_user_clickup_client(user_id)
            user_data = self.get_user_data(user_id)
            
            if not clickup_client:
                await callback.answer("❌ ClickUp не настроен", show_alert=True)
                return
            
            # Получаем ID текущего пользователя
            clickup_user_id = user_data["clickup_settings"].get("user_id")
            if not clickup_user_id:
                await callback.answer("❌ Не найден ID пользователя ClickUp", show_alert=True)
                return
            
            await callback.answer("🔄 Загрузка ваших задач...")
            
            try:
                # Получаем задачи из конкретного списка, назначенные на текущего пользователя
                if status == "all":
                    tasks = await clickup_client.get_tasks(list_id, clickup_user_id)
                else:
                    # Получаем все задачи пользователя и фильтруем по статусу
                    all_tasks = await clickup_client.get_tasks(list_id, clickup_user_id)
                    tasks = [task for task in all_tasks 
                            if task.get('status', {}).get('status', '').lower() == status.lower()]
                
                if not tasks:
                    # Получаем название списка для отображения
                    list_details = None
                    try:
                        # Пытаемся получить детали списка (это может потребовать дополнительный API вызов)
                        list_name = "Выбранный список"
                    except:
                        list_name = "Выбранный список"
                    
                    status_display = status.title() if status != 'all' else 'Все'
                    
                    # Создаем кнопку назад 
                    back_keyboard = InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(
                            text="🔙 Назад к статусам",
                            callback_data=f"back_to_list_{list_id}"
                        )]
                    ])
                    
                    await callback.message.edit_text(
                        f"📋 *{list_name}*\n📊 Статус: {status_display}\n\n❌ У вас нет задач с данным статусом",
                        reply_markup=back_keyboard,
                        parse_mode="Markdown"
                    )
                    return
                
                # Получаем название списка из первой задачи
                list_name = tasks[0].get('list', {}).get('name', 'Неизвестный список')
                status_display = status.title() if status != 'all' else 'Все'
                
                header_text = (
                    f"📋 *{list_name}*\n"
                    f"📊 Статус: {status_display}\n"
                    f"👤 Ваших задач: {len(tasks)}\n\n"
                    f"Управляйте задачами с помощью кнопок:"
                )
                
                # Кнопка назад к статусам
                back_keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(
                        text="🔙 Назад к статусам",
                        callback_data=f"back_to_list_{list_id}"
                    )]
                ])
                
                await callback.message.edit_text(
                    header_text,
                    reply_markup=back_keyboard,
                    parse_mode="Markdown"
                )
                
                # Отправляем задачи с кнопками управления
                for task in tasks:
                    task_name = task.get('name', 'Без названия')
                    task_status = task.get('status', {}).get('status', 'Неизвестен')
                    
                    # Ограничиваем длину названия
                    if len(task_name) > 50:
                        display_name = task_name[:50] + "..."
                    else:
                        display_name = task_name
                    
                    keyboard = self.create_task_keyboard(task)
                    
                    await callback.message.answer(
                        f"📋 *{display_name}*\n📊 {task_status}",
                        reply_markup=keyboard,
                        parse_mode="Markdown"
                    )
                    
                    # Небольшая пауза между сообщениями
                    await asyncio.sleep(0.1)
                    
            except Exception as e:
                logger.error(f"Ошибка при получении задач: {e}")
                await callback.message.edit_text(f"❌ Ошибка загрузки задач: {str(e)}")
        
        @self.dp.callback_query(F.data.startswith("status_select_"))
        async def handle_status_select(callback: CallbackQuery):
            parts = callback.data.split("_", 3)  # status_select_{project_id}_{status}
            project_id = parts[2]
            status = parts[3]
            
            user_id = str(callback.from_user.id)
            clickup_client = self.get_user_clickup_client(user_id)
            
            if not clickup_client:
                await callback.answer("❌ ClickUp не настроен", show_alert=True)
                return
            
            await callback.answer("🔄 Загрузка задач...")
            
            try:
                # Получаем все задачи пользователя
                all_tasks = await clickup_client.get_user_tasks()
                
                if not all_tasks:
                    await callback.message.edit_text("📋 У вас нет задач в ClickUp")
                    return
                
                # Фильтруем задачи по проекту и статусу
                filtered_tasks = self.filter_tasks_by_project_and_status(all_tasks, project_id, status)
                
                if not filtered_tasks:
                    # Получаем названия для отображения
                    project_name = "Неизвестный проект"
                    status_name = status
                    
                    for task in all_tasks:
                        if task.get('space', {}).get('id') == project_id:
                            project_name = task.get('project_name', project_name)
                            break
                    
                    # Создаем кнопку назад к статусам
                    back_keyboard = InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(
                            text="🔙 Назад к статусам",
                            callback_data=f"project_select_{project_id}"
                        )]
                    ])
                    
                    await callback.message.edit_text(
                        f"📋 В проекте *{project_name}* нет задач со статусом *{status_name}*",
                        reply_markup=back_keyboard,
                        parse_mode="Markdown"
                    )
                    return
                
                # Отправляем первое сообщение с информацией
                project_name = filtered_tasks[0].get('project_name', 'Неизвестный проект')
                status_display = status.title() if status != 'all' else 'Все'
                
                header_text = (
                    f"🏗 *{project_name}*\n"
                    f"📊 Статус: {status_display}\n"
                    f"📋 Найдено задач: {len(filtered_tasks)}\n\n"
                    f"Управляйте задачами с помощью кнопок:"
                )
                
                # Кнопка назад к статусам
                back_keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(
                        text="🔙 Назад к статусам",
                        callback_data=f"project_select_{project_id}"
                    )]
                ])
                
                await callback.message.edit_text(
                    header_text,
                    reply_markup=back_keyboard,
                    parse_mode="Markdown"
                )
                
                # Отправляем задачи с кнопками управления
                for task in filtered_tasks:
                    task_name = task.get('name', 'Без названия')
                    task_status = task.get('status', {}).get('status', 'Неизвестен')
                    
                    # Ограничиваем длину названия
                    if len(task_name) > 50:
                        display_name = task_name[:50] + "..."
                    else:
                        display_name = task_name
                    
                    keyboard = self.create_task_keyboard(task)
                    
                    await callback.message.answer(
                        f"📋 *{display_name}*\n📊 {task_status}",
                        reply_markup=keyboard,
                        parse_mode="Markdown"
                    )
                    
                    # Небольшая пауза между сообщениями
                    await asyncio.sleep(0.1)
                    
            except Exception as e:
                logger.error(f"Ошибка при получении задач: {e}")
                await callback.message.edit_text(f"❌ Ошибка загрузки задач: {str(e)}")
        
        @self.dp.callback_query(F.data == "back_to_projects")
        async def handle_back_to_projects(callback: CallbackQuery):
            user_id = str(callback.from_user.id)
            
            if not self.get_user_clickup_client(user_id):
                await callback.answer("❌ ClickUp не настроен", show_alert=True)
                return
            
            await callback.answer("🔄 Загрузка проектов...")
            
            # Получаем проекты пользователя
            result = await self.get_user_projects(user_id)
            
            if not result["success"]:
                await callback.message.edit_text(f"❌ Ошибка получения проектов: {result['error']}")
                return
            
            if result["total"] == 0:
                await callback.message.edit_text("📋 У вас нет проектов с задачами в ClickUp")
                return
            
            # Создаем клавиатуру с проектами
            keyboard = self.create_projects_keyboard(result["projects"])
            
            projects_text = (
                f"🏗 *Ваши проекты*\n\n"
                f"Найдено проектов: {result['total']}\n"
                f"Выберите проект для просмотра задач:"
            )
            
            await callback.message.edit_text(
                projects_text,
                reply_markup=keyboard,
                parse_mode="Markdown"
            )

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
