# CLAUDE.md

Reminders for Albion away and cup ticket sales, in a dedicated iCloud
calendar ("Albion tickets"). How the club's pages are built:
`docs/superpowers/notes/2026-11-13-source-recon.md`.

## Hard rules

- **Never request `tickets.brightonandhovealbion.com`** (DataDome bot
  detection; it risks the user's season-ticket account). `fetch.fetch` refuses
  every host but the main website. The ticket site reaches the tool only as a
  PDF the user saved by hand (`albion import`).
- Never log in, touch purchase flows or disguise a request. One request at a
  time, 2 s apart, honest User-Agent with no email.
- **Only the "Albion tickets" calendar is ever changed.** EventKit's access
  reaches every calendar, so `calendar.js` refuses an event ID found elsewhere.
- Never silently miss: anything unreadable becomes a "check this" event.
- A failed fetch or calendar write never removes or loses an event: only
  successes are recorded, and failures retry next run.
- Notice times are anchored to first-seen times, so two-hourly runs are
  idempotent and never re-fire alerts.
- Status labels ("BUY", "Sold Out") mean nothing before the first sale stage
  opens. Sale dates decide.
- No personal data in tracked files (points live in `data/state.json`).
- Tests never touch the network or the real calendar (`FakeCalendar`, or
  `MacCalendar` with a stand-in command). Check behaviour with `--dry-run`.

## Conventions

uv, Python ≥ 3.15 (latest only), src layout, Click is the only runtime dependency, British
English, feature branches only.

## Layout

`fetch` → `discover` (Ticket and Fixture News in the all-news listing) →
`parse_article`/`parse_stages`/`dates` (article → `Match`) → `rules`
(`Outcome`) → `records` (match → record + notices) → `notices` → `sync` →
`calendar_app`. `run.py` wires the check, `importing.py` saved pages; `cli.py`
holds only commands, with `upcoming.py` and `history.py` rendering and
`display.py` the shared table and date helpers. `model.py` defines keys,
seasons and slugs once (`match_key`, `season_of`, `url_slug`).

- **Calendar:** `calendar.js` (EventKit via `osascript`) takes one batch per
  run and prints a JSON result line per change as it goes. Event IDs are
  `calendarItemExternalIdentifier`. JXA wraps ObjC values: compare numbers
  with `Number(…)`, and get `CLLocation` via `NSClassFromString`.
  Each event's URL is `albion-tickets:<notice key>`, and a create first looks
  for that key: a write whose reply was lost (run cut short) is updated, never
  duplicated. `albion tidy` lists or removes events the state doesn't track;
  older records may hold the local ID (`calendarItemIdentifier`), so both count.
- **Saved pages:** `ticket_page` reads the Away/Home Games PDF (PDFKit via
  `pdf_text.js`); `importing.run_import` adds matches with `source: import`. The
  club's news wins: import skips matches an article tracks, and
  `records.adopt_import` hands an imported match to its article by fixture day.
  `state.last_import` drives one event (`IMPORT_KEY`) asking for fresh pages
  three weeks on at 7pm, then weekly until done; each import moves it on.
  Each check rebuilds their sale events from the record
  (`records.refresh_sales`), so a change in how sale events look needs no
  fresh import.
- **Records:** `MatchRecord.summary` is rebuilt every check. What only a saved
  page gives lives beside it: `page_sold_out` (the year-on-year sell-out
  level, read via `sold_out_at()`) and `venue`. `state.have_tickets`
  (`albion got`) leaves a match only its fixture and kick-off-change events.
- **Grounds:** `venues.GROUNDS` holds each Premier League ground's postal
  address and map pin; other grounds come from saved pages (`state.venues`)
  and are pinned by Maps when written. Update `GROUNDS` each summer.
- **Fixture News:** `fixture_news` reads moves, postponements and cup draws
  from an article's sentences; `news_updates` matches each to a tracked match
  (same club and end; nearest date when unsure, else "check this") and records
  it in `MatchRecord.news`, which beats any older source (`with_news`). Read
  about daily for a week; draws create matches with `source: draw`.
- Each check also rebuilds the fixture event of every tracked match it didn't
  read (`records.refresh_fixtures`), so a change in how events look reaches all.
