# 🎟️ albion-tickets

**Reminders for Brighton & Hove Albion away and cup ticket sales, on your phone.**

Away tickets go on sale in stages by loyalty points, usually over one week:
the top points bracket on Tuesday, then Wednesday, Thursday, and everyone
else with a season ticket on Friday. Miss your morning and the match is often
gone. This tool reads the club's public ticket news and puts **your** sale day
into a calendar that syncs to your phone, with alerts the evening before and
on the morning.

## What it does

- 📰 Reads the club's ticket news on its main website every two hours
  (07:00–22:00). It never logs in, never touches the ticket site, and never
  buys anything.
- 🎯 Works out your stage from your points total, including a **predicted**
  Friday before the points brackets are announced.
- 📅 Adds events to a dedicated **Albion tickets** calendar:
  - your sale (alerts at 19:00 the night before, 08:30 and 08:55);
  - every away and home cup fixture (no alerts), moved when the kick-off moves;
  - a ⚠️ alert when a kick-off or sale date changes;
  - "ticket exchange open to you", only when a match sold out at a stage you
    qualify for;
  - "your points should have landed: update them" 10 days after each away
    match (the club credits loyalty points about 10 days after the game),
    added only once that day comes;
  - sales that were already over when first found are left out;
  - articles about home league games are read once, then ignored;
  - "check this ticket article" when it can't read something, so a sale is
    never silently missed.

## Setup

1. In Calendar.app, create a calendar called **Albion tickets** under your
   iCloud account, so it reaches your phone.
2. `uv sync`
3. `uv run albion points <your points>`
4. `uv run albion check --dry-run` and read what it would add.
5. `uv run albion check`. The first time, macOS asks to let it control
   Calendar.
6. `launchd/install.sh` to run it automatically.

## Commands

| Command | What it does |
|---|---|
| `albion check [--dry-run] [-v]` | Read the news and update the calendar. Prints a short summary; `-v` lists every change with its date. A status line shows progress in a terminal (`--progress`/`--quiet` to override) |
| `albion points <n>` | Set your loyalty points total |
| `albion upcoming` | Tracked matches and your sale day for each |
| `albion history [--season 2025-26 | --all] [-v]` | A table per season: kick-off, match, points it is worth, the Tue/Wed/Thu points thresholds, your sale day and the sell-out tier, then any kick-off changes. `-v` adds every sale stage per match |
| `albion dismiss <key>` | Clear a "check this" reminder |
| `albion add <url>` | Track a ticket article older than the news listing shows |

## Limits

- The main website doesn't say *which stage* a match sold out at, so
  sell-out and exchange notices are rare and fall back to "check this".
- Times aren't given in articles; 9am is assumed and the event says so.
- Your points total is stored only in `data/` on your Mac.

MIT licence.
