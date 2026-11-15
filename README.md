# 🎟️ albion-tickets

**Albion away and cup ticket sales, in your phone's calendar.**

Away tickets are released in stages by loyalty points over one week, and it's
easy to miss your morning. This reads the club's public ticket news and puts
**your** sale day in a calendar, with alerts the evening before and that
morning. It never logs in, never touches the ticket site and never buys.

## Setup

1. In Calendar.app, create an **Albion tickets** calendar under iCloud.
2. `uv sync`, then `uv run albion points <your points>`.
3. `uv run albion check --dry-run`, then `uv run albion check`. Allow **full
   calendar access** when macOS asks. Only the Albion tickets calendar is
   ever changed.
4. `launchd/install.sh` checks every two hours, 07:00–22:00. If a scheduled
   run asks for calendar access too, allow it.

Each match appears with its ground pinned on a map.

## Commands

| Command | What it does |
|---|---|
| `albion check [--dry-run] [-v]` | Read the news and update the calendar |
| `albion points <n>` | Set your points total |
| `albion upcoming` | Tracked matches and your sale day for each |
| `albion history [--season 2025-26] [--all] [-v]` | A table per season |
| `albion dismiss <key>` | Clear a "check this" reminder |
| `albion add <url>` | Track an article older than the news listing shows |
| `albion import <pdf>… [--dry-run]` | Read ticket pages you saved as PDFs (see below) |
| `albion got <match> [--undo]` | You already have tickets: no more sale reminders for it |
| `albion export <folder>` | Copy your history somewhere safe |

### Saved ticket pages

The ticket site lists sale dates weeks before the club's news, but the tool
never visits it. Save its Away Games or Home Games page as a PDF in your own
browser and run `albion import` on it. Away games and home cup ties are kept;
the club's news takes over each match once it covers it.

Your points and history stay in `data/` on your Mac, with a daily copy in
`data/backups/`.

MIT licence.
