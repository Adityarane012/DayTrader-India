---
name: trader-news
description: >-
  News Monitor for the NSE. Tracks exchange filings and breaking news on
  every stock you watch and flags what moves it: NSE corporate announcements
  per symbol (results, board meeting outcomes, acquisitions, director
  changes, insider and takeover disclosures), Google News headlines (India
  edition) by company name, Yahoo headlines, and how far each stock is from
  yesterday's close. Shows only what is new since the last check, newest
  first, in India time, tags each item (earnings, deal, people, insider,
  block deal, legal, circuit, macro...) and never repeats one. If NSE refuses
  the request it says so and goes on with the headlines. Before the open it
  also lists the day's NSE results and board meetings for your stocks and
  the Nifty 50 (an event day is a reason to skip an opening-range trade) and
  the market's own headlines from Economic Times, Livemint and Moneycontrol.
  Use when the user says "any news on RELIANCE", "morning brief", "Dalal
  Street brief", "any results today", "is anything reporting today", "why is this moving", "what's the news on my
  watchlist", "morning briefing", "pre-market news", "monitor the news", "did
  anything break", "check the NSE announcements", or after /trader-scanner
  finds setups.
argument-hint: "[symbols]"
---

# trader-news

A chart can look perfect and still be about to gap on a results date, a
board meeting or a SEBI order. Before a setup becomes a trade, this skill
reads the feeds that carry those first, for every stock on the watchlist,
and tells you only what is new. It also prints how far each stock has moved
today, so a headline and a move sit side by side.

Tool in this folder (standard library Python, no keys):

```bash
python "${CLAUDE_SKILL_DIR}/news.py"                               # watchlist + plan + portfolio
python "${CLAUDE_SKILL_DIR}/news.py" --symbols RELIANCE HCLTECH --hours 12
python "${CLAUDE_SKILL_DIR}/news.py" --symbols "M&M" --no-nse --json
python "${CLAUDE_SKILL_DIR}/news.py" --events --market               # the morning brief, plus the watchlist's news
python "${CLAUDE_SKILL_DIR}/news.py" --events --market --watchlist trader/picks.json
```

## The morning brief: --events and --market

Run it before 9:15. Both were checked against the live sources on
2026-11-16.

- `--events`: NSE's event calendar, ONE request, today and the next 3 days
  (`nseindia.com/api/event-calendar?index=equities&from_date=..&to_date=..`).
  It lists every result or board meeting of a stock you watch, then of the
  universe (`trader/universe.txt`, the Nifty 50), and counts the rest. A
  stock on your list with an event TODAY gets "an event day, skip an
  opening-range trade": results move a stock in ways an opening range does
  not predict. If NSE refuses, it says "NSE event calendar unavailable" and
  goes on; check the event calendar on nseindia.com in a browser.
- `--market`: the market's headlines from the last `--market-hours` (12),
  newest first, one line a story, at most 15. A `*` marks a story about the
  Nifty, the Sensex, FIIs, the RBI or the market as a whole. Sources:
  - Economic Times Markets RSS: `economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms`
  - Livemint Markets RSS: `livemint.com/rss/markets`
  - Moneycontrol, through Google News limited to its markets and stocks
    sections (`site:moneycontrol.com/news/business/markets when:1d`).
    Moneycontrol's own RSS feeds stopped updating years ago, and a site-wide
    search matched the "Nifty" and "Sensex" in every page's menu.
  Quote pages and "headlines" under 5 words are left out.
- With `--events` or `--market` and no symbols, only the brief runs.
  Summarise it for the user in a few lines: any event on their list first,
  then the 3 headlines that bear on the Nifty today, then their stocks' news.
  Headlines are leads, not facts: say where each came from.

## What it reads and writes

| file / feed | what |
| --- | --- |
| `--symbols`, else `trader/watchlist.json` | the scanner's hits (trader-scanner), with company names |
| `trader/plan.json` | the trade you are planning (trader-exit) |
| `trader/portfolio.json` | what you hold (trader-broker records fills there) |
| NSE corporate announcements | `nseindia.com/api/corporate-announcements?index=equities&symbol=RELIANCE&from_date=..&to_date=..`: the exchange filings for the last `--hours` |
| Google News RSS (India) | `news.google.com/rss/search?q="Reliance Industries"&hl=en-IN&gl=IN&ceid=IN:en`, by the company's name; quote pages ("Share Price Today", "Live NSE/BSE") left out |
| Yahoo Finance headline RSS | `feeds.finance.yahoo.com/rss/2.0/headline?s=RELIANCE.NS&region=IN&lang=en-IN`: usually empty for NSE symbols, kept because it costs one request |
| Yahoo Finance chart endpoint | the last price against yesterday's close (unofficial, can lag) |
| `trader/state/news.json` | what has been shown (kept 30 days) |

