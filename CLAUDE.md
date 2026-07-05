# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a Telegram bot for salary calculation and time tracking built with Python using the aiogram library. The bot helps users track their work hours and calculate earnings based on their hourly rate.

## Running the Bot

To start the bot:
```bash
python main.py
```

The bot requires a `BOT_TOKEN` environment variable containing the Telegram bot token.

## Architecture

The application follows a single-file architecture with the main `SalaryBot` class that handles:

- **Data Management**: JSON-based persistence in `salary_data.json` with user-specific work sessions
- **State Management**: FSM (Finite State Machine) for handling multi-step interactions (rate setting, time input)
- **Command Handlers**: Telegram commands for user interactions (`/start`, `/setrate`, etc.)

### Key Components

- `SalaryBot`: Main bot class handling initialization, data persistence, and command routing
- `SalaryStates`: FSM states for handling user input flows
- Data structure: User data keyed by Telegram user ID, containing rate and work sessions organized by date

### Data Flow

1. User data is loaded from `salary_data.json` on startup
2. Each user has a rate (rubles/hour) and work sessions organized by date
3. Work sessions store total hours, earnings, and individual time entries
4. Data is persisted to JSON file after each update

### Available Commands

#### Basic Commands
- `/start` - Welcome message and current rate display
- `/setrate` - Set hourly rate (enters FSM state)
- `/today` - Show today's earnings
- `/yesterday` - Show yesterday's earnings
- `/week` - Show last 7 days summary
- `/month` - Show last 30 days summary
- `/goal [amount]` - Show/set monthly earnings goal (0 clears it); progress appears in `/month`, the daily digest, and the Mini App
- `/bonus` - Add a bonus payment via FSM (amount → date → comment); bonuses live in the `bonuses` table, are reported as a separate line ("по часам / премии / итого"), and count toward the monthly goal
- `/bonuses` - List this year's bonuses with inline delete buttons
- `/help` - Command reference

#### ClickUp Integration
- `/clickup_setup` - Step-by-step ClickUp integration setup
- `/clickup_token` - Set Personal API Token
- `/clickup_workspace` - Set Workspace ID
- `/syncclickup` - Sync today's time entries
- `/synclast [days]` - Sync last N days (default 7)
- `/clickupstatus` - Show integration status and active timers
- `/notifications` - Toggle background autosync and notifications (daily digest, weekly summary, long-timer alert), set digest time

#### Background Scheduler
`scheduler.py` runs inside the same process (started from the `api.py` lifespan, gated by `SCHEDULER_ENABLED`). It periodically autosyncs ClickUp entries for every user with a configured token and sends notifications according to per-user settings stored in `users` columns. Sent notifications are deduplicated via the `notification_log` table, so restarts never re-send a digest. Timing envs: `SCHEDULER_TICK_SECONDS`, `AUTOSYNC_INTERVAL_MINUTES`, `TIMER_CHECK_INTERVAL_MINUTES`, `APP_TZ`.

#### Task Management
- `/tasks` - Step-by-step task navigation: Projects → Status → Tasks with interactive controls
- `/active_task` - Show currently active task with running timer

#### Analytics
- `/tasksummary [period]` - Task summary (week/today/yesterday/month/N days)
- `/monthweeks` - Weekly breakdown for current month
- `/weekdetails` - Detailed daily breakdown for current week
- `/year` - Monthly breakdown for current year

### Task Management Features

#### Step-by-step Navigation Interface
The `/tasks` command provides a structured navigation flow following ClickUp hierarchy:

1. **Spaces** - Choose from available workspaces/teams
2. **Folders** - Select folder within the space (if any exist)
3. **Lists** - Choose specific project/list within folder or space
4. **Status Filter** - Select task status: All, Open, In Progress, Review, Done, Complete
5. **Task List** - View tasks assigned to you with interactive controls

#### Interactive Task Controls
Each task includes inline buttons:
- **📋 Инфо** - View detailed task information (name, description, assignee, due date, project)
- **⏱️ Старт** - Start ClickUp timer for the task
- **⏹️ Стоп** - Stop running timer
- **Status buttons** - Change task status in ClickUp (Open, In Progress, Review, Done, Complete)

#### Navigation Features
- **🔙 Назад** buttons for easy navigation between levels
- **Back to Spaces** - Return to workspace selection
- **Back to Folders** - Return to folder selection within space
- **Back to Lists** - Return to list selection within folder
- **Back to Status** - Return to status selection for current list
- Hierarchical navigation following ClickUp structure

#### Performance Optimizations
- **Minimal API Requests** - Only loads data when needed at each navigation level
- **User Filtering** - Shows only tasks assigned to current user (assignee filter)
- **On-demand Loading** - Spaces → Folders → Lists → Tasks loaded progressively
- **Efficient Caching** - User information cached during ClickUp setup

#### Supported ClickUp Statuses
- Open (📂)
- In Progress (🔄)
- Review (👀)
- Done (✅)
- Complete (🏁)

#### Timer Management
- Start/stop timers directly from Telegram
- View active task with running time
- Automatic synchronization with ClickUp time tracking
- Integration with existing salary calculation system

The bot uses Russian language for user interactions. All work time comes from ClickUp time tracking (manual time entry is not supported); time entries are read-only — corrections are made in ClickUp and re-synced.