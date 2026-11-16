---
name: trader-alerts
description: >-
  Price Alerts for the NSE. Rings when a price, a stop or the opening bell
  hits. Turns the trade plan into three alerts in one go (the stop, the
  target and the 15:15 flat-by, before the broker's auto square-off), plus
  above / below / stop / target levels, percent moves from the previous
  close, any time of day, and the NSE opening bell at 9:15, each ringing once
  so you are not spammed. Knows NSE hours (9:15 to 15:30 IST) and the 2026
  NSE holidays, works out India time itself, reads quotes from the user's
  own Fyers login (no login today: it says so and rings no price alert;
  time alerts still ring), and writes trader/prices.json for sizing and the
  risk check. Use when the user says
  "alert me when", "tell me if HCLTECH hits", "watch my stop", "watch my
  trade", "remind me to close by 3:15", "is the market open", "when does the
  market open", "get me a price", or right after /trader-exit writes a plan.
argument-hint: "[symbol] [price]"
---

# trader-alerts

Price Alerts watches the numbers so the user does not have to stare at a
chart. An alert is information, never an order: when a stop alert rings,
nothing is sold by this skill. With a broker's bracket order (or a Dhan Super
Order) the stop-loss and the target already sit at the broker and do the
work; the alerts tell the user what happened and when it is time to be flat.

`${CLAUDE_SKILL_DIR}` below is this skill's folder (where this SKILL.md lives).

```bash
python "${CLAUDE_SKILL_DIR}/alerts.py" clock                          # NSE open or closed, next open
python "${CLAUDE_SKILL_DIR}/alerts.py" add --from-plan                # stop, target, flat-by from trader/plan.json
python "${CLAUDE_SKILL_DIR}/alerts.py" add --opening-bell
python "${CLAUDE_SKILL_DIR}/alerts.py" add --symbol HCLTECH --stop 1377.40
python "${CLAUDE_SKILL_DIR}/alerts.py" add --symbol HCLTECH --target 1399.00
python "${CLAUDE_SKILL_DIR}/alerts.py" add --at 15:15 --label "flat by 15:15"
python "${CLAUDE_SKILL_DIR}/alerts.py" add --symbol "M&M" --pct 1.5
python "${CLAUDE_SKILL_DIR}/alerts.py" check                          # exit 0 = something rang
python "${CLAUDE_SKILL_DIR}/alerts.py" quote HCLTECH --write          # -> trader/prices.json
python "${CLAUDE_SKILL_DIR}/alerts.py" quote --holdings --write       # portfolio + plan symbols
python "${CLAUDE_SKILL_DIR}/alerts.py" list
python "${CLAUDE_SKILL_DIR}/alerts.py" reset hcltech.ns-plan-stop
```

`--now "2026-11-13 15:15"` pins the clock (India time); `--offline DIR`
reads saved quote files (`yahoo-<SYMBOL>.json`) instead of the network;
`--source fyers|yahoo` picks the quotes (below). Quote a symbol with `&`
(`"M&M"`) in a shell.

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
| `trader/plan.json` | the trade from trader-exit, for `add --from-plan` |
| `trader/alerts.json` | the rules (`alerts.example.json` in this folder) |
| `trader/state/alerts.json` | which rules rang and when, so each rings once |
| `trader/prices.json` | the latest quotes, merged in, for trader-budget and trader-risk; `detail.<SYM>.source` says fyers or yahoo |
| `~/.day-trader-india/` | the day's Fyers token and request count (written by `fyers.py`, outside the repo) |
| `trader/portfolio.json` | the symbols held, for `quote --holdings` |

## Rule types

| type | rings when | rings again |
| --- | --- | --- |
| `above` / `target` | price at or above `price` | after `reset`, or on its own if `"rearm": true` and the price fell back |
| `below` / `stop` | price at or below `price` | same |
| `pct_move` | moved `pct` percent from the previous close (or `ref`), optional `direction` up or down | once per day at most |
| `time` | the India clock passed `at` ("15:15") on a trading day | once per trading day |
| `opening_bell` | the NSE is open | once per trading day |

A rule with `"date"` is watched on that India date only; `--from-plan` rules
carry the plan's date, so yesterday's stop never rings today. The NSE has no
early closes, so a time rule always rings at its own time.

## Quotes

- Fyers (the default): `api-t1.fyers.in/data/quotes`, one request for up to
  50 symbols. A symbol Fyers has no quote for is an error line, not a Yahoo
  price. The quote's time is when it was read (Fyers' answer has no trade
  time). It is one reading per check, not a stream.
