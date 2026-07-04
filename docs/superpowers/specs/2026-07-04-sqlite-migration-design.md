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
    duration_ms  INTEGER NOT NULL DEFAULT 0,        -- длительность в мс (родная единица ClickUp)
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
- **Храним `duration_ms`, а не усечённые `hours`/`minutes`.** Текущий JSON теряет секунды: сессия пишет `int((duration_hours % 1) * 60)`, а дневной `total_hours` копит точный float. На реальных данных `SUM(hours+minutes/60)` расходится с дневными тоталами на **8–12 часов** у активных пользователей (деньги при этом сходятся — `earnings` в сессии точный). Точный `total_hours` из ClickUp — более правильная величина, её и сохраняем. Для новых синков `duration_ms` берётся напрямую из `duration` ClickUp (без потерь); отображаемые часы/минуты вычисляются из `duration_ms` на чтении. См. бэкфилл в разделе миграции.
- **Дублирующийся `date` внутри сессии убираем** — источник истины только колонка `date` (внешний ключ даты из JSON).
- **`synced_entries` оставляем отдельной таблицей** (не выводим из сессий) — прямой 1:1 маппинг текущих данных, поведение синка не меняется. `PRIMARY KEY(user_id, entry_id)` + `INSERT OR IGNORE` делает конкурентные синки безопасными.

## API `DataManager` (репозиторий)

**Чтение:**

```python
get_rate(user_id) -> float
get_clickup_settings(user_id) -> dict            # token уже расшифрован
get_user_clickup_client(user_id) -> ClickUpClient | None
get_work_sessions(user_id) -> dict               # легаси-форма {date: {total_hours, total_earnings, sessions:[...]}}
is_entry_synced(user_id, entry_id) -> bool
```

`get_work_sessions` реконструирует привычную вложенную структуру из SQL: `total_hours` считается точно как `SUM(duration_ms)/3_600_000`, каждая сессия несёт `duration_ms` (+ производные `hours`/`minutes` и `duration_hours` для отображения и группировки по задачам). Это единый метод чтения — он покрывает и агрегаты отчётов, и списки сессий, минимизируя правки в date-математике (в отчётах меняется только источник: `user_data["work_sessions"]` → `get_work_sessions(user_id)`).

**Запись:**

```python
ensure_user(user_id)                              # INSERT OR IGNORE, дефолтная строка
set_rate(user_id, rate)                           # автокоммит
set_clickup_settings(user_id, **fields)           # шифрует token внутри
clear_clickup_settings(user_id)
add_synced_session(user_id, entry_id, date, session) -> bool
```

**`add_synced_session` — одна транзакция вместо двух методов.** Пометка синка и вставка сессии должны быть атомарны: иначе краш между ними оставит запись помеченной синхронизированной, но без сессии — тихая потеря, которую повторный синк уже не починит. Метод в одной транзакции (`BEGIN IMMEDIATE` → `INSERT OR IGNORE synced_entries` → если запись новая, `INSERT work_sessions` → `COMMIT`) возвращает `True`, если сессия была добавлена. Дедуп между процессами держит `PRIMARY KEY(user_id, entry_id)`.

**Отчёты** (`generate_*_report`, вебапп-разбивки `get_days_breakdown`/`get_weeks_breakdown`/`get_months_breakdown`, `get_tasks_summary`/`group_sessions_by_task`) — вся логика с датами/неделями **остаётся как есть**. Меняется только источник данных: `user_data["work_sessions"]` → `get_work_sessions(user_id)`. `group_sessions_by_task` считает часы из `duration_ms` (а не `hours + minutes/60`), чтобы суммы по задачам совпадали с дневными тоталами.

## Миграция и верификация (`migrate_to_sqlite.py`)

```python
def migrate(json_path="salary_data.json", db_path="salary.db") -> bool:
    if db_exists(db_path): return False           # идемпотентно, повторно не мигрирует
    data = load_json_robust(json_path)            # если JSON нет — тоже выходим (return False)
    tmp = f"{db_path}.{os.getpid()}.tmp"          # уникальный tmp на процесс (race-tolerant)
    create_schema(tmp)
    for user_id, u in data.items():
        insert_user(u)                            # token шифруется здесь
        for date, day in u["work_sessions"].items():
            sessions_ms = [session_to_ms(s) for s in day["sessions"]]
            backfill_last(sessions_ms, day.get("total_hours"))  # см. бэкфилл ниже
            for s, ms in zip(day["sessions"], sessions_ms):
                insert_session(user_id, date, ms, s)  # внешний date — источник истины
        for eid in u.get("clickup_synced_entries", []):
            insert_synced(user_id, eid)
    verify(data, db)                              # при расхождении → raise, tmp удаляем
    if db_exists(db_path):                        # кто-то мигрировал параллельно
        remove(tmp); return False
    os.replace(tmp, db_path)                      # атомарно вводим БД
    try:
        os.replace(json_path, f"{json_path}.migrated-{ts}")  # архивируем JSON
    except FileNotFoundError:
        pass                                      # другой процесс уже переименовал — ок
    return True
```

**Бэкфилл потери секунд.** Сессии в JSON хранят усечённые `hours`/`minutes` — их сумма меньше точного дневного `total_hours` на 8–12 часов у активных пользователей. Восстанавливаем правильный (точный) дневной тотал: для каждого дня `session_ms = (hours*60 + minutes)*60_000`; `target_ms = round(total_hours * 3_600_000)`; разницу `target_ms − sum(session_ms)` добавляем к последней сессии дня. Тогда `SUM(duration_ms)/3_600_000` в БД равен исходному `total_hours`, у пользователей часы не «худеют», и верификация против JSON-тоталов сходится. Если у дня нет `total_hours` — цель равна сумме сессий (дельта 0).

