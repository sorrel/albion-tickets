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

`albion import` is the one way in from the ticket site: the user saves its
Away/Home Games page as a PDF by hand, `ticket_page` reads it (PDFKit through
`pdf_text.js`, so no new dependency) and `run.run_import` adds matches marked
`source: import`. The club's news always wins: import skips anything an
article tracks, and `run._adopt_import` hands an imported match to its article
by fixture day. `state.have_tickets` (set by `albion got`) keeps only the
fixture and kick-off-change notices for a match.
The sell-out level a saved page gives is kept in `MatchRecord.page_sold_out`,
not `summary` (every check rebuilds that): it is the year-on-year record, and
the club's news often never states it. Read it via `MatchRecord.sold_out_at()`.

Fixture events carry the ground as their location (`venues.location`): the
built-in `venues.GROUNDS` table first (keep it to this season's Premier
League plus likely visitors, as "Ground, Town"), then the match's own saved
page, then `state.venues` (learnt per away opponent from saved pages), and
the Amex for home games. Update `GROUNDS` each summer when the league changes.
