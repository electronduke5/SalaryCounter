"""
Одноразовый скрипт: проставляет project_name (название списка ClickUp) в уже
сохранённых сессиях, у которых его ещё нет.

Логика: сохранённые сессии хранят только clickup_id (id записи времени) и не
хранят list_id. Поэтому заново запрашиваем записи времени ClickUp за диапазон
дат, встречающихся в данных, строим карту {clickup_id -> list_id}, резолвим
названия списков и заполняем project_name у подходящих сессий.

Запуск:  python backfill_projects.py   (после миграции на SQLite)
"""
import asyncio
from datetime import datetime, timedelta

from dotenv import load_dotenv

load_dotenv()

from data_manager import DataManager

CHUNK_DAYS = 30


def _pending_sessions(dm: DataManager, user_id: str):
    """[(date_str, clickup_id), ...] clickup-сессий без project_name."""
    with dm._lock:
        rows = dm.conn.execute(
            "SELECT date, clickup_id FROM work_sessions "
            "WHERE user_id = ? AND source = 'clickup' AND clickup_id IS NOT NULL "
            "AND (project_name IS NULL OR project_name = '')",
            (user_id,),
        ).fetchall()
    return [(r["date"], r["clickup_id"]) for r in rows]


def _set_project_name(dm: DataManager, user_id: str, clickup_id: str, name: str) -> int:
    with dm._lock:
        cur = dm.conn.execute(
            "UPDATE work_sessions SET project_name = ? "
            "WHERE user_id = ? AND clickup_id = ? "
            "AND (project_name IS NULL OR project_name = '')",
            (name, user_id, clickup_id),
        )
    return cur.rowcount


async def backfill_user(dm: DataManager, user_id: str) -> int:
    client = dm.get_user_clickup_client(user_id)
    if not client:
        print(f"[{user_id}] ClickUp не настроен — пропуск")
        return 0

    pending = _pending_sessions(dm, user_id)
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
    for _date_str, clickup_id in pending:
        list_id = entry_to_list.get(str(clickup_id))
        if not list_id:
            continue
        name = await dm._resolve_list_name(client, list_id, list_name_cache)
        if name:
            updated += _set_project_name(dm, user_id, clickup_id, name)

    print(f"[{user_id}] обновлено сессий: {updated} из {len(pending)}")
    return updated


async def main():
    dm = DataManager()
    with dm._lock:
        user_ids = [r["user_id"] for r in dm.conn.execute("SELECT user_id FROM users")]
    total = 0
    for user_id in user_ids:
        try:
            total += await backfill_user(dm, user_id)
        except Exception as e:
            print(f"[{user_id}] ошибка backfill: {e!r} — пропуск пользователя")
    print(f"Готово. Всего обновлено: {total}." if total else "Изменений нет.")


if __name__ == "__main__":
    asyncio.run(main())