## NSE, politely

NSE's endpoints are unofficial and sometimes refuse automated requests. The
tool asks once per symbol, a second apart, with a plain user agent and no
cookies. If NSE answers HTTP 401, 403, 429 or 5xx, or sends an HTML page
instead of JSON, it prints "NSE announcements unavailable", stops asking NSE
for the rest of that check, and goes on with the headlines. It never works
around a block. When that happens, say so to the user and point them to the
announcements page on nseindia.com.

## The rules

- **Headlines are leads, not facts.** Before telling the user something
  happened, open the story or the filing and read it. Quote the source and
  link it. Never summarise a paywalled story you could not read: say so.
- **Filings beat headlines.** If an NSE announcement and a headline
  disagree, the announcement is what the company told the exchange.
- **Say what it touches.** Every item lists the symbols it touches and its
  tags. Headlines: earnings, analyst, legal, deal, block (block and bulk
  deals, OFS), capital, people, risk, circuit, macro (RBI, repo rate, CPI,
  Budget, GST, FII flows). Filings: earnings, people, deal, insider,
  capital, rating, legal, clarification, routine. Filings marked `!` can move
  a stock today: results and board meeting outcomes, acquisitions and
  mergers, director or KMP changes, insider and takeover disclosures, legal
  orders, and the exchange's own clarification requests. `routine` ones
  (newspaper copies, trading-window notices, investor meet schedules) are
  shown but rarely matter.
- **MOVING** marks a stock 3 % or more from yesterday's close (`--move-pct`).
  A move with no headline is worth saying out loud too.
- **No predictions.** Report what was published and how far the price is from
  yesterday's close. Never say what the stock will do next.

## Steps

1. Run the check: `python "${CLAUDE_SKILL_DIR}/news.py"`. Exit code 1 means
   nothing new. `--all` shows items already seen, `--json` gives everything
   machine readable, `--dry-run` leaves the state alone.
2. Read the items that matter: every `!` filing, anything tagged earnings,
   legal, block, circuit or risk, and every MOVING symbol first.
3. Write a short brief, per symbol: what happened, the source and link, the
   move, and one line on why it matters to the setup (for example "results
   are after the close today: an overnight gap can jump past any stop, so
   this is an intraday trade or none").
4. If a story changes the picture, say so before `/trader-entry` and
   `/trader-exit`: a results date, a board meeting, a block deal, an
   exchange clarification. Never act on a headline alone.

During the session: `/loop 15m /trader-news`, or a scheduled task each
morning before the 9:15 open.

## Example: the morning of Saturday 2026-11-14

`news.py --symbols RELIANCE HCLTECH "M&M"` on real data: RELIANCE leads with
Google News stories ("Reliance Industries shares rebound 15% in November, add
Rs 2.38 lakh crore in market value", Livemint; "India's Reliance plans $4.6
billion coal-to-gas project", Reuters) and NSE's 18:25 investor-meet filing
(routine). M&M's NSE feed for the week holds an Acquisition filing and three
board meeting outcomes, flagged `!`. Yahoo's feed was empty for RELIANCE and
HCLTECH. The price lines read `M&M.NS Rs 3333.00 -1.94% vs yesterday's
close Rs 3399.00`. When a symbol has no news, say so rather than padding the
brief.

## What it never does

- Never invents or embellishes a story, a quote or a number.
- Never trades on news, and never tells the user to buy or sell because of a
  headline.
- Never hammers a server: one request per feed per symbol, a second between
  calls, and it stops asking NSE the moment NSE says no.

## Safety

- Education and tooling, not financial advice. A PASS is a rules check, not a recommendation. Not SEBI-registered advice.
- Paper trading by default (`"paper": true`): practice, written down, not placed. Going live is the user's own decision, in their own config.
- Nothing in this pack places an order. trader-broker shows a ticket only when trader-risk passed that exact order
  today, and records a yes only when the user typed an explicit yes for that one order in the chat. The user then
  places it themselves, in their own broker's app, and records the result.
- No F&O, margin (MIS leverage), short selling or leverage unless the config allows it and the user confirms.
- Broker logins, passwords, PINs, OTPs and API keys never go in the chat.
