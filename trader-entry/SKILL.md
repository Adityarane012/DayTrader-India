---
name: trader-entry
description: >-
  Entry Timer for the NSE. Watches a setup bar by bar and tells you the moment
  to get in. Reads 1-minute or 5-minute bars for NSE symbols (RELIANCE.NS,
  M&M.NS; a bare RELIANCE gets the .NS) from the user's own Fyers login
  (it stops, and says so, when there is none today), builds the opening range
  (9:15 to 9:30 IST by default) and calls the entry on the first completed bar
  that CLOSES above the range high, or above a level you give it (like a
  20-day high from the scanner), with an optional volume check. Says waiting
  and how far, triggered with the time and the price, expired, or not open
  yet, and writes trader/entry.json for /trader-exit. Long side only. It never
  places an order. Use when the user says "tell me when to get in", "watch
  RELIANCE", "has it broken out", "did it break the opening range", "entry
  signal", "time my entry", "check my watchlist", or after /trader-scanner
  and /trader-news, before /trader-exit.
argument-hint: "[SYMBOL] [--setup orb|level] [--interval 5m|1m]"
---

# trader-entry

The Entry Timer turns a setup into one moment: the bar that confirms it. It
reads bars, 1-minute or 5-minute, and waits for each one to finish. A price
that pokes above the high in the middle of a bar is not an entry. A bar that
CLOSES above it is. Then it says the time and the price, writes them down for
the Exit Planner, and stops. It never buys anything. Day trading loses most
people money, and a clean signal does not change that.

`${CLAUDE_SKILL_DIR}` below is this skill's folder (where this SKILL.md lives).

```bash
python "${CLAUDE_SKILL_DIR}/entry.py" check HCLTECH               # 15-minute opening range, 5-minute bars
python "${CLAUDE_SKILL_DIR}/entry.py" check HCLTECH --write       # also save trader/entry.json
python "${CLAUDE_SKILL_DIR}/entry.py" check RELIANCE --setup level --level 1342.80
python "${CLAUDE_SKILL_DIR}/entry.py" check "M&M" --interval 1m --min-volume-x 1.5
python "${CLAUDE_SKILL_DIR}/entry.py" watch HCLTECH --until 15:00 # one line per closed bar, stops on the trigger
python "${CLAUDE_SKILL_DIR}/entry.py" watchlist                   # every hit in trader/watchlist.json
```

Quote a symbol with `&` in it (`"M&M"`): a shell reads a bare `&` as "run in
the background". Other flags: `--or-minutes N` (default 15), `--json`,
`--source fyers|yahoo` (below), `--offline FILE` (a saved Yahoo chart
JSON, `.json` or `.json.gz`, or a folder of `<SYMBOL>.NS.json`; always read as
Yahoo), `--now "2026-11-13 09:35"` (India time) to replay a day. `watch` with
`--now` or `--offline` runs on a simulated clock and replays the day bar by
bar without waiting.

## Fyers: live prices from your own login

Live prices come from the user's own Fyers login, and only from it:
Yahoo's NSE data runs 15 to 30 minutes behind, too late to time an entry or
ring a stop. `fyers.py` in this folder does the login and reads prices. It
has no order call in it.

Once, in the Fyers API dashboard (fyers.in/web/api-dashboard/user-apps):
the app needs the Market Data permission and the redirect URL
`http://127.0.0.1:8765/` (any free port works, if the two match). Then the
user sets three environment variables in their own terminal. On Windows:
`setx FYERS_APP_ID "..."`, `setx FYERS_SECRET_ID "..."`,
`setx FYERS_REDIRECT_URI "http://127.0.0.1:8765/"`, then a new terminal.
The secret is typed there, never in the chat.

Each trading day, after 6:30 AM India time (Fyers tokens expire then), the
USER runs, in their own terminal:

```bash
python "${CLAUDE_SKILL_DIR}/fyers.py" login     # opens the Fyers login: ID, PIN, TOTP in the browser
python "${CLAUDE_SKILL_DIR}/fyers.py" status    # logged in until when, requests used today
```

