# Source recon — 13 November 2026

Read-only, by hand: ten requests to www.brightonandhovealbion.com.

## Listing

- `/latest-news-men` holds a curated selection, mostly interviews. It had
  only two "Ticket News" items in two months. **Not usable.**
- `/all-latest-news` holds the newest ~39 articles (about a week). Each
  carries `publishDateTime` and `categories=[{name:"Ticket News",…}]` in the
  page's embedded data (a Nuxt-style payload, not plain links). **Use this.**
  Checked every two hours, a one-week window catches every new ticket article.
- `/sitemap.xml` and `/ticket-news` don't exist (they return a generic page).
- `robots.txt`: `User-agent: * / Allow: /`.

## Articles

- Article text lives in the embedded payload as `articleBody` rich-text nodes
  (`value:"…"`), not in server-rendered HTML. The page also carries *other*
  articles' bodies (related items), so the parser must take only the
  `articleBody` belonging to the page's own slug, bounded by bracket matching.
- **One article can cover several matches** ("Bournemouth and Nottingham
  Forest ticket information").
- Per match: a heading line ("Fulham v Albion", "Bournemouth (away)",
  "Nottingham Forest"), then a date line ("Saturday 26 December - kick-off
  3pm", "Wednesday 2 / December, kick-off 8.15pm."), "On sale dates:", stage
  lines **without times** ("STHs/1901 Club members with 284+pts: Tue 27 Oct"),
  pricing, and "Points allocated for this fixture: 10" (sometimes split across
  lines).
- Escaped `\n` occurs inside text values and must become a line break.

## Coverage (away matches on the ticket site, 13 Nov)

Articles found for Bournemouth, Forest, Fulham and Spurs (current sales), and
Conference League aways (one combined article). Future aways (Brentford
onwards) have no article yet: the ticket site lists their STH start dates
weeks ahead, the main site publishes about a week before. **Gate: passed.**

## Sell-outs

The main site does **not** state the stage a match sold out at, and "Wheelchair
Only" appears only on the ticket site. Sold-out news exists only as articles
such as "Newcastle United sold out – ticket exchange now open" (a home match).
So the exchange rule will mostly fall back to "check this".
