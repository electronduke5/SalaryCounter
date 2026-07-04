"""
Одноразовый скрипт: проставляет project_name (название списка ClickUp) в уже
сохранённых сессиях, у которых его ещё нет.

Логика: сохранённые сессии хранят только clickup_id (id записи времени) и не
хранят list_id. Поэтому заново запрашиваем записи времени ClickUp за диапазон
дат, встречающихся в данных, строим карту {clickup_id -> list_id}, резолвим
названия списков и заполняем project_name у подходящих сессий.

Запуск:  python backfill_projects.py
"""
import asyncio
from datetime import datetime, timedelta

from data_manager import DataManager

CHUNK_DAYS = 30


def _clickup_sessions_missing_project(user_data):
    for date_str, day in user_data.get("work_sessions", {}).items():
        for session in day.get("sessions", []):
            if session.get("source") == "clickup" and not session.get("project_name"):
                yield date_str, session


async def backfill_user(dm: DataManager, user_id: str) -> int:
    client = dm.get_user_clickup_client(user_id)
    if not client:
        print(f"[{user_id}] ClickUp не настроен — пропуск")
        return 0

    user_data = dm.get_user_data(user_id)
    pending = list(_clickup_sessions_missing_project(user_data))
    if not pending:
        print(f"[{user_id}] нечего заполнять")
        return 0

    dates = [datetime.strptime(d, "%Y-%m-%d") for d, _ in pending]
    start_date = min(dates).replace(hour=0, minute=0, second=0, microsecond=0)
    end_date = max(dates).replace(hour=23, minute=59, second=59) + timedelta(days=1)

    # {clickup_id -> list_id}
    entry_to_list: dict[str, str] = {}
    cursor = start_date
    while cursor < end_date:
        chunk_end = min(cursor + timedelta(days=CHUNK_DAYS), end_date)
        entries = await client.get_time_entries(cursor, chunk_end)
        for entry in entries:
            entry_id = entry.get("id")
            list_id = DataManager._entry_list_id(entry)
            if entry_id and list_id:
                entry_to_list[str(entry_id)] = list_id
        cursor = chunk_end

    list_name_cache: dict[str, str] = {}
    updated = 0
    for _date_str, session in pending:
        list_id = entry_to_list.get(str(session.get("clickup_id")))
        if not list_id:
            continue
        name = await dm._resolve_list_name(client, list_id, list_name_cache)
        if name:
            session["project_name"] = name
            updated += 1

    print(f"[{user_id}] обновлено сессий: {updated} из {len(pending)}")
    return updated


async def main():
    dm = DataManager()
    total = 0
    for user_id in list(dm.data.keys()):
        try:
            total += await backfill_user(dm, user_id)
        except Exception as e:
            print(f"[{user_id}] ошибка backfill: {e!r} — пропуск пользователя")
    if total:
        dm.save_data()
        print(f"Готово. Всего обновлено: {total}. Данные сохранены.")
    else:
        print("Изменений нет — файл не тронут.")


if __name__ == "__main__":
    asyncio.run(main())
