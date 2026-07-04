import asyncio
import hashlib
import hmac
import json
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import Optional
from urllib.parse import parse_qsl, unquote

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from data_manager import DataManager

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
WEBAPP_URL = os.getenv("WEBAPP_URL", "")
API_PORT = int(os.getenv("API_PORT", "8000"))
DEV_USER_ID = os.getenv("DEV_USER_ID", "")  # Set this to your Telegram user ID for browser testing
INIT_DATA_MAX_AGE_SECONDS = 24 * 60 * 60

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

data_manager = DataManager()


# ---------------------------------------------------------------------------
# Telegram initData validation
# ---------------------------------------------------------------------------

def validate_init_data(init_data: str, bot_token: str) -> Optional[dict]:
    """
    Validate Telegram WebApp initData using HMAC-SHA256.
    Returns the parsed user dict on success, None on failure.
    """
    try:
        parsed = dict(parse_qsl(init_data, strict_parsing=True))
    except Exception:
        return None

    received_hash = parsed.pop("hash", None)
    if not received_hash:
        return None

    data_check_string = "\n".join(
        f"{k}={v}" for k, v in sorted(parsed.items())
    )

    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    expected_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()

    if not hmac.compare_digest(expected_hash, received_hash):
        return None

    # Reject stale initData (older than 24h) to prevent replay of leaked payloads
    try:
        auth_date = int(parsed.get("auth_date", 0))
    except (TypeError, ValueError):
        return None
    if auth_date <= 0 or datetime.now().timestamp() - auth_date > INIT_DATA_MAX_AGE_SECONDS:
        return None

    user_str = parsed.get("user")
    if not user_str:
        return None

    try:
        return json.loads(unquote(user_str))
    except Exception:
        return None


async def get_current_user(x_init_data: str = Header("", alias="X-Init-Data")) -> str:
    """FastAPI dependency that validates initData and returns user_id as str."""
    # Dev bypass: set DEV_USER_ID in .env to skip Telegram auth in browser
    if DEV_USER_ID and not x_init_data:
        return DEV_USER_ID

    if not BOT_TOKEN:
        raise HTTPException(status_code=500, detail="BOT_TOKEN not configured")

    user = validate_init_data(x_init_data, BOT_TOKEN)
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid initData")

    return str(user["id"])


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class RateUpdate(BaseModel):
    rate: float


class ClickUpSetupRequest(BaseModel):
    api_token: str
    workspace_id: str


class SyncRequest(BaseModel):
    days: int = 1


class TaskStatusUpdate(BaseModel):
    status: str


# ---------------------------------------------------------------------------
# App lifespan: run bot + API in same process
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    bot_task = None
    try:
        if BOT_TOKEN:
            from main import SalaryBot
            salary_bot = SalaryBot(BOT_TOKEN)
            # Inject shared data_manager so bot and API share the same data
            salary_bot.data_manager = data_manager
            bot_task = asyncio.create_task(salary_bot.start_bot())
            logger.info("Bot polling started")
    except Exception as e:
        logger.error(f"Failed to start bot: {e}")

    yield

    if bot_task:
        bot_task.cancel()
        try:
            await bot_task
        except asyncio.CancelledError:
            pass


app = FastAPI(title="SalaryCounter API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

api = FastAPI()


@api.get("/user/profile")
async def get_user_profile(user_id: str = Depends(get_current_user)):
    user_data = data_manager.get_user_data(user_id)
    clickup = user_data.get("clickup_settings", {})
    return {
        "rate": user_data.get("rate", 0),
        "clickup_configured": bool(clickup.get("api_token") and clickup.get("workspace_id")),
        "clickup_username": clickup.get("username"),
        "clickup_user_id": clickup.get("user_id"),
    }


@api.get("/user/rate")
async def get_rate(user_id: str = Depends(get_current_user)):
    user_data = data_manager.get_user_data(user_id)
    return {"rate": user_data.get("rate", 0)}


@api.put("/user/rate")
async def update_rate(body: RateUpdate, user_id: str = Depends(get_current_user)):
    if body.rate <= 0:
        raise HTTPException(status_code=400, detail="Rate must be positive")
    user_data = data_manager.get_user_data(user_id)
    user_data["rate"] = body.rate
    data_manager.save_data()
    return {"rate": body.rate}


def _sum_sessions(user_data: dict, start_date: datetime, end_date: datetime) -> dict:
    """Суммирует часы и заработок по дневным сессиям в диапазоне [start_date, end_date] включительно."""
    start = start_date.date()
    end = end_date.date()
    total_hours = 0.0
    total_earnings = 0.0
    for date_str, session in user_data["work_sessions"].items():
        try:
            d = datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            continue
        if start <= d <= end:
            total_hours += session.get("total_hours", 0)
            total_earnings += session.get("total_earnings", 0)
    return {"total_hours": total_hours, "total_earnings": total_earnings}


def _daily_series(user_data: dict, start_date: datetime, end_date: datetime) -> list:
    """Разбивка по дням в диапазоне [start_date, end_date] включительно (без пропусков)."""
    out = []
    cur = start_date
    while cur.date() <= end_date.date():
        ds = cur.strftime("%Y-%m-%d")
        session = user_data["work_sessions"].get(ds, {})
        out.append({
            "date": ds,
            "total_hours": session.get("total_hours", 0),
            "total_earnings": session.get("total_earnings", 0),
        })
        cur += timedelta(days=1)
    return out


def _monthly_series(user_data: dict, year: int) -> list:
    """Разбивка по 12 месяцам указанного года."""
    totals = {m: {"total_hours": 0, "total_earnings": 0} for m in range(1, 13)}
    for date_str, session in user_data["work_sessions"].items():
        try:
            d = datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            continue
        if d.year != year:
            continue
        totals[d.month]["total_hours"] += session.get("total_hours", 0)
        totals[d.month]["total_earnings"] += session.get("total_earnings", 0)
    return [
        {"month": f"{year}-{m:02d}", **totals[m]} for m in range(1, 13)
    ]


def _previous(user_data: dict, start_date: datetime, end_date: datetime, label: str, series: Optional[list] = None) -> dict:
    """Итоги предыдущего эквивалентного периода для сравнения (+ опциональная разбивка)."""
    totals = _sum_sessions(user_data, start_date, end_date)
    result = {**totals, "label": label}
    if series is not None:
        result["series"] = series
    return result


@api.get("/earnings/today")
async def earnings_today(user_id: str = Depends(get_current_user)):
    user_data = data_manager.get_user_data(user_id)
    now = datetime.now()
    today = now.strftime("%Y-%m-%d")
    session = user_data["work_sessions"].get(today, {})
    prev_day = now - timedelta(days=1)
    return {
        "date": today,
        "total_hours": session.get("total_hours", 0),
        "total_earnings": session.get("total_earnings", 0),
        "sessions": session.get("sessions", []),
        "previous": _previous(user_data, prev_day, prev_day, "вчера"),
    }


@api.get("/earnings/yesterday")
async def earnings_yesterday(user_id: str = Depends(get_current_user)):
    user_data = data_manager.get_user_data(user_id)
    yesterday_dt = datetime.now() - timedelta(days=1)
    yesterday = yesterday_dt.strftime("%Y-%m-%d")
    session = user_data["work_sessions"].get(yesterday, {})
    day_before = yesterday_dt - timedelta(days=1)
    return {
        "date": yesterday,
        "total_hours": session.get("total_hours", 0),
        "total_earnings": session.get("total_earnings", 0),
        "sessions": session.get("sessions", []),
        "previous": _previous(user_data, day_before, day_before, "позавчера"),
    }


@api.get("/earnings/week")
async def earnings_week(user_id: str = Depends(get_current_user)):
    user_data = data_manager.get_user_data(user_id)
    today = datetime.now()
    monday = today - timedelta(days=today.weekday())
    days = []
    current = monday
    while current <= today:
        date_str = current.strftime("%Y-%m-%d")
        session = user_data["work_sessions"].get(date_str, {})
        days.append({
            "date": date_str,
            "total_hours": session.get("total_hours", 0),
            "total_earnings": session.get("total_earnings", 0),
            "sessions": session.get("sessions", []),
        })
        current += timedelta(days=1)
    total_hours = sum(d["total_hours"] for d in days)
    total_earnings = sum(d["total_earnings"] for d in days)
    return {
        "period_start": monday.strftime("%Y-%m-%d"),
        "period_end": today.strftime("%Y-%m-%d"),
        "days": days,
        "total_hours": total_hours,
        "total_earnings": total_earnings,
        "previous": _previous(
            user_data,
            monday - timedelta(days=7),
            monday - timedelta(days=1),
            "прошлая неделя",
            series=_daily_series(user_data, monday - timedelta(days=7), monday - timedelta(days=1)),
        ),
    }


@api.get("/earnings/week-details")
async def earnings_week_details(user_id: str = Depends(get_current_user)):
    user_data = data_manager.get_user_data(user_id)
    report = data_manager.generate_week_details_report(user_data)
    return {"report": report}


@api.get("/earnings/month")
async def earnings_month(user_id: str = Depends(get_current_user)):
    user_data = data_manager.get_user_data(user_id)
    today = datetime.now()
    first = today.replace(day=1)
    days = []
    current = first
    while current <= today:
        date_str = current.strftime("%Y-%m-%d")
        session = user_data["work_sessions"].get(date_str, {})
        days.append({
            "date": date_str,
            "total_hours": session.get("total_hours", 0),
            "total_earnings": session.get("total_earnings", 0),
        })
        current += timedelta(days=1)
    total_hours = sum(d["total_hours"] for d in days)
    total_earnings = sum(d["total_earnings"] for d in days)
    prev_month_last = first - timedelta(days=1)
    prev_month_first = prev_month_last.replace(day=1)
    return {
        "period_start": first.strftime("%Y-%m-%d"),
        "period_end": today.strftime("%Y-%m-%d"),
        "days": days,
        "total_hours": total_hours,
        "total_earnings": total_earnings,
        "previous": _previous(
            user_data,
            prev_month_first,
            prev_month_last,
            "прошлый месяц",
            series=_daily_series(user_data, prev_month_first, prev_month_last),
        ),
    }


@api.get("/earnings/month-weeks")
async def earnings_month_weeks(user_id: str = Depends(get_current_user)):
    user_data = data_manager.get_user_data(user_id)
    report = data_manager.generate_month_weeks_report(user_data)
    return {"report": report}


@api.get("/earnings/prev-month-weeks")
async def earnings_prev_month_weeks(user_id: str = Depends(get_current_user)):
    user_data = data_manager.get_user_data(user_id)
    report = data_manager.generate_prev_month_weeks_report(user_data)
    return {"report": report}


@api.get("/earnings/year")
async def earnings_year(user_id: str = Depends(get_current_user)):
    user_data = data_manager.get_user_data(user_id)
    now = datetime.now()
    current_year = now.year
    months = {}
    for date_str, session in user_data["work_sessions"].items():
        try:
            d = datetime.strptime(date_str, "%Y-%m-%d")
            if d.year != current_year:
                continue
            key = d.strftime("%Y-%m")
            if key not in months:
                months[key] = {"month": key, "total_hours": 0, "total_earnings": 0}
            months[key]["total_hours"] += session.get("total_hours", 0)
            months[key]["total_earnings"] += session.get("total_earnings", 0)
        except ValueError:
            continue
    sorted_months = sorted(months.values(), key=lambda x: x["month"])
    total_hours = sum(m["total_hours"] for m in sorted_months)
    total_earnings = sum(m["total_earnings"] for m in sorted_months)
    prev_start = datetime(current_year - 1, 1, 1)
    prev_end = datetime(current_year - 1, 12, 31, 23, 59, 59)
    return {
        "year": current_year,
        "months": sorted_months,
        "total_hours": total_hours,
        "total_earnings": total_earnings,
        "previous": _previous(
            user_data,
            prev_start,
            prev_end,
            "прошлый год",
            series=_monthly_series(user_data, current_year - 1),
        ),
    }


@api.get("/clickup/status")
async def clickup_status(user_id: str = Depends(get_current_user)):
    client = data_manager.get_user_clickup_client(user_id)
    user_data = data_manager.get_user_data(user_id)
    clickup_settings = user_data.get("clickup_settings", {})

    if not client:
        return {
            "configured": False,
            "username": None,
            "workspace_id": None,
            "active_timer": None,
            "synced_count": 0,
        }

    try:
        team_id = await client.get_team_id()
        current_timer = await client.get_current_timer() if team_id else None
    except Exception:
        team_id = None
        current_timer = None

    active_timer = None
    if current_timer:
        task_info = current_timer.get("task", {})
        start_ms = int(current_timer.get("start", 0))
        active_timer = {
            "task_id": task_info.get("id"),
            "task_name": task_info.get("name", "Неизвестная задача"),
            "start": start_ms,
        }

    return {
        # Connected == credentials are stored (client exists). Do NOT gate this
        # on the live get_team_id() call, or a transient ClickUp API failure
        # would hide the connected profile behind the setup form.
        "configured": True,
        "username": clickup_settings.get("username"),
        "workspace_id": clickup_settings.get("workspace_id"),
        "active_timer": active_timer,
        "synced_count": len(user_data.get("clickup_synced_entries", set())),
        "user_id_set": bool(clickup_settings.get("user_id")),
    }


@api.post("/clickup/setup")
async def clickup_setup(body: ClickUpSetupRequest, user_id: str = Depends(get_current_user)):
    result = await data_manager.validate_clickup_credentials(body.api_token, body.workspace_id)
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["error"])

    user_data = data_manager.get_user_data(user_id)
    user_data["clickup_settings"]["api_token"] = body.api_token
    user_data["clickup_settings"]["workspace_id"] = body.workspace_id
    user_data["clickup_settings"]["team_id"] = result["team_id"]
    user_data["clickup_settings"]["user_id"] = result["user_id"]
    user_data["clickup_settings"]["username"] = result["username"]
    data_manager.save_data()

    return {
        "success": True,
        "username": result["username"],
        "team_id": result["team_id"],
    }


