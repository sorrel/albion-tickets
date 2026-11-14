# 🎟️ albion-tickets

**Albion away and cup ticket sales, in your phone's calendar.**

Away tickets are released in stages by loyalty points over one week, and it's
easy to miss your morning. This reads the club's public ticket news and puts
**your** sale day in a calendar, with alerts the evening before and that
morning. It never logs in, never touches the ticket site and never buys.

## Setup

1. In Calendar.app, create an **Albion tickets** calendar under iCloud.
2. `uv sync` then `uv run albion points <your points>`
3. `uv run albion check --dry-run`, then `uv run albion check`
   (macOS asks once to let it control Calendar).
4. `launchd/install.sh` to check every two hours, 07:00–22:00.

## Commands

| Command | What it does |
|---|---|
| `albion check [--dry-run] [-v]` | Read the news and update the calendar |
| `albion points <n>` | Set your points total |
| `albion upcoming` | Tracked matches and your sale day for each |
| `albion history [--season 2025-26] [--all] [-v]` | A table per season |
| `albion dismiss <key>` | Clear a "check this" reminder |
| `albion add <url>` | Track an article older than the news listing shows |
| `albion export <folder>` | Copy your history somewhere safe |

Your points and history stay in `data/` on your Mac, with a daily copy in
`data/backups/`.

MIT licence.
