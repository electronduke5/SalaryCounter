# Миграция хранения данных на SQLite — дизайн

Дата: 2026-07-04
Статус: одобрен, готов к плану реализации

## Контекст и проблема

Сейчас данные хранятся в одном файле `salary_data.json` (~1.8 МБ и растёт), ключ — Telegram `user_id`. Файл целиком грузится в память при старте и **целиком переписывается при каждом сохранении**. Бот (`main.py`) и вебапп-API (`api.py`) делят один экземпляр `DataManager` в одном asyncio-процессе.

Проблемы, которые решаем:

1. **Полная перезапись файла на каждый save** — O(n) на любое изменение, растёт бесконечно.
2. **Гонки read-modify-write** — `save_data` синхронно блокирует event loop; последовательность `get_user_data → мутация → save_data` не атомарна между `await`, параллельные синки могут терять записи.
3. **Токены ClickUp в открытом виде** в JSON.
4. **Дублирование производных данных** — `total_hours`/`total_earnings` хранятся и пересчитываются из сессий; `date` дублируется внутри сессии.
5. **`clickup_synced_entries`** — множество, растущее без границ, пишется целиком у каждого пользователя.

Объём работы: **всё сразу** — SQLite + нормализация + шифрование токенов.

## Решения (зафиксированы)

- **Хранилище:** SQLite (один файл, без сервера, транзакции, WAL, безопасная конкурентность).
- **Шифрование:** Fernet (`cryptography`), ключ `ENCRYPTION_KEY` в `.env`.
- **Переход:** код миграции в отдельном модуле `migrate_to_sqlite.py` с верификацией; вызывается автоматически на старте, если `salary.db` ещё нет, и может быть запущен вручную (комбинированный вариант).
- **Архитектура доступа:** Подход B — метод-ориентированный репозиторий вместо возврата мутируемого словаря.

## Архитектура и модули

Маленькие модули с одной ответственностью:

| Файл | Назначение |
|------|-----------|
| `db.py` *(новый)* | Одно соединение SQLite (WAL, `foreign_keys=ON`, `busy_timeout`), DDL-схема, `get_connection()` |
| `crypto.py` *(новый)* | Fernet `encrypt()`/`decrypt()` + генерация ключа; ключ из `ENCRYPTION_KEY` |
| `migrate_to_sqlite.py` *(новый)* | `migrate(json, db)` с верификацией; вызывается и вручную, и автоматически при старте |
| `data_manager.py` *(переписываем)* | Репозиторий: явные методы вместо возврата мутируемого dict. Логика форматирования отчётов сохраняется, меняется только источник данных |
| `main.py` / `api.py` *(правим вызовы)* | Заменяем `get_user_data → мутация → save_data` на методы; вызов `migrate()` на старте |

Всё работает в одном asyncio-процессе → одно общее соединение, отдельного сервера БД не требуется.

## Схема БД

```sql
CREATE TABLE users (
    user_id              TEXT PRIMARY KEY,          -- Telegram id (строкой, как сейчас)
    rate                 REAL NOT NULL DEFAULT 0,
    clickup_api_token    TEXT,                      -- ЗАШИФРОВАН (Fernet), nullable
    clickup_workspace_id TEXT,
    clickup_team_id      TEXT,
    clickup_user_id      TEXT,
    clickup_username     TEXT
);

CREATE TABLE work_sessions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      TEXT NOT NULL REFERENCES users(user_id),
    date         TEXT NOT NULL,                     -- "YYYY-MM-DD"
    hours        INTEGER NOT NULL DEFAULT 0,
    minutes      INTEGER NOT NULL DEFAULT 0,
    earnings     REAL NOT NULL DEFAULT 0,
    timestamp    TEXT,                              -- ISO
    source       TEXT NOT NULL DEFAULT 'clickup',
    clickup_id   TEXT,
    task_name    TEXT,
    project_name TEXT,
    description  TEXT
);
CREATE INDEX idx_sessions_user_date ON work_sessions(user_id, date);

CREATE TABLE synced_entries (
    user_id  TEXT NOT NULL REFERENCES users(user_id),
    entry_id TEXT NOT NULL,
    PRIMARY KEY (user_id, entry_id)                 -- дедуп на уровне БД
);
```

Ключевые решения по схеме:

- **`total_hours`/`total_earnings` не хранятся** — считаются через `SUM()` в запросах. Убирает дублирование и рассинхрон.
- **Дублирующийся `date` внутри сессии убираем** — источник истины только колонка `date` (внешний ключ даты из JSON).
- **`synced_entries` оставляем отдельной таблицей** (не выводим из сессий) — прямой 1:1 маппинг текущих данных, поведение синка не меняется. `PRIMARY KEY(user_id, entry_id)` + `INSERT OR IGNORE` делает конкурентные синки безопасными.

## API `DataManager` (репозиторий)

**Чтение:**

```python
get_rate(user_id) -> float
get_clickup_settings(user_id) -> dict            # token уже расшифрован
get_user_clickup_client(user_id) -> ClickUpClient | None
get_daily_totals(user_id, start, end) -> dict     # {date_str: {"total_hours", "total_earnings"}}
get_sessions(user_id, start, end) -> list[dict]   # сырые сессии для группировки по задачам
is_entry_synced(user_id, entry_id) -> bool
```

**Запись (каждый — одна атомарная транзакция):**

```python
ensure_user(user_id)                              # INSERT OR IGNORE, дефолтная строка
set_rate(user_id, rate)
set_clickup_settings(user_id, **fields)           # шифрует token внутри
clear_clickup_settings(user_id)
add_session(user_id, date, session) -> None       # INSERT одной сессии
try_mark_synced(user_id, entry_id) -> bool        # INSERT OR IGNORE, True если новая
```

