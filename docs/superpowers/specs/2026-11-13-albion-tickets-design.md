# Albion away-ticket reminders — design

Date: 13 November 2026. Status: draft, awaiting approval.

## Why

For a season-ticket holder, Premier League home matches are covered. Away
matches and cup matches have to be bought, in sales released in stages by
loyalty points, and it is easy to **forget the sale day**. Miss your morning
and a popular away match is often gone.

The tool exists so that doesn't happen: it tells the user, on their phone,
the evening before and the morning of every sale they can actually take part
in.

Success looks like: no qualifying sale missed through forgetting, and no noise
about sales the user cannot join.

## Goals

- Track **away matches** (all competitions) and **home cup matches** (FA Cup,
  League Cup, European ties: anything at the Amex that is not Premier League).
- Work out, for each match, **the user's stage**: the first stage whose
  condition the user meets, given their points.
- Remind the user of that stage through **calendar events that reach their
  phone**.
- Notice when published information **changes over time** (points brackets
  announced later, dates moved, matches sold out) and update the reminders.
- Tell the user about the **ticket exchange** only when they are allowed to use
  it (see Rules).
- Record, per match, the stage at which it sold out, so over a season the user
  can see how close their points are to an earlier stage.

## Non-goals

- **Buying tickets**, or anything that touches the purchase flow. The club
  actively works to stop applications doing this.
- **Logging in** to anything. The user enters their points total by hand.
- Premier League home matches (covered by the season ticket).
- Push notifications, email, or any channel other than the calendar (for now;
  the reminder output is a separate module so another channel can be added).
- Women's, academy or hospitality events.

## Anti-goals (it fails even if it "works" if…)

- It puts the **season-ticket account at risk**. Hence: never access
  `tickets.brightonandhovealbion.com` (protected by DataDome bot detection),
  never disguise a request, never log in.
- It **silently misses** a sale. Anything it can't read confidently becomes a
  "check this" event, never a guess and never nothing.
- It **spams**: duplicate events for one sale, or reminders for stages the user
  can't join.

## Constraints

- Only source: the club's **public main website**,
  `www.brightonandhovealbion.com`. Plain HTTP fetches of its news and articles
  were confirmed to work (HTTP 200) on 13 Nov 2026. One sequential request at a
  time, honest User-Agent with no email address, `robots.txt` respected, no
  JavaScript executed.
- Follows the `scripts/` workspace conventions: uv, Python ≥ 3.12, src layout
  (`src/albion_tickets/`), Click for the CLI, pytest, British English, no
  personal information in tracked files (the points total lives in gitignored
  local state), feature branches only.
- Runs unattended on the user's Mac via launchd.
- Tests never run against the live site or the real calendar (fixtures and a
  fake calendar only); a `--dry-run` shows what would change.

## What the source looks like

Observed on 13 Nov 2026 (ticket site, viewed once by hand) and in main-site
articles. The tool reads only the main site, but the wording is the same.

Away stage lines:

    STHs/1901 Club Members w/ 284+ Points: Tue 27 Oct 9am
    STHs/1901 Club Members w/ 225+ Points: Wed 28 Oct 9am
    STHs/1901 Club Members w/ 205+ Points: Thu 29 Oct 9am
    All STHs/1901 Club Members: Fri 30 Oct 9am
    All MyAlbion+ Members: Tue 03 Nov 9am

Main-site article variant (no time given): `STHs/1901 Club members with
303+pts: Tues 7 Apr`.

Placeholder before brackets are set: `STHs/1901 Club Members *: Tue 01 Dec,
9am` with "*points brackets will be announced closer to the on sale date".

Sold-out lines: `Sold out to STHs/1901 Club Members w/ 239+ Points`,
`Sold out to All MyAlbion+ Members`. Exchange: `The resale for this fixture will
close on Wednesday 18 Nov, 9am`.