**Верификация** (до коммита tmp): для каждого пользователя сверяем БД против JSON:

- сумма `earnings` по всем сессиям (точность `1e-6`);
- `SUM(duration_ms)/3_600_000` против суммы дневных `total_hours` (точность `1e-3` ч — с запасом на округление до мс);
- число сессий;
- размер `synced_entries`.

Любое расхождение → исключение, tmp удаляется, оригинальный JSON остаётся нетронутым.

**Замечание по данным:** часть сессий в JSON содержит внутреннее поле `date`, часть — нет. Миграция берёт авторитетным внешний ключ-дату (`work_sessions[date]`), внутренний дубликат игнорируется.

**Вызов на старте — в ОБЕИХ точках входа.** `deploy.sh`/systemd запускают только `python main.py`; api.py поднимается отдельным процессом (или иначе). Поэтому `migrate()` вызывается и в `SalaryBot.__init__` (перед `DataManager()`), и в `api.py` до инициализации `data_manager`. Она идемпотентна и race-tolerant (уникальный tmp по pid, повторная проверка наличия БД перед `os.replace`, устойчивость к уже-переименованному JSON), так что одновременный старт двух процессов безопасен.

**Рекомендация деплоя:** запускать `python migrate_to_sqlite.py` явным шагом ДО старта сервисов — тогда авто-миграция на старте становится подстраховкой, а не основным путём.

**Откат:** JSON сохранён как `.migrated-<ts>`. Чтобы откатиться — удалить `salary.db` и переименовать архив обратно.

## Шифрование токенов (`crypto.py`)

- Fernet из `cryptography`. Ключ — `ENCRYPTION_KEY` из `.env`.
- `encrypt(plaintext) -> str`, `decrypt(token) -> str`. Токен в БД лежит только зашифрованным; расшифровка — в момент создания `ClickUpClient`.
- Генерация ключа: `python crypto.py genkey` печатает строку для вставки в `.env`.
- Если `ENCRYPTION_KEY` не задан — `DataManager`/`migrate` падают на старте с понятным сообщением и инструкцией сгенерировать ключ (явная ошибка лучше тихой записи токенов не туда).
- `.env.example` и `requirements.txt` дополняются (`cryptography`, `ENCRYPTION_KEY=`).

**Известное ограничение:** потеря `ENCRYPTION_KEY` делает сохранённые токены невосстановимыми — пользователям придётся заново пройти `/clickup_setup`. Ключ хранить так же бережно, как `BOT_TOKEN`.

## Конкурентность — как уходят гонки

Топология: **одно соединение на процесс**. Возможны два процесса — бот (`python main.py`) и вебапп-API (`api.py`); общий `DataManager` существует только когда точка входа — api.py (инъекция в lifespan).

1. **Внутри процесса — атомарные синхронные методы.** Гонка была из-за `await` между чтением и записью. Методы записи (`add_synced_session`, `set_rate`, `set_clickup_settings`, ...) синхронны, без `await` внутри: другая корутина не вклинивается в середину read-modify-write. Это защищает только внутрипроцессное чередование.
2. **Между процессами — уровень БД.** Два параллельных синка (в т.ч. из разных процессов) защищены `PRIMARY KEY(user_id, entry_id)` + `INSERT OR IGNORE`: сессия создаётся только если пометка синка была новой (`rowcount == 1`), всё в одной транзакции `add_synced_session`. WAL + `busy_timeout=5000` переживают межпроцессную конкуренцию за запись; WAL позволяет читать во время записи.

Режим транзакций фиксируем явно: соединение в автокоммите (`isolation_level=None`), мульти-стейтментные записи оборачиваются в `BEGIN IMMEDIATE … COMMIT` (предсказуемая блокировка вместо неочевидного дефолта `sqlite3`).

Отрицательные длительности (`duration_ms < 0`, бегущие таймеры) по-прежнему пропускаются до дедупа и не помечаются — поведение сохранено.

## Правки в вызовах

Механически, по всем call-site'ам `data_manager.*` в `main.py`/`api.py` (всего ~134 вызова, но правок меньше — отчёты инкапсулированы и вызываются без изменения сигнатур на стороне вызова):

- `get_user_data(id)["rate"]` → `get_rate(id)`
- `user_data["rate"] = x; save_data()` → `set_rate(id, x)`
- запись/чтение clickup-настроек → `set_clickup_settings(...)` / `get_clickup_settings(...)`
- `user_data["work_sessions"]` в отчётах/аналитике → `get_work_sessions(id)`
- подсчёт синков → `SELECT COUNT(*) FROM synced_entries`.

Точный список всех call-site'ов составляется при написании плана реализации.

## Тестирование (pytest, каталог `tests/` уже есть)

- **Миграция:** фикстура-JSON → `migrate()` → проверка числа строк, сходимости `earnings` и часов (включая бэкфилл потери секунд), срабатывания верификации на намеренно битых данных.
- **Репозиторий:** `add_synced_session` даёт верные агрегаты и дедупит (эмуляция двойного синка); `set_rate`; отчёты совпадают с ожидаемыми; часы по задачам считаются из `duration_ms`.
- **Шифрование:** round-trip; в колонке БД лежит НЕ плейнтекст, но `decrypt` возвращает исходный токен.

## Затрагиваемые файлы

Новые: `db.py`, `crypto.py`, `migrate_to_sqlite.py`.
Переписываем: `data_manager.py`.
Правим: `main.py`, `api.py`, `requirements.txt`, `.env.example`, `.gitignore` (убедиться, что `salary.db`, `salary_data.json*`, `.env` игнорируются).