Claude never runs `login` and never asks for the PIN, the TOTP, the secret or
the token. The token is saved in `~/.day-trader-india/`, outside the repo.

Log in between 9:00 and 9:10 AM to be safe: the pre-open session (9:00 to
9:08) already gives a quote, so a problem shows before the bell. The latest
that still catches the first possible entry is before 9:35 (the 9:30 bar's
close); Fyers' candles hold the whole day so far, so the 9:15 to 9:30 range
is there even if you log in after the open.

`--source fyers` is the default. Without today's login, or when Fyers cannot
answer (an expired token, a network error, its request limit), the tool
stops and says why, with the login command. It never switches to Yahoo on
its own. `--source yahoo` reads Yahoo's delayed data only when asked, for
practice and replays, and every line it prints says "delayed". The free Fyers plan allows 50 data requests a minute and 5,000 a day,
and going over the minute limit more than 3 times blocks the account for the
day, so `fyers.py` stops itself at 40 a minute and 4,500 a day, and after one
"too many requests" it does not ask Fyers again that day.


## What it reads and writes

| file | what |
| --- | --- |
| `trader/watchlist.json` | the scanner's hits (`hits[].symbol`), for `watchlist` |
| `trader/config.json` | `no_entries_before` (09:30) and `no_entries_after` (15:00), India time. Optional |
| Fyers history API | today's bars from the user's own login (`fyers.py`) |
| Yahoo chart API | only with `--source yahoo` (practice, replays): `range=1d&interval=5m`, delayed, unofficial |
| `~/.day-trader-india/` | the day's Fyers token and request count (written by `fyers.py`, outside the repo) |
| `trader/entry.json` | with `check --write`, or when `watch` triggers: symbol, setup, status, time, bar, price, level, opening range, and `prev_close` (the previous close, for trader-exit's price-band warning). Fyers' bars do not carry it, so a live trigger makes one extra Fyers quote for it; if that fails it is left empty and you pass `--prev-close` to trader-exit. A replay (`--now`, `--offline`) asks for no quote |

## The rule

- **Market hours.** The NSE session is 9:15 to 15:30 IST (UTC+5:30, no
  daylight saving). Weekends and NSE holidays are closed, and so is Muhurat
  trading: it is a special evening session, not a day to day-trade.
- **Opening range (orb).** The high and low of the first 15 minutes: the
  9:15, 9:20 and 9:25 five-minute bars, or fifteen 1-minute bars. The level
  to beat is the range high.
- **Level.** A price you give, like a 20-day high from `/trader-scanner`.
- **The trigger** is the first completed bar after the range that CLOSES
  above the level. A wick above is not a trigger. A close exactly at the
  level is not above it.
- **The time** is that bar's close time (the 9:30 bar closes at 9:35 AM).
  The price is its close, to the paisa.
- **Only closed bars count.** A bar is closed when the clock passes its start
  plus 5 (or 1) minutes and, on Yahoo, Yahoo has caught up to that moment
  (it waits a minute at most). Yahoo's live tick, like 10:49:45, is never a
  bar. Fyers' bar still forming is not counted either. Fyers bars that do not
  fit the session (off the bar grid, or in the future) are refused with the
  reason.
- **Volume, if you want it.** `--min-volume-x 1.5` also needs the trigger
  bar's volume at 1.5 times the range bars' average. On NSE symbols Yahoo
  sends 0 volume for the 9:15 bar (the opening auction is not in it), so the
  range's average is lower than the real one and the check is looser than it
  looks.
- **Time limits.** No entries before 9:30 (the range is not set) or after
  15:00 (config): the Exit Planner gets you flat by 15:15, before the
  broker's auto square-off.
- **What it says.** Waiting (and how far the last close is from the level),
  triggered, expired, or no data. Before 9:15: not open yet. Before 9:30: the
  range is still forming. Weekends and NSE holidays: the market is closed.
  The holiday list covers 2026 (NSE circular NSE/CMTR/71775); for a later year
  it says to check the NSE list.

## Steps

1. Get the symbol from the user, or run `entry.py watchlist` after
   `/trader-scanner`. Check `/trader-news` for it first. On a trading day,
   if it says "no Fyers login today", ask the user to run `fyers.py login`
   in their own terminal; do not switch to `--source yahoo` for a live
   decision.
2. Run `entry.py check SYMBOL`. Tell the user the status in one line:
   waiting and how far, triggered at what time and price, or expired.
3. To wait for it, Claude can run `entry.py watch SYMBOL --until 15:00` in
   the background, or `entry.py check SYMBOL --write` on a `/loop` every 5
   minutes. `watch` wakes just after each bar closes, prints one line per
   bar, and exits 0 on the trigger (it writes `trader/entry.json`) or 1 when
   the setup expires. Keep the computer awake while it watches: a sleeping
   laptop pauses it, and it catches up, late, when it wakes.
4. When it triggers, say the time and the price, and that nothing was placed.
   If the trigger is more than a bar old, say that too: a late entry is a
   different trade.
5. Hand off to `/trader-exit` to set the stop and the target BEFORE anything
   is bought.

## Example: HCLTECH, Friday 2026-11-13

HCLTECH.NS, 5-minute bars, real data. The opening range is 1373.80 to
1381.00. At 9:34 the 9:30 bar is still open, so it waits:

```
WAITING  last close Rs 1378.60 (9:25 bar), Rs 2.40 under the range high Rs 1381.00 (-0.17%).
The 9:30 bar is still forming (Rs 1384.60 so far, closes 9:35 AM); it does not count until it closes.
```

At 9:35 the bar has closed:

```
HCLTECH.NS  Fri 2026-11-13 09:35 IST  opening-range breakout (15-minute range) on 5-minute bars (Fyers, your own login)
Opening range 9:15-9:30: high Rs 1381.00, low Rs 1373.80 (3 of 3 bars).
TRIGGERED 9:35 AM at Rs 1384.60: the 9:30 bar (bar 3) closed above the range high Rs 1381.00 (+0.26%).
This is the moment to get in, if you take the trade. Nothing was placed.
Next: set the stop and target BEFORE you buy: /trader-exit (exit.py plan --from trader/entry.json).
```

With `--min-volume-x 4` the 9:30 bar is too thin (3.05x the range's volume)
and the trigger moves to 9:40 AM at 1389.70 (the 9:35 bar, 6.40x).

## Rules

- Bar by bar, on 1-minute or 5-minute Fyers bars from the user's login. The
  first line names the source. Yahoo (`--source yahoo`) is delayed and can lag: practice
  and replays only, never a live entry. Not for scalping.
- Never ask for, print or handle the Fyers secret, PIN, TOTP or token. The
  user logs in in their own terminal.
- A signal is information, not an order, and not a promise. Nothing here
  promises winning trades or money.
- Long side only. This pack plans longs only. If the user wants a short, say that.
- One trigger per setup per day: the first close above. Later closes do not
  reset it.
- Never call an entry early because a bar looks like it will close above.

## What it never does

It never places an order, never sizes a position, never sets the stop (that
is `/trader-exit`), never moves the level after the fact, and never counts a
bar that has not closed. It never runs `/trader-broker` from a background
watch: nobody is there to say yes.

## Safety

- Education and tooling, not financial advice. A PASS is a rules check, not a recommendation. Not SEBI-registered advice.
- Paper trading by default (`"paper": true`): practice, written down, not placed. Going live is the user's own decision, in their own config.
- Nothing in this pack places an order. trader-broker shows a ticket only when trader-risk passed that exact order
  today, and records a yes only when the user typed an explicit yes for that one order in the chat. The user then
  places it themselves, in their own broker's app, and records the result.
- No F&O, margin (MIS leverage), short selling or leverage unless the config allows it and the user confirms.
- Broker logins, passwords, PINs, OTPs and API keys never go in the chat.