- Yahoo, only with `--source yahoo` (practice): `query2.finance.yahoo.com/v8/finance/chart/<SYMBOL>.NS`, an
  unofficial free JSON endpoint, one request per symbol, half a second apart.
  On a 429 it waits and tries once more; on a 429 or a 5xx after that it
  tries `query1`. Upstream's second source, Stooq, only knew US tickers and
  is gone.
- Yahoo quotes are unofficial and run 15 to 30 minutes behind: never for a
  live stop, target or size. Each line of `quote` ends in `[fyers]` or
  `[yahoo]`, and trader-risk and trader-budget warn about a Yahoo price. The broker's price is the
  one that fills. Each price in `trader/prices.json` keeps its quote time, and
  trader-risk only uses one under 15 minutes old.
- If Fyers is down, read the price from the broker's app and write it into
  `trader/prices.json` as `{"as_of": "...Z", "prices": {"HCLTECH.NS": 1384.60}}`.

## The NSE clock

The regular session is 9:15 a.m. to 3:30 p.m. India time (IST, UTC+5:30, no
daylight saving), closed on weekends and on the 2026 trading holidays from
NSE circular NSE/CMTR/71775: Jan 26, Mar 3 (Holi), Mar 26, Mar 31, Apr 3
(Good Friday), Apr 14, May 1, May 28, Jun 26, Sep 14, Oct 2, Oct 20
(Dussehra), Nov 10 (Diwali-Balipratipada), Nov 24, Dec 25. Muhurat trading
(Sunday Nov 8, a special evening session) is not treated as a session. For
any other year it says the holiday list is unknown: NSE publishes the next
year's list each December.

## Steps

1. Right after trader-exit writes the plan, run `add --from-plan`. Confirm
   the three alerts back to the user: the stop, the target and the flat-by time.
2. Run `check` while the trade is open: every few minutes from a Claude
   scheduled task or `/loop`. Each run fetches only the symbols in today's
   rules (one Fyers request for all of them) and rings each alert once. A
   check reads one quote; it is not a stream, and a price can pass a level
   between two checks. Every 2 to 5 minutes is plenty, and stays far inside
   Fyers' limits.
3. Tell the user what rang in one line each. A stop or target alert means the
   Super Order has probably filled: check the positions in the broker's app
   and record the fill with trader-broker. The flat-by alert means close
   anything still open: trader-broker `flatten`, then trader-risk, then the
   user's yes. Never act for them.

## Example: HCLTECH, Friday 2026-11-13

Entry 1384.60 at 9:35 AM, stop 1377.40, target 1399.00, flat by 15:15.
`add --from-plan` writes `hcltech.ns-plan-stop`, `hcltech.ns-plan-target`
and `hcltech.ns-flat-by` for that day. A `check` reads the quote, 1378.00,
between the stop and the target:

```
NSE OPEN (2026-11-13 10:00 IST, regular session).
Nothing hit. 3 rule(s) watched today, HCLTECH.NS Rs 1378.00.
```

At 3:15 PM:

```
ALERT Flat by 15:15, before the auto square-off: it is 15:15 IST (set for 15:15), the market closes at 15:30.
If HCLTECH.NS is still open, close it: trader-broker flatten --symbol HCLTECH.NS builds the sell ticket, then
trader-risk and your yes.
```

It rings once. The next trading day the plan's three alerts are no longer
watched; with `add --opening-bell`, the bell rings at 9:15.

## Rules

- An alert is a fact about a price or the clock. Say it as a fact.
- Never present a Yahoo quote as live: it is delayed and unofficial. A
  Fyers quote is a reading at the time shown, not a stream.
- Never ask for, print or handle the Fyers secret, PIN, TOTP or token. The
  user logs in in their own terminal.
- Confirm every new rule back to the user: symbol, type, level, day.

## What it never does

It never places, cancels or changes an order, never claims a Yahoo quote
is live, never runs the Fyers login for the user, and never predicts where a
price is going.

## Safety

- Education and tooling, not financial advice. A PASS is a rules check, not a recommendation. Not SEBI-registered advice.
- Paper trading by default (`"paper": true`): practice, written down, not placed. Going live is the user's own decision, in their own config.
- Nothing in this pack places an order. trader-broker shows a ticket only when trader-risk passed that exact order
  today, and records a yes only when the user typed an explicit yes for that one order in the chat. The user then
  places it themselves, in their own broker's app, and records the result.
- No F&O, margin (MIS leverage), short selling or leverage unless the config allows it and the user confirms.
- Broker logins, passwords, PINs, OTPs and API keys never go in the chat.
