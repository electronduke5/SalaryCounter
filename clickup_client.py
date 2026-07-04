import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional

import aiohttp

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

                async with session.get(url, headers=headers) as response:
                    response_text = await response.text()
                    logger.info(f"ClickUp API response: {response.status}")

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

    async def get_list(self, list_id: str) -> Optional[Dict]:
        """Получение информации о списке (проекте) по его id"""
        async def _fetch_list():
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
                url = f"{self.base_url}/list/{list_id}"
                headers = self._get_headers()

                logger.info(f"ClickUp API request: GET {url}")

                async with session.get(url, headers=headers) as response:
                    response_text = await response.text()
                    logger.info(f"ClickUp API response: {response.status}")

                    if response.status == 200:
                        return await response.json()
                    else:
                        raise aiohttp.ClientError(f"HTTP {response.status}: {response_text}")

        try:
            return await retry_with_backoff(_fetch_list)
        except Exception as e:
            logger.error(f"Ошибка получения списка {list_id}: {e}")
            return None

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

        spaces = await self.get_spaces()

        for space in spaces:
            space_id = space.get('id')

            lists = await self.get_lists(space_id)

            folders = await self.get_folders(space_id)
            for folder in folders:
                folder_lists = await self.get_lists(space_id, folder.get('id'))
                lists.extend(folder_lists)

            for list_item in lists:
                list_id = list_item.get('id')
                tasks = await self.get_tasks(list_id, assignee_id)

                for task in tasks:
                    task['project_name'] = space.get('name', 'Unknown Project')
                    task['list_name'] = list_item.get('name', 'Unknown List')

                all_tasks.extend(tasks)

        return all_tasks

    async def get_list_statuses(self, list_id: str) -> List[Dict]:
        """Получение доступных статусов для конкретного списка"""
        async def _fetch_statuses():
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
                url = f"{self.base_url}/list/{list_id}"
                headers = self._get_headers()

                logger.info(f"ClickUp API request: GET {url} (для получения статусов)")

                async with session.get(url, headers=headers) as response:
                    response_text = await response.text()
                    logger.info(f"ClickUp API response: {response.status}")

                    if response.status == 200:
                        data = await response.json()
                        statuses = data.get('statuses', [])
                        logger.info(f"Получено статусов: {len(statuses)}")
                        logger.info(f"Сырые данные статусов из API: {statuses}")

                        formatted_statuses = []
                        for status in statuses:
                            status_name = status.get('status', 'Unknown')
                            formatted_status = {
                                'key': status_name.lower(),
                                'name': status_name,
                                'color': status.get('color', '#000000')
                            }
                            formatted_statuses.append(formatted_status)
                            logger.info(f"Отформатирован статус: {formatted_status}")

                        return formatted_statuses
                    else:
                        raise aiohttp.ClientError(f"HTTP {response.status}: {response_text}")

        try:
            return await retry_with_backoff(_fetch_statuses)
        except Exception as e:
            logger.error(f"Ошибка получения статусов списка: {e}")
            return [
                {"key": "open", "name": "Open", "color": "#ff6b6b"},
                {"key": "in progress", "name": "In Progress", "color": "#4ecdc4"},
                {"key": "review", "name": "Review", "color": "#45b7d1"},
                {"key": "done", "name": "Done", "color": "#96ceb4"},
                {"key": "complete", "name": "Complete", "color": "#ffeaa7"}
            ]
