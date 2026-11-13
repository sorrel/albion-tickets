# CLAUDE.md

Reminders for Albion away and cup ticket sales. Design and plan:
`docs/superpowers/specs/2026-11-13-albion-tickets-design.md`,
`docs/superpowers/plans/2026-11-13-albion-tickets.md`. Source findings:
`docs/superpowers/notes/2026-11-13-source-recon.md`.

## Hard rules

- **Never request `tickets.brightonandhovealbion.com`.** It is protected by
  DataDome bot detection, and automated access risks the user's season-ticket
  account. `fetch.fetch` refuses every host but the main website; keep it so.
- Never log in, never touch purchase flows, never disguise a request.
- One request at a time, 2 s apart, honest User-Agent with no email.
- Status labels ("BUY", "Sold Out") mean nothing before the first sale stage
  opens. Sale dates decide.
- Never silently miss: anything unreadable becomes a "check this" event.
- A failed fetch must never remove calendar events (see `run.py`).
- Notice times are anchored to first-seen times so two-hourly runs are
  idempotent and never re-fire alerts.
- No personal data in tracked files: points live in `data/state.json`.
- Tests never hit the network or the real calendar (`FakeCalendar`). Verify
  behaviour with `albion check --dry-run`, not live runs.

## Conventions

uv, Python ≥ 3.12, src layout, Click is the only runtime dependency, British
English, feature branches only (never commit to `main` directly).

## Layout

`fetch` (polite GET) → `discover` (Ticket News in the all-news listing) →
`payload`/`parse_article`/`parse_stages`/`dates` (article → `Match`) →
`rules` (`Outcome`) → `store` (history, changes) → `notices` → `calendar_app`
(`calendar.js` via `osascript`) — wired together in `run.py`, exposed by `cli.py`.