Dates carry **no year**: infer the next occurrence on or before the match date.
Day names are abbreviated inconsistently (Tue/Tues, Thu/Thur). Times are
always 9am in everything seen so far; where none is given, assume 9am and say
so in the event.

## Rules

**User's stage.** Walk the stages in order and pick the first the user meets:
`w/ N+ Points` if points ≥ N, otherwise `All STHs/1901 Club Members`. For home
cup ties, the season-ticket-holder stage. A modest points total typically
falls into the "All STHs/1901" stage.

**The weekly pattern** (from the user). Away sales to STHs/1901 members run
over one week:
- **Tuesday**: the top points bracket, set so that everyone in it who wants a
  ticket is guaranteed one;
- **Wednesday**: the next bracket, up to about a quarter of STHs;
- **Thursday**: up to about half of STHs;
- **Friday**: all remaining STHs. This is usually the user's day.

**Brackets not yet announced.** The STH start date is published well ahead
(e.g. Brentford: "STHs/1901 Club Members *: Tue 01 Dec, 9am"). Predict the
user's day from the pattern: Friday of that week, 9am. Create that event
marked "predicted: brackets not announced yet". When the brackets appear,
confirm or move it. If the user's points reach an earlier bracket, move it
earlier and announce the change, as for any moved date.

**Pattern breaks.** If a published schedule doesn't fit Tue–Fri (a different
start day, more or fewer brackets, a bank-holiday shift), follow what's
published, and say in the event that the usual pattern doesn't apply.

**Sold out before the user's stage.** Replace the sale reminder with a quiet,
alert-free note ("Spurs sold out at 239+, you have 150").