@api.delete("/clickup/setup")
async def clickup_reset(user_id: str = Depends(get_current_user)):
    user_data = data_manager.get_user_data(user_id)
    user_data["clickup_settings"] = {
        "api_token": None,
        "workspace_id": None,
        "team_id": None,
        "user_id": None,
        "username": None,
    }
    data_manager.save_data()
    return {"success": True}


@api.post("/clickup/sync")
async def clickup_sync(body: SyncRequest, user_id: str = Depends(get_current_user)):
    user_data = data_manager.get_user_data(user_id)
    if user_data.get("rate", 0) <= 0:
        raise HTTPException(status_code=400, detail="Rate not set")

    end_date = datetime.now()
    start_date = end_date - timedelta(days=max(1, body.days) - 1)
    start_date = start_date.replace(hour=0, minute=0, second=0, microsecond=0)

    result = await data_manager.sync_clickup_entries(user_id, start_date, end_date)
    if not result["success"]:
        raise HTTPException(status_code=500, detail=result["error"])
    return result


@api.get("/clickup/spaces")
async def get_spaces(user_id: str = Depends(get_current_user)):
    client = data_manager.get_user_clickup_client(user_id)
    if not client:
        raise HTTPException(status_code=400, detail="ClickUp not configured")
    spaces = await client.get_spaces()
    return {"spaces": spaces}