**Отчёты** (`generate_week_report`, `generate_month_report`, `generate_year_report`, `generate_week_details_report`, `generate_month_weeks_report`, `generate_prev_month_weeks_report`, вебапп-разбивки `get_days_breakdown`/`get_weeks_breakdown`/`get_months_breakdown`, `get_tasks_summary`/`group_sessions_by_task`) — вся логика с датами/неделями **остаётся как есть**. Меняется только источник данных: вместо `user_data["work_sessions"][date_str]` вызывают `get_daily_totals(...)` (для агрегатов по дням) или `get_sessions(...)` (для группировки по задачам). Это минимизирует правки в выверенной date-математике.

## Миграция и верификация (`migrate_to_sqlite.py`)

```python
def migrate(json_path="salary_data.json", db_path="salary.db") -> bool:
    if db_exists(db_path): return False           # идемпотентно, повторно не мигрирует
    data = load_json_robust(json_path)            # если JSON нет — тоже выходим (return False)
    create_schema("salary.db.tmp")                # схема во ВРЕМЕННЫЙ файл
    for user_id, u in data.items():
        insert_user(u)                            # token шифруется здесь
        for date, day in u["work_sessions"].items():
            for s in day["sessions"]:
                insert_session(user_id, date, s)  # внешний date — источник истины
        for eid in u.get("clickup_synced_entries", []):
            insert_synced(user_id, eid)
    verify(data, db)                              # при расхождении → raise, .tmp удаляем
    os.replace("salary.db.tmp", db_path)          # атомарно вводим БД
    os.replace(json_path, f"{json_path}.migrated-{ts}")  # архивируем JSON
    return True
```

**Верификация** (до коммита `.tmp`): для каждого пользователя сверяем данные в БД против JSON:

- сумма `earnings` по всем сессиям (точность `1e-6`);
- сумма часов по всем сессиям;
- число сессий;
- размер `synced_entries`.

Любое расхождение → исключение, `.tmp` удаляется, оригинальный JSON остаётся нетронутым. Исправляем и перезапускаем.

**Замечание по данным:** в текущем JSON часть сессий содержит внутреннее поле `date`, часть — нет. Миграция берёт авторитетным внешний ключ-дату (`work_sessions[date]`), внутренний дубликат игнорируется.

**Вызов на старте** — в `api.py` (lifespan) до инициализации `DataManager`:

```python
migrate()            # если salary.db нет, а json есть — мигрирует; иначе no-op
data_manager = DataManager()
```

Ту же `migrate()` можно запустить вручную: `python migrate_to_sqlite.py`.

**Откат:** JSON сохранён как `.migrated-<ts>`. Чтобы откатиться — удалить `salary.db` и переименовать архив обратно.

## Шифрование токенов (`crypto.py`)

- Fernet из `cryptography`. Ключ — `ENCRYPTION_KEY` из `.env`.
- `encrypt(plaintext) -> str`, `decrypt(token) -> str`. Токен в БД лежит только зашифрованным; расшифровка — в момент создания `ClickUpClient`.
- Генерация ключа: `python crypto.py genkey` печатает строку для вставки в `.env`.
- Если `ENCRYPTION_KEY` не задан — `DataManager`/`migrate` падают на старте с понятным сообщением и инструкцией сгенерировать ключ (явная ошибка лучше тихой записи токенов не туда).
- `.env.example` и `requirements.txt` дополняются (`cryptography`, `ENCRYPTION_KEY=`).

## Конкурентность — как уходят гонки

1. **Атомарные синхронные методы.** Гонка была из-за `await` между чтением и записью. Методы записи (`add_session`, `set_rate`, `set_clickup_settings`, ...) — синхронные, без `await` внутри: другая корутина не вклинивается в середину read-modify-write.
2. **Дедуп на уровне БД.** В `sync_clickup_entries` (async, с `await` к ClickUp между записями) два параллельных синка защищены `try_mark_synced()` → `INSERT OR IGNORE` в `synced_entries`. Сессия создаётся только если запись была новой (`rowcount == 1`). WAL позволяет читать во время записи.

Отрицательные длительности (`duration_ms < 0`, бегущие таймеры) по-прежнему пропускаются до дедупа и не помечаются — поведение сохранено.

## Правки в вызовах

~30 мест в `main.py`/`api.py`, механически:

- `get_user_data(id)["rate"]` → `get_rate(id)`
- `user_data["rate"] = x; save_data()` → `set_rate(id, x)`
- запись clickup-настроек → `set_clickup_settings(...)`
- отчёты инкапсулированы в `DataManager`, внешние вызовы не меняются.

Точный список всех call-site'ов составляется при написании плана реализации.

## Тестирование (pytest, каталог `tests/` уже есть)

- **Миграция:** фикстура-JSON → `migrate()` → проверка числа строк, сходимости totals, срабатывания верификации на намеренно битых данных.
- **Репозиторий:** `add_session` даёт верные агрегаты; `set_rate`; дедуп через `try_mark_synced` (эмуляция двойного синка); отчёты совпадают с ожидаемыми.
- **Шифрование:** round-trip; в колонке БД лежит НЕ плейнтекст, но `decrypt` возвращает исходный токен.

## Затрагиваемые файлы

Новые: `db.py`, `crypto.py`, `migrate_to_sqlite.py`.
Переписываем: `data_manager.py`.
Правим: `main.py`, `api.py`, `requirements.txt`, `.env.example`, `.gitignore` (убедиться, что `salary.db`, `salary_data.json*`, `.env` игнорируются).