**Ticket exchange.** The exchange is open only to the stage the match sold out
at and above. So:
- sold out at a stage the user qualifies for (e.g. "All STHs/1901 Club
  Members" or "All MyAlbion+ Members") → a "check the exchange" event, with
  the resale closing date where published;
- sold out at a bracket above the user's points → no exchange event.
- If the source says a match sold out but not at which stage → a "check this"
  event with the link.

**"Available" doesn't mean available.** A match can show as on sale (BUY)
when only wheelchair or accessible tickets remain, as with Nottingham Forest
away on 5 Dec 2026. The user does not need accessible tickets. So the tool
never alerts on "tickets still available" status. The site then says
**"Wheelchair Only"** (confirmed by the user), which counts as sold out at
whichever stage was on sale when it first appeared. The
sale-day reminder stands regardless: it fires because the user's stage opens,
not because tickets are shown as available.

**Kick-off changes** (from the user). Record each tracked match's date and
kick-off time every time it's seen, keeping the history, not only the latest
value. Matches are often moved for TV, and the source marks unconfirmed ones
("Fixture date and time is not yet confirmed"). When a date or time changes,
add a "kick-off moved" event with an immediate alert: old → new. This matters
most for matches the user has a ticket for, because travel plans depend on it.
Every tracked match also gets an alert-free calendar event for the match
itself, which moves when the kick-off changes *(Claude's call)*.

**No per-match "bought" or "skip" state** (the user's decision). The user wants
to be kept informed about every tracked match, whatever they've done about it.
So every match gets its sale, sell-out, exchange and kick-off notices, and the
tool never asks the user to tell it which matches they bought.

**Status labels are not trusted; sale dates are** (from the user). Matches
whose sale hasn't started yet often show "BUY" even though nothing can be
bought, and sometimes "Sold Out". Neither label means anything before the
first published stage opens; "BUY" is never used as a signal at all. A "Sold Out" or
"Wheelchair Only" label only counts as a sell-out once the match's first
published stage has opened. Before that it's ignored, and the match is treated
as not on sale yet. The stage that sold out is the latest stage whose start
time has passed when the label first appears after sales opened, unless a
"Sold out to …" line names the stage outright, in which case that line wins.

**Points upkeep.** Ten days after each away match (when the club credits the
points), a "did you go? If so, update
your points (this match was worth N)" event, with no alert, using the points
figure published for the fixture. The user runs `albion points <n>`. Points
also have to be entered when the tool is first set up.
That figure goes only in local state, never in a tracked file.

**"Check this" events** *(builder-check answer; Claude's call)*. They fire
only for articles that look like ticket news for a match the tool tracks (away,
or a home cup tie), or for ticket articles it can't tie to any match at all. A
recognised article about a Premier League home match is ignored. The event goes
at 8:30 the next morning (or straight away, if a stage the user may be in opens
sooner), with one alert, and links to the article. It isn't repeated. It's
removed automatically once the article parses, or by `albion dismiss <match>`.

**Exchange events** *(Claude's call)*. One event on the day the sell-out is
detected, and a second the day before resale closes, if a close date is
published. The exchange isn't nagged about daily.

**Late or changed information** *(Claude's call)*. Runs every two hours from
7am to 10pm, and launchd also runs once on wake if a slot was missed while the
Mac slept. If a sale is found too late for the 7pm-before alert, the event gets
an immediate alert instead. If an existing sale date or time **moves**, the
event is updated *and* a separate "date changed" event with an immediate alert
is added. Calendar edits reach the phone silently, so the change has to be
announced.

## Reminders

One dedicated calendar ("Albion tickets") in Calendar.app on an iCloud account,
so events sync to the user's phone. Each sale event, at the stage time:

- title like `🎟️ Fulham away: your sale 9am (All STHs/1901, you have 150)`;
- notes: all stages, the source link, when it was last checked;
- alerts: 7pm the evening before, 8:30 on the day, 8:55 on the day.

Each event is tied to a stable key (match + kind) so a re-run **updates** it
in place and never duplicates it. A stage that disappears or a cancelled match
removes or retitles its event.

## Approaches considered

- **A. Read the main website's ticket news** (no login, unattended).
  Above board, but may lag the ticket site and omit times.
- **B. Read the ticket site through the user's signed-in Chrome** on a schedule.
  Best data and could read points automatically, but it is automated access to
  the site the club protects, *through the season-ticket account*.
- **C. A, plus the user types their points total.** *Chosen.* Nothing risks the
  account, it runs unattended, and points change only every few weeks.

A plain script fetching the ticket site was ruled out: DataDome blocks it, and
getting round that would mean disguising the script.

For reading articles: fixed patterns over the visible text, with anything
unrecognised falling back to a "check this" event. (Using a language model to
extract stages was considered; it needs an API key and adds cost, and the
wording has proved regular.)

## Parts

1. **Discover**: find ticket-information articles on the main site's news
   listing (the "Ticket News" category if it has its own URL).
2. **Snapshot**: store every distinct version of each article locally, deduped
   by a hash of its normalised text, so changes are visible and debuggable.
3. **Parse**: match, competition, venue, kick-off, stages, sold-out line,
   exchange close, points for the fixture. Unrecognised → "check this".
4. **Decide**: apply the Rules against the stored points total.
5. **Remind**: create, update or remove calendar events.
6. **Run**: launchd, twice a day (morning and early evening), plus a CLI:
   `albion check [--dry-run]`, `albion points <n>`, `albion upcoming`,
   `albion history` (sold-out stages per match).

All state (snapshots, parsed matches, event keys, points) lives in a gitignored
`data/` folder.

## Left to the builder

- How to find ticket articles reliably (category URL, listing pages, or
  keyword matching on titles), and how far back to look.
- How to drive Calendar.app (AppleScript/JXA via `osascript`, or EventKit).
- Storage format (JSON files or SQLite).
- Exact fixture-parsing patterns, built from saved real articles.
- Keeping the open questions below as verified checks early in the build.

## Open risks to verify early

- Whether **every** away and cup match gets a main-site article, and how soon
  after the ticket site. If coverage proves poor, come back to the user before
  building further.
- Whether main-site articles state the **sold-out stage**, or "Wheelchair
  Only", which the exchange rule depends on. Both were seen on the ticket site;
  if the main site never says either, the exchange rule falls back to "check
  this".