@api.get("/clickup/spaces/{space_id}/folders")
async def get_folders(space_id: str, user_id: str = Depends(get_current_user)):
    client = data_manager.get_user_clickup_client(user_id)
    if not client:
        raise HTTPException(status_code=400, detail="ClickUp not configured")
    folders = await client.get_folders(space_id)
    root_lists = await client.get_lists(space_id)
    return {"folders": folders, "root_lists": root_lists}


@api.get("/clickup/folders/{folder_id}/lists")
async def get_folder_lists(folder_id: str, space_id: str, user_id: str = Depends(get_current_user)):
    client = data_manager.get_user_clickup_client(user_id)
    if not client:
        raise HTTPException(status_code=400, detail="ClickUp not configured")
    lists = await client.get_lists(space_id, folder_id)
    return {"lists": lists}


@api.get("/clickup/lists/{list_id}/tasks")
async def get_list_tasks(list_id: str, status: str = "all", user_id: str = Depends(get_current_user)):
    client = data_manager.get_user_clickup_client(user_id)
    if not client:
        raise HTTPException(status_code=400, detail="ClickUp not configured")

    user_data = data_manager.get_user_data(user_id)
    assignee_id = user_data.get("clickup_settings", {}).get("user_id")

    tasks = await client.get_tasks(list_id, assignee_id)

    if status != "all":
        tasks = [t for t in tasks if t.get("status", {}).get("status", "").lower() == status.lower()]

    return {"tasks": tasks, "total": len(tasks)}


@api.get("/clickup/lists/{list_id}/statuses")
async def get_list_statuses(list_id: str, user_id: str = Depends(get_current_user)):
    client = data_manager.get_user_clickup_client(user_id)
    if not client:
        raise HTTPException(status_code=400, detail="ClickUp not configured")
    statuses = await client.get_list_statuses(list_id)
    return {"statuses": statuses}


