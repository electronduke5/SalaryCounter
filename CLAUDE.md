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
- **Command Handlers**: Telegram commands for user interactions (`/start`, `/setrate`, `/addtime`, etc.)

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

- `/start` - Welcome message and current rate display
- `/setrate` - Set hourly rate (enters FSM state)
- `/addtime` - Add work time in "hours minutes" format (enters FSM state)  
- `/today` - Show today's earnings
- `/yesterday` - Show yesterday's earnings
- `/week` - Show last 7 days summary
- `/month` - Show last 30 days summary
- `/help` - Command reference

The bot uses Russian language for user interactions and expects time input in "HOURS MINUTES" format (e.g., "8 30" for 8 hours 30 minutes).