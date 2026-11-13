# Albion Away-Ticket Reminders Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A local, unattended tool that reads the club's public ticket news and puts the user's away and cup ticket sale days, sell-outs, exchange openings and kick-off changes into a dedicated phone-synced calendar.

**Architecture:** A pipeline of pure stages: fetch (polite GET) → discover (ticket articles) → parse (article text → `Match`) → decide (rules + points → `Notice`s) → sync (diff against stored state → calendar upserts/removals). Only fetch and the calendar adapter touch the outside world; everything else is pure and tested with fixtures. launchd runs `albion check` every two hours, 07:00–22:00.

**Tech Stack:** Python ≥ 3.12, uv, Click (the only runtime dependency), stdlib `urllib`/`html.parser`/`zoneinfo`/`json`, pytest. Calendar.app driven through `osascript -l JavaScript` (JXA).

**Spec:** `docs/superpowers/specs/2026-11-13-albion-tickets-design.md`

## Global Constraints

- Only ever fetch `https://www.brightonandhovealbion.com` (plus its `robots.txt`). **Never** request `tickets.brightonandhovealbion.com`; a test asserts no code path can.
- One sequential request at a time, 2 s pause between requests, honest User-Agent `albion-tickets/0.1 (personal reminder tool)`, no email address, `robots.txt` respected, no JavaScript executed, no cookies persisted.
- Never log in, never touch purchase flows.
- src layout: `src/albion_tickets/`; `[tool.hatch.build.targets.wheel] packages = ["src/albion_tickets"]`; `[tool.pytest.ini_options] pythonpath = ["src", "."]`.
- Console script `albion = "albion_tickets.cli:cli"`.
- British English in code, comments, output and docs.
- All state under gitignored `data/`. No personal data (points total, paths, names, emails) in tracked files.
- Times are Europe/London (`zoneinfo.ZoneInfo("Europe/London")`).
- Tests never hit the network or the real calendar. Use fixtures and `FakeCalendar`.
- Git: feature branches only. Never override git identity or signing. If signing fails because 1Password is locked, leave the work staged and say so.
- Calendar name: `Albion tickets`. Sale alerts: 19:00 the evening before, 08:30 and 08:55 on the day.

## Review Focus

1. **A failed or partial fetch must never remove events.** A run where the listing or an article fetch fails removes nothing for the affected matches (Task 9, `test_failed_fetch_removes_nothing`).
2. **Pre-sale "Sold Out"/"BUY" labels** must never cancel a reminder (Task 5, `test_sold_out_before_first_stage_is_ignored`).
3. **Year rollover**: a stage line "Tue 29 Dec" for a match on Sat 30 Jan resolves to the previous calendar year (Task 2, `test_year_rolls_back_across_new_year`).
4. **Weekday/date mismatch** in a stage line (a club typo) produces a "check this" notice, not a wrong date (Task 3, `test_weekday_mismatch_is_unreadable`).
5. **Re-running is idempotent**: two identical runs create no duplicate events and no change notices (Task 9, `test_second_identical_run_changes_nothing`).

---

### Task 1: Scaffold the project and capture real fixtures (gate)

**Files:**
- Create: `pyproject.toml`, `.gitignore`, `LICENSE` (MIT), `src/albion_tickets/__init__.py`, `src/albion_tickets/config.py`, `src/albion_tickets/fetch.py`, `tests/__init__.py`, `tests/test_fetch.py`, `tests/fixtures/` (saved pages), `docs/superpowers/notes/2026-11-13-source-recon.md`, `.github/workflows/tests.yml`
- Copy from sibling: `.gitignore` and `.github/workflows/tests.yml` from `../econsult-window-monitor/`. Edit only the comment lines that name the eConsult site. `fetch.py` follows `../econsult-window-monitor/src/monitor/fetch.py` (`FetchResult`, `fetch`, `robots_allows`).

**Interfaces:**
- Produces: `config.BASE_URL = "https://www.brightonandhovealbion.com"`, `config.USER_AGENT`, `config.REQUEST_PAUSE_S = 2`, `config.LISTING_PATHS: list[str]`, `config.DATA_DIR: Path` (repo `data/`, overridable via env `ALBION_DATA_DIR`), `config.TZ`, `config.CALENDAR_NAME = "Albion tickets"`. `fetch.fetch(url: str) -> FetchResult` (never raises; refuses any host other than `BASE_URL`'s, returning `error="host not allowed"`).

- [ ] **Step 1:** `git init` in `albion-tickets/`, commit the spec on `main` as the initial commit, then `git switch -c feature/initial-build`.
- [ ] **Step 2: Write failing tests** in `tests/test_fetch.py`: `test_ticket_site_is_refused` (`fetch("https://tickets.brightonandhovealbion.com/").error == "host not allowed"`, with `urllib` monkeypatched to fail the test if it is called), and `test_user_agent_has_no_email` (`"@" not in config.USER_AGENT`).
- [ ] **Step 3:** Run `uv run pytest tests/test_fetch.py -v`. Expect FAIL (module missing).
- [ ] **Step 4:** Implement `config.py` and `fetch.py`. Run again and expect PASS.
- [ ] **Step 5: Recon (read-only, by hand, a handful of requests).** Using `fetch`, save into `tests/fixtures/`: the men's news listing (`/latest-news-men`) and its first two further pages (find the pagination URL in the HTML); and ticket articles for at least one away match with points brackets, one with "brackets will be announced", one sold-out or "Wheelchair Only" article if any exists, and one home cup tie. Strip anything personal. Record in the recon note:
  - which listing path(s) and page URL scheme to set in `config.LISTING_PATHS`;
  - how ticket articles can be told apart (title words, "Ticket News" category tag in the HTML);
  - whether articles give kick-off date and time, competition and venue, and in what wording;
  - whether the main site ever states the sold-out stage, "Wheelchair Only", or the exchange close date;
  - **coverage**: for each away match the ticket site listed on 13 Nov 2026 (Hull, Bournemouth, Forest, Panathinaikos, Fulham, Spurs, Brentford, Newcastle, Man Utd, Ipswich, Leeds, Villa, Everton, Palace, Arsenal), is there a main-site article?
- [ ] **Step 6: Gate.** If fewer than about two-thirds of those away matches have an article, or articles lack sale-stage lines, **stop and report to the user** before Task 2. The spec says to come back to them.
- [ ] **Step 7:** Commit: `feat: scaffold albion-tickets with polite fetch and source fixtures`.

### Task 2: Dates

**Files:** Create `src/albion_tickets/dates.py`, `tests/test_dates.py`

**Interfaces:**
- Produces: `parse_day_date(text: str, before: date | None, after: date | None) -> date | None`. It accepts `Tue 27 Oct`, `Tues 7 Apr`, `Thur 29 Oct`, `Thu 01 Apr`, `Wednesday 18 Nov`, and `Mon 30th Nov`. It returns `None` when the weekday contradicts the date in the inferred year. It also produces `parse_time(text: str) -> tuple[time, bool]`, which accepts `9am`, `9:30am`, `10.00am` and `2:05 PM`, and returns `(time(9, 0), True)` (the second item is `assumed`) when there's no time. Finally it produces `at_london(d: date, t: time) -> datetime` (aware).
- Year inference: choose the year among `{y-1, y, y+1}` (where `y` is the year of `before` or `after`) that is ≤ `before` and nearest to it. If `before` is `None`, choose the year ≥ `after` and nearest to it.

- [ ] **Step 1: Failing tests:**
  - `test_parses_abbreviations` (each form above);
  - `test_year_rolls_back_across_new_year` (`parse_day_date("Tue 29 Dec", before=date(2027,1,30), after=None) == date(2026,12,29)`);
  - `test_weekday_mismatch_returns_none` (`"Wed 27 Oct"` before 2026-12-05 gives `None`, because 27 Oct 2026 is a Tuesday);
  - `test_missing_time_is_assumed_9am`;
  - `test_pm_times`.
- [ ] **Step 2:** Run and expect FAIL. **Step 3:** Implement. **Step 4:** Run and expect PASS. **Step 5:** Commit: `feat: date and time parsing with year inference`.

### Task 3: Parse sale stages and status lines

**Files:** Create `src/albion_tickets/model.py`, `src/albion_tickets/parse_stages.py`, `tests/test_parse_stages.py`

**Interfaces:**
- Produces in `model.py` (frozen dataclasses):
  - `Stage(label: str, audience: Literal["sth","myalbion","guests","general","other"], min_points: int | None, brackets_pending: bool, opens: datetime, time_assumed: bool)`;
  - `Status(sold_out_to: str | None, sold_out_min_points: int | None, sold_out_label_seen: bool, wheelchair_only: bool, exchange_closes: datetime | None)`.
- Produces `parse_stages(text: str, match_day: date | None, published: date | None) -> tuple[list[Stage], list[str]]`. It returns the stages in published order, plus the lines that *looked* like stage lines but couldn't be read. Also produces `parse_status(text: str, match_day: date | None, published: date | None) -> Status`.
- Audience rules:
  - `STH`, `Season Ticket` or `1901` → `sth`, unless the label ends in `Guests` → `guests`;
  - `MyAlbion+` → `myalbion`;
  - `General Sale` → `general`;
  - everything else → `other`.
- `min_points` comes from `w/ N+ Points`, `with N+pts` or `N+ points`. `brackets_pending` is true for `STHs/1901 Club Members *:`.

- [ ] **Step 1: Failing tests**, using the real lines quoted in the spec (copy them verbatim):
  - `test_forest_four_brackets` (four `sth` stages with points 284, 225, 205, None, opening Tue 27 to Fri 30 Oct 2026 at 09:00, then `myalbion`);
  - `test_article_variant_with_pts_and_no_time` (`time_assumed=True`);
  - `test_brackets_pending`;
  - `test_weekday_mismatch_is_unreadable` (that line is returned in the unreadable list);
  - `test_sold_out_to_bracket` (`sold_out_min_points == 239`);
  - `test_sold_out_to_all_myalbion`;
  - `test_wheelchair_only`;
  - `test_exchange_close` (`Wednesday 18 Nov, 9am`);
  - one test per saved fixture from Task 1, asserting the stages found.
- [ ] **Steps 2–4:** Run and expect FAIL, implement, then run and expect PASS. **Step 5:** Commit: `feat: parse sale stages and sell-out status`.

### Task 4: Parse a whole article into a Match; decide what's tracked

**Files:** Create `src/albion_tickets/text.py`, `src/albion_tickets/parse_article.py`, `src/albion_tickets/discover.py`, `tests/test_parse_article.py`, `tests/test_discover.py`

**Interfaces:**
- Consumes: Task 3.
- Produces:
  - `text.visible_text(html: str) -> str` (stdlib `HTMLParser`; drop script, style and nav; collapse whitespace; one line per block);
  - `model.Match(key: str, opponent: str, home: bool, competition: str, kickoff: datetime | None, kickoff_confirmed: bool, stages: list[Stage], status: Status, fixture_points: int | None, url: str, unreadable: list[str])`;
  - `parse_article(html: str, url: str, today: date) -> Match | None`, which returns `None` when the article isn't about a single match;
  - `is_tracked(m: Match) -> bool`, true for away matches, or home matches whose competition isn't the Premier League;
  - `discover.ticket_articles(listing_html: str) -> list[tuple[str, str]]`, giving `(absolute_url, title)` for ticket articles only. Use the method found in the Task 1 recon note.
- `key` is `f"{season}-{slug(opponent)}-{'h' if home else 'a'}-{slug(competition)}"`, where the season runs August to July (for example `2026-27`). It mustn't include the kick-off, because the kick-off can move.

- [ ] **Step 1: Failing tests:**
  - per fixture, the expected `Match` fields;
  - `test_key_ignores_kickoff`;
  - `test_premier_league_home_not_tracked`;
  - `test_home_cup_tie_tracked`;
  - `test_unconfirmed_kickoff` (the "not yet confirmed" wording gives `kickoff_confirmed=False`);
  - `test_discover_finds_only_ticket_articles` (on the listing fixture);
  - `test_womens_articles_excluded`.
- [ ] **Steps 2–4:** Run and expect FAIL, implement, then run and expect PASS. **Step 5:** Commit: `feat: parse ticket articles into matches`.

### Task 5: Rules — the user's stage, sell-outs, exchange

**Files:** Create `src/albion_tickets/rules.py`, `tests/test_rules.py`

**Interfaces:**
- Consumes: `Match`, `Stage` and `Status`.
- Produces `Outcome(kind: Literal["sale","predicted_sale","sold_out_before_you","exchange_open","unreadable"], stage: Stage | None, opens: datetime | None, sold_out_stage: str | None, pattern_note: str | None)`, and `decide(m: Match, points: int, now: datetime, first_sold_out_seen: datetime | None) -> Outcome`.
- Rules, from the spec:
  - The user's stage is the first `sth` stage with `min_points is None`, or with `points >= min_points`.
  - **Brackets pending:** the predicted stage is the Friday of the week of the pending stage's date, at 09:00, if that date is a Tuesday. Otherwise use the published date, with `pattern_note` set.
  - **Pattern check:** points-bracket `sth` stages that aren't Tue, Wed, Thu, Fri on consecutive days, ending in an "All" stage, set `pattern_note = "Not the usual Tuesday–Friday pattern"`.
  - **Sold out:** the status counts only if `now` (or `first_sold_out_seen`) is after the first stage's `opens`. `sold_out_min_points` (or "All MyAlbion+/All STHs" wording) names the stage. Otherwise the sold-out stage is the latest stage opened at `first_sold_out_seen`. `wheelchair_only` counts the same as sold out.
  - If the match sold out at a stage before the user's, the outcome is `sold_out_before_you`. If the user qualified at the sell-out stage or later, it's `exchange_open`.
  - A sell-out without a known stage, or `unreadable` lines with no stages, gives `unreadable`.
  - "BUY" is never read at all.

- [ ] **Step 1: Failing tests** (184 points throughout):
  - `test_184_gets_friday_on_forest` (Fri 30 Oct 09:00);
  - `test_300_points_gets_tuesday`;
  - `test_brentford_predicted_friday` (STH pending stage Tue 1 Dec 2026 → `predicted_sale` Fri 4 Dec 09:00);
  - `test_pending_not_tuesday_uses_published_with_note`;
  - `test_irregular_brackets_note`;
  - `test_sold_out_before_first_stage_is_ignored`;
  - `test_spurs_sold_out_at_239_is_before_you`;
  - `test_sold_out_to_all_myalbion_is_exchange_open`;
  - `test_wheelchair_only_after_thursday_opened_means_sold_at_thursday` (`sold_out_before_you`);
  - `test_wheelchair_only_after_friday_opened_is_exchange_open`;
  - `test_sold_out_unknown_stage_is_unreadable`.
- [ ] **Steps 2–4:** Run and expect FAIL, implement, then run and expect PASS. **Step 5:** Commit: `feat: decide the user's stage and exchange access`.

### Task 6: State and change detection

**Files:** Create `src/albion_tickets/store.py`, `tests/test_store.py`

**Interfaces:**
- Produces a `State` dataclass, persisted as `data/state.json` (written atomically: temp file, then `os.replace`), with these fields:
  - `points: int | None`;
  - `matches: dict[str, MatchRecord]`;
  - `events: dict[str, str]`, mapping a notice key to a calendar uid;
  - `dismissed: set[str]`;
  - `articles: dict[str, str]`, mapping a URL to a match key.
- `MatchRecord(kickoffs: list[tuple[str, str]], stage_opens: dict[str, str], first_sold_out_seen: str | None, last_seen: str)` holds observation history as ISO strings: kick-off values with when each was seen, and the user's stage `opens` value.
- Functions:
  - `load(path) -> State`, which gives an empty state when the file is missing and raises on a corrupt file (never silently resets);
  - `save(state, path)`;
  - `snapshot(url: str, text: str, data_dir: Path) -> bool`, which writes `data/snapshots/<sha256 of normalised text>.txt` plus an index line, and returns `True` if the text is new;
  - `observe(state, m: Match, outcome_opens: datetime | None, now) -> list[Change]`.
- `Change(kind: Literal["kickoff_moved","sale_moved"], match_key: str, old: str, new: str)`. Only a real change of a known value counts. The first observation never produces a `Change`.

- [ ] **Step 1: Failing tests:**
  - `test_first_observation_no_change`;
  - `test_kickoff_moved_detected_and_history_kept`;
  - `test_same_kickoff_no_change`;
  - `test_sale_moved_detected`;
  - `test_first_sold_out_seen_recorded_once`;
  - `test_snapshot_dedupes_identical_text`;
  - `test_corrupt_state_raises`;
  - `test_save_is_atomic` (the temp file is gone and the content round-trips).
- [ ] **Steps 2–4:** Run and expect FAIL, implement, then run and expect PASS. **Step 5:** Commit: `feat: local state with kick-off and sale history`.

### Task 7: Notices — what goes in the calendar

**Files:** Create `src/albion_tickets/notices.py`, `tests/test_notices.py`

**Interfaces:**
- Consumes: `Match`, `Outcome` and `Change`.
- Produces:
  - `Notice(key: str, title: str, start: datetime, end: datetime, alarms: list[datetime], notes: str, one_shot: bool)`;
  - `notices_for(m: Match, o: Outcome, points: int, now: datetime) -> list[Notice]`;
  - `change_notices(changes: list[Change], matches: dict[str, Match], now) -> list[Notice]`;
  - `check_this(key: str, url: str, title: str, now: datetime, soonest: datetime | None) -> Notice`.
- Keys are `f"{kind}:{match_key}"`. Change notices use `f"{kind}:{match_key}:{new}"` and have `one_shot=True`.
- Notice catalogue (titles start with 🎟️):
  - **sale / predicted_sale:** starts at `opens` and lasts 15 minutes. Alarms are at 19:00 the day before, 08:30 and 08:55, dropping any that are already past. If all of them are past and `opens` is still in the future, add one alarm at `now + 2 min`. Title: `🎟️ {Opponent} {away|home cup}: your sale {9am} ({stage label}, you have {points})`. A predicted sale's title ends `(predicted: brackets not announced yet)`. The notes list every stage, the `pattern_note`, "time assumed 9am" where applicable, the article URL and when it was last checked.
  - **sold_out_before_you:** at the user's stage time, with no alarms. Title: `{Opponent} sold out at {stage} (you have {points})`.
  - **exchange_open:** starts at `now + 5 min` with an alarm at the start. Plus `exchange_closing`, the day before the close at 19:00, with an alarm, when `exchange_closes` is known.
  - **fixture:** at kick-off for 2 hours, no alarms. The title has `(time not confirmed)` when the kick-off is unconfirmed.
  - **points_upkeep:** away matches only. 09:00 the day after kick-off, no alarms. Title: `Did you go to {Opponent}? If so, update your points (worth {N}): albion points <n>`.
  - **kickoff_moved / sale_moved:** start at `now + 5 min`, alarm at the start. Title: `⚠️ {Opponent}: kick-off moved {old} → {new}`, or `sale moved`.
  - **check_this:** at 08:30 the next day, or `now + 5 min` if `soonest` is before that. One alarm. Title: `Check this ticket article: {title}`.

- [ ] **Step 1: Failing tests:**
  - `test_sale_alarms_evening_and_morning` (three alarms with exact datetimes for Fri 4 Dec 2026);
  - `test_late_found_sale_gets_immediate_alarm`;
  - `test_predicted_title_marked`;
  - `test_sold_out_note_has_no_alarms`;
  - `test_exchange_closing_day_before_1900`;
  - `test_fixture_unconfirmed_title`;
  - `test_points_upkeep_away_only`;
  - `test_change_notice_is_one_shot_with_unique_key`;
  - `test_check_this_next_morning`.
- [ ] **Steps 2–4:** Run and expect FAIL, implement, then run and expect PASS. **Step 5:** Commit: `feat: build calendar notices`.

### Task 8: Calendar adapter

**Files:** Create `src/albion_tickets/calendar.py`, `tests/test_calendar.py`

**Interfaces:**
- Produces a `Calendar` protocol with:
  - `upsert(n: Notice, uid: str | None) -> str`, which returns the uid;
  - `remove(uid: str) -> None`, which does nothing if the event has gone;
  - `check_ready() -> str | None`, which returns an error message, or `None` when ready.
- Produces `FakeCalendar` (an in-memory dict, used by all later tests) and `MacCalendar`. `MacCalendar` runs one `osascript -l JavaScript` script per call, passing the notice as JSON on stdin, never interpolated into the script text.
- `MacCalendar` doesn't create the calendar itself. `check_ready()` returns `Calendar "Albion tickets" not found — create it in Calendar.app under your iCloud account` when it's missing. It sets alarms as display alarms with `triggerInterval` in minutes relative to the start, and a subprocess timeout of 30 s.

- [ ] **Step 1: Failing tests:**
  - `test_fake_upsert_then_update_keeps_uid`;
  - `test_fake_remove_missing_is_noop`;
  - `test_mac_payload_goes_via_stdin` (monkeypatch `subprocess.run` and assert the notice title isn't in `args` but is in `input`);
  - `test_alarm_minutes_relative_to_start` (19:00 the day before a 09:00 start gives `-840`).
- [ ] **Steps 2–4:** Run and expect FAIL, implement, then run and expect PASS.
- [ ] **Step 5: By hand, once, after asking the user:** create the calendar, run a one-off script that upserts a test notice dated tomorrow, confirm it appears on the phone, then remove it. Don't automate this.
- [ ] **Step 6:** Commit: `feat: calendar adapter for Calendar.app`.

### Task 9: The run — fetch, parse, decide, sync

**Files:** Create `src/albion_tickets/run.py`, `tests/test_run.py`

**Interfaces:**
- Consumes everything above.
- Produces `run_check(cal: Calendar, fetcher: Callable[[str], FetchResult], state_path: Path, now: datetime, dry_run: bool) -> Report`, where `Report(created: list[str], updated: list[str], removed: list[str], changes: list[str], errors: list[str])`.
- Order of work:
  1. Check that the calendar is ready. If it isn't, abort with an error.
  2. Points `None` → abort with "Set your points first: albion points <n>".
  3. Fetch the listing pages and discover articles.
  4. Merge with the known `state.articles` for matches whose kick-off is still in the future (or less than a day ago).
  5. Fetch each one, snapshot it, parse it, and skip it if it isn't tracked.
  6. Decide, observe the changes, and build the notices, dropping dismissed `check_this` keys.
  7. Upsert each one.
- **Removal rule:** remove an event only if (a) its match's article was fetched and parsed successfully this run, (b) its key isn't in this run's notices, and (c) it isn't `one_shot`. If any listing fetch failed, discovery adds nothing new but known articles still run. Matches past kick-off + 1 day are dropped from tracking, but their events stay.
- `dry_run` computes everything, writes nothing, and calls no `upsert` or `remove`.

- [ ] **Step 1: Failing tests** (`FakeCalendar` plus a fixture-backed fake fetcher):
  - `test_end_to_end_creates_sale_fixture_and_points_events`;
  - `test_second_identical_run_changes_nothing`;
  - `test_failed_fetch_removes_nothing`;
  - `test_changed_article_moves_event_and_adds_change_notice`;
  - `test_dry_run_writes_nothing`;
  - `test_missing_points_aborts`;
  - `test_never_requests_ticket_site` (the fake fetcher records every URL, and none has the `tickets.` host);
  - `test_dismissed_check_this_not_recreated`.
- [ ] **Steps 2–4:** Run and expect FAIL, implement, then run and expect PASS. **Step 5:** Commit: `feat: end-to-end check run with safe removal`.

### Task 10: CLI

**Files:** Create `src/albion_tickets/cli.py`, `tests/test_cli.py`

**Interfaces:** A Click group `cli` with these commands:
- `check [--dry-run]` prints the `Report` and exits 1 if there are errors;
- `points <n>` sets the points total (`n` must be 0–2000);
- `upcoming` lists tracked matches with your stage date, status and any `check_this` keys;
- `history` lists each match's kick-off history and sold-out stage;
- `dismiss <key>` adds a `check_this` key to `dismissed`.

- [ ] **Step 1: Failing tests** (Click `CliRunner`, `ALBION_DATA_DIR` set to `tmp_path`, `MacCalendar` patched to `FakeCalendar`):
  - `test_points_sets_and_upcoming_shows`;
  - `test_points_rejects_negative`;
  - `test_check_dry_run_exit_zero`;
  - `test_dismiss_unknown_key_errors`.
- [ ] **Steps 2–4:** Run and expect FAIL, implement, then run and expect PASS. **Step 5:** Commit: `feat: albion CLI`.

### Task 11: launchd, docs, finish

**Files:** Create `launchd/com.albion-tickets.check.plist`, `launchd/install.sh`, `launchd/uninstall.sh`, `README.md`, `CLAUDE.md`, `tests/test_launchd_template.py`

- The plist runs `__REPO_DIR__/.venv/bin/albion check` with `StartCalendarInterval` at minute 0 of hours 7, 9, 11, 13, 15, 17, 19, 21 and 22. launchd runs a missed interval once on wake, which gives the catch-up run. There's no `KeepAlive`, and logs go to `data/`.
- `install.sh` and `uninstall.sh` follow `../econsult-window-monitor/launchd/` (substitute `__REPO_DIR__`, `uv sync`, then load or unload).
- `CLAUDE.md` carries the hard rules from Global Constraints. `README.md` covers setup: create the calendar, `albion points <n>`, `albion check --dry-run`, then `launchd/install.sh`.

- [ ] **Step 1: Failing test:** `test_plist_has_no_machine_paths_and_nine_slots`.
- [ ] **Steps 2–4:** Run and expect FAIL, implement, then run and expect PASS.
- [ ] **Step 5:** Run the whole suite with `uv run pytest -q`. Expect everything to pass.
- [ ] **Step 6: With the user present:** `albion points 184`, then `albion check --dry-run`. Review the output together (expect Brentford predicted for Fri 4 Dec 09:00). Then do a real `albion check`, check the phone, and run `launchd/install.sh`.
- [ ] **Step 7:** Commit: `feat: launchd schedule and docs`. Merge to `main` when the user agrees. Creating a GitHub repo is a separate, outward-facing step, so ask first.