@api.get("/clickup/tasks/{task_id}")
async def get_task(task_id: str, user_id: str = Depends(get_current_user)):
    client = data_manager.get_user_clickup_client(user_id)
    if not client:
        raise HTTPException(status_code=400, detail="ClickUp not configured")
    task = await client.get_task_details(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@api.put("/clickup/tasks/{task_id}/status")
async def update_task_status(task_id: str, body: TaskStatusUpdate, user_id: str = Depends(get_current_user)):
    client = data_manager.get_user_clickup_client(user_id)
    if not client:
        raise HTTPException(status_code=400, detail="ClickUp not configured")
    success = await client.update_task_status(task_id, body.status)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to update task status")
    return {"success": True}


@api.post("/clickup/tasks/{task_id}/timer/start")
async def start_task_timer(task_id: str, user_id: str = Depends(get_current_user)):
    client = data_manager.get_user_clickup_client(user_id)
    if not client:
        raise HTTPException(status_code=400, detail="ClickUp not configured")
    success = await client.start_timer(task_id)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to start timer")
    return {"success": True}


@api.post("/clickup/timer/stop")
async def stop_timer(user_id: str = Depends(get_current_user)):
    client = data_manager.get_user_clickup_client(user_id)
    if not client:
        raise HTTPException(status_code=400, detail="ClickUp not configured")
    success = await client.stop_timer()
    if not success:
        raise HTTPException(status_code=500, detail="Failed to stop timer")
    return {"success": True}


@api.get("/analytics/tasks")
async def analytics_tasks(
    period: str = "week",
    start: Optional[str] = None,
    end: Optional[str] = None,
    user_id: str = Depends(get_current_user),
):
    # A custom range (start/end) takes precedence over the named preset.
    if start and end:
        try:
            start_date = datetime.strptime(start, "%Y-%m-%d").replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            end_date = datetime.strptime(end, "%Y-%m-%d").replace(
                hour=23, minute=59, second=59, microsecond=0
            )
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid start/end date (expected YYYY-MM-DD)")
        if end_date < start_date:
            start_date, end_date = (
                end_date.replace(hour=0, minute=0, second=0, microsecond=0),
                start_date.replace(hour=23, minute=59, second=59, microsecond=0),
            )
        period = "custom"
        period_name = f"{start_date.strftime('%d.%m.%Y')} — {end_date.strftime('%d.%m.%Y')}"
    else:
        # The webapp sends "7"/"30"; map them to the keys get_tasks_summary_by_period understands.
        period_key = {"7": "7days", "30": "30days"}.get(period, period)
        start_date, end_date, period_name = data_manager.get_tasks_summary_by_period(period_key)

    summary = data_manager.get_tasks_summary(user_id, start_date, end_date)

    # Emit tasks as a list, sorted by earnings, with the field names the webapp expects.
    tasks_out = [
        {
            "task_name": task["task_name"],
            "hours": task["total_hours"],
            "earnings": task["total_earnings"],
            "sessions_count": task["sessions_count"],
            "first_session": task["first_session"],
            "last_session": task["last_session"],
            "source_type": task["source_type"],
        }
        for task in sorted(
            summary["tasks"].values(),
            key=lambda t: t["total_earnings"],
            reverse=True,
        )
    ]

    # Breakdown granularity (days / weeks / months) chosen by the period length.
    breakdown = data_manager.get_period_breakdown(user_id, start_date, end_date)

    return {
        "period": period,
        "period_name": period_name,
        "period_start": start_date.isoformat(),
        "period_end": end_date.isoformat(),
        "tasks": tasks_out,
        "breakdown": breakdown,
        "total_hours": summary["total_hours"],
        "total_earnings": summary["total_earnings"],
        "total_tasks": summary["total_tasks"],
        "total_sessions": summary["total_sessions"],
    }


# Mount the API under /api/v1
app.mount("/api/v1", api)

# Serve the built Nuxt app (SPA fallback)
WEBAPP_BUILD = os.path.join(os.path.dirname(__file__), "webapp", ".output", "public")

if os.path.isdir(WEBAPP_BUILD):
    app.mount("/", StaticFiles(directory=WEBAPP_BUILD, html=True), name="webapp")
else:
    @app.get("/")
    async def root():
        return {"message": "SalaryCounter API", "docs": "/docs"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api:app", host="0.0.0.0", port=API_PORT, reload=False)
