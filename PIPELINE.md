# The trading day, step by step

What to run, when, and who runs it, from the night before to the end of the
day. The day-trade loop runs at most 3 times a day (`max_trades_per_day`).

> Education and tooling, not financial advice. Most day traders lose money.
> `"paper": true` (the default) means every step below is practice: you write
> the trade down instead of placing it. Keep it that way until a few weeks of
> paper days look sane next to your ICICIDirect chart.

Run everything from the repo folder (`DayTrader/`). Every file the tools
write lands in `trader/` there, and each step reads what the one before it
wrote. The night before a trading day, write that day's plan (picks,
cautions, anything unusual) to `trader/YYYY-MM-DD.md`, so the morning's
fresh Claude session starts from it (`CLAUDE.md` tells it to look).

## Who does what

| Who | What |
| --- | --- |
| **You**, in your own terminal | `fyers.py login` (PIN and TOTP in the browser), and nothing else secret |
| **You**, in the ICICIDirect app | place, change or cancel every order. Nothing in this pack can |
| **You**, in the Claude chat | pick the stock, say yes or no to each ticket, report what filled |
| **Claude**, in the chat | runs the tools, reads you the results, runs the alert loop |

Two ways to run any step, same result:

- **In Claude Code**: type the skill, e.g. `/trader-scanner orb`. Claude runs
  the tool and tells you the result in plain words. This is the normal way.
- **Yourself**: the `python ...` line shown next to each step.

## The day at a glance (India time)

| Time | Step | Skill | Live data? |
| --- | --- | --- | --- |
| Once a week | Refresh the stock list | `/trader-scanner universe` | no |
| Night before or by 8:45 | Pre-market scan, news | `/trader-scanner daily`, `/trader-news` | no (finished days) |
| **9:00** | **Morning guard: market open? logged in?** | `python scripts/morning_check.py` | no (reads the saved login only) |
| **9:00 to 9:10** | **Fyers login, then test it** | `fyers.py login` (you) | yes |
| 9:10 | Is the market open today? | `/trader-alerts clock` | no |
| 9:15 to 9:35 | Watch 1 or 2 picked stocks from the open (Route A) | `/trader-entry watch` | Fyers |
| 9:35 onward | Opening-range scan (Route B) | `/trader-scanner orb` | Fyers |
| On a trigger | Plan, replay, size, check, ticket, place | exit, timemachine, budget, risk, broker | Fyers quote |
| While a trade is open | Alerts every 3 minutes | `/loop 3m /trader-alerts check` | Fyers |
| **15:00** | No new entries after this (config) | | |
| **15:15** | Flat: close anything still open | `/trader-broker flatten` | |
| After 15:30 | The day's log | `/trader-broker log` | no |

## 0. Once: setup

1. `trader/config.json`: copy `trader-budget/config.example.json` there and
   check the numbers (`/trader-budget` walks you through them). The example:
   Rs 10,000, Rs 200 max loss a trade, Rs 500 a day, 3 trades a day, broker
   `icicidirect`, `"paper": true`.
2. Fyers: the app's redirect URL in the Fyers API dashboard is
   `http://127.0.0.1:8765/`, and `FYERS_APP_ID`, `FYERS_SECRET_ID`,
   `FYERS_REDIRECT_URI` are set with `setx` (done). Open a NEW terminal after
   any `setx`: an old one does not see the change.
3. The stock list: `/trader-scanner universe` (the Nifty 50), or
   `--index banknifty` for a list that scans in seconds.
   `python trader-scanner/scan.py universe --index nifty50`

## 1. Before the open (no login needed)

Finished days only, so Yahoo's delay does not matter here.

1. **Pre-market scan**: `/trader-scanner daily` finds daily-chart setups
   (20-day breakout, bull flag, reclaimed the 20-day average, oversold
   bounce) and writes `trader/watchlist.json`.
   `python trader-scanner/scan.py daily`
2. **The morning brief and the news** on what you might trade:
   `/trader-news` with the brief. It lists today's NSE results and board
   meetings for your stocks and the Nifty 50, the market's headlines (ET,
   Livemint, Moneycontrol), and each stock's own news. A results day, a board
   meeting or a big filing is a reason to skip a stock today.
   `python trader-news/news.py --events --market --watchlist trader/picks.json --hours 18`
   (run it again around 8:45 for the morning's headlines)
3. **Pick 1 or 2 stocks** to watch from the open (Route A below). Fewer is
   better: each needs your attention when it triggers.

## 2. 9:00 to 9:10: log in to Fyers (you, in your own terminal)

Step 0, at 9:00: run `python scripts/morning_check.py`. It prints one line:
`OK` (trading day, login good), `LOG IN TO FYERS NOW` (exit 2: run the login
below) or `MARKET CLOSED TODAY` (weekend or holiday, exit 0) or `MARKET CLOSED FOR THE DAY` (a trading day, run at 15:30 or later, exit 0). `CANNOT CHECK`
(exit 3) means the clock or `fyers.py status` did not answer: run them by
hand. Run after 9:30 it adds "late: the first entry is 9:35". It makes no
Fyers request and never logs in for you. A Fyers login that comes after
9:35 loses the opening entry window; this check is the guard.

```bash
python trader-entry/fyers.py login         # browser opens: Fyers ID, PIN, TOTP
python trader-entry/fyers.py status        # "logged in ... good until <tomorrow> 06:30 IST"
python trader-entry/fyers.py quote HCLTECH # the pre-open (9:00 to 9:08) already has a price
```

- After 6:30 AM, or the token dies at 6:30. 9:00 to 9:10 is best: if
  something is wrong you find out before the bell. The hard latest is before
  9:35, the first possible entry.
- Never paste the secret, the PIN, the TOTP or the token into the chat. If
  Claude says "no Fyers login today", this is the step to do.
- Without the login, every live step stops and says so. That is on purpose:
  nothing quietly falls back to Yahoo's delayed prices.

Then `/trader-alerts clock` (`python trader-alerts/alerts.py clock`): a
weekend or an NSE holiday ends the day here.

## 3. Find the entry: two routes

The opening range is 9:15 to 9:30. The entry is the first 5-minute bar after
it that CLOSES above the range high. The earliest is 9:35 (the 9:30 bar's
close).

**Route A, watch ahead (the better one)**: a stock you picked before the
open. Tell Claude: *"watch HCLTECH in the background"*. It runs

```bash
python trader-entry/entry.py watch HCLTECH --until 15:00
```

as a background job: one Fyers request just after each bar closes, one line
per bar, and it ends by itself on the trigger (it writes `trader/entry.json`)
or when the setup expires at 15:00. Claude is told the moment it ends, so you
hear about the trigger at the bar's close, not minutes later. Start it any
time from 9:10. Two stocks means two watches.

**Route B, scan at 9:35**: what in the whole list has already broken out.

```bash
python trader-scanner/scan.py orb          # /trader-scanner orb
```

The Nifty 50 takes about a minute (one Fyers request per stock, paced under
the limit). It writes the hits to `trader/watchlist.json`. Pick one, check its
news, then `/trader-entry check SYMBOL --write`. A hit from 9:35 that you
look at at 9:50 is a late entry: the price, the stop distance and the odds
have moved, and the entry tool says so.

## 4. On a trigger: from signal to ticket (a few minutes, in order)

Do these in one go, in this order. Each reads the file the last one wrote.
If anything blocks, stop: no trade is a fine outcome.

| # | Step | Command | Writes |
| --- | --- | --- | --- |
| 1 | Stop and target, BEFORE buying | `python trader-exit/exit.py plan --write` | `trader/plan.json` |
| 2 | Replay the rest of the day | `python trader-timemachine/timemachine.py run --write` | the odds |
| 3 | Fresh Fyers price | `python trader-alerts/alerts.py quote HCLTECH --write` | `trader/prices.json` |
| 4 | Size it | `python trader-budget/size.py --write` | `trader/orders.json` |
| 5 | Check every rule | `python trader-risk/check.py` | PASS or BLOCK |
| 6 | The ticket | `python trader-broker/ticket.py show` | READY or not |

- Step 1: the default stop is the opening-range middle, the target 2R. A 1R
  target does not clear the costs on a Rs 10,000 account.
  For the price-band warning, save NSE's security list once as
  `trader/sec_list.csv` and pass `--prev-close PRICE` (nothing downloads the
  list or writes the previous close for you yet). Without them the plan says
  "band unknown" once a day and carries on. A list saved before the latest
  trading day also gets a once-a-day note.
- Step 2: if it says the setup loses on its own history, that is a reason to
  skip. It is a simulation, not a promise.
- Step 3 before 4 and 5: sizing and the risk check use a price only if it is
  under 15 minutes old. A run-up since the trigger means a bigger risk, so
  fewer shares.
- Step 5 BLOCK: Claude says why (too far a stop, the daily limit, after
  15:00 ...). Do not edit the limits to make it pass.
- Step 6: Claude reads you the ticket. **You reply with a plain "yes" for
  that one order**, or "no". Claude records it with `ticket.py approve`.
  Nothing is sent anywhere.

## 5. Place it (you, in ICICIDirect)

1. Buy the quantity on the ticket, product **Intraday**, and put the stop
   loss and the target in, as the ticket says. If the two exits are separate
   orders, they are NOT linked: when one fills, cancel the other at once.
2. Tell Claude what happened: placed with the order id and the fill, or
   skipped, or rejected. It records it (`ticket.py result ...`), and that is
   what counts toward the day's 3 trades and Rs 500.
3. Paper mode: write it down instead, and report it the same way.

## 6. While it is open: the alert loop

```text
python trader-alerts/alerts.py add --from-plan   # the stop, the target, flat by 15:15
```

then in Claude Code:

```text
/loop 3m /trader-alerts check
```

- Every 3 minutes Claude runs `alerts.py check`: one Fyers request for all
  the symbols, and it tells you only what rang. Each alert rings once.
- A stop or target alert means the broker's order has probably filled: look
  at your positions in ICICIDirect, cancel the other exit if it is a separate
  order, and tell Claude the fill (`ticket.py fill --symbol HCLTECH --side
  sell --qty 5 --price 1399.00`).
- When the trade is closed, tell Claude to stop the loop.
- A loop runs only while this Claude Code session is open and the computer
  is awake: plugged in, sleep off. A check is one reading, so a fast price
  can pass a level between two checks. Your stop order at the broker is what
  protects you, not the alert.
- 3 minutes is plenty: about 115 requests in a day, against 4,500. Do not go
  under 1 minute.

## 7. 15:00 and 15:15

- **15:00**: no new entries (the risk check blocks them). A watch still
  running ends here by itself.
- **15:15**: the flat-by alert rings. If anything is still open:

```bash
python trader-broker/ticket.py flatten --symbol HCLTECH   # the sell ticket
python trader-risk/check.py                               # an exit always passes
python trader-broker/ticket.py show
```

  You say yes, cancel the open stop and target in ICICIDirect first, then
  sell, and report the fill. Out before the broker's own square-off (about
  15:20, for a fee).

## 8. After the close

- `/trader-broker log` (`python trader-broker/ticket.py log`): today's yes,
  no, placed and filled, each with its max loss. How much of the 3 trades and
  the Rs 500 you used is in every risk check's "today before this" line.
- Compare the first real contract note with the costs the pack estimated
  (`plan.md`, Next).

## What loops, and what never does

| Loop it | How | Why |
| --- | --- | --- |
| The entry watch | background job (Route A) | it wakes on each bar's close by itself |
| Alerts while a trade is open | `/loop 3m /trader-alerts check` | stop, target and 15:15, without staring at a chart |
| (fallback for the watch) | `/loop 5m /trader-entry check HCLTECH --write` | if a background job is not an option |

| Never loop or automate | Why |
| --- | --- |
| `fyers.py login` | your PIN and TOTP, in your terminal only |
| `ticket.py approve` | it needs your own yes, for one order, every time |
| placing orders | there is no broker connection for orders; you place every one |
| the scanner every few minutes | 50 requests a run; once at 9:35 (and maybe once at 10:00) is enough |

## Fyers' limits, in practice

The free plan allows 50 data requests a minute and 5,000 a day, and going over
the minute limit more than 3 times in a day blocks the account for the rest of
that day. `fyers.py` stops itself at 40 a minute and 4,500 a day, and after a
single "too many requests" it leaves Fyers alone until tomorrow.

A normal day: the 9:35 scan 50, two watches about 70 each up to 15:00, the
alert loop about 115, a few quotes: about 300 of 4,500. The only step that
comes near 40 a minute is the scan, and it waits for the next minute instead
of going over. `python trader-entry/fyers.py status` shows today's count.

## When something goes wrong

| It says | Do |
| --- | --- |
| "LOG IN TO FYERS NOW" (morning check), or "no Fyers login today" | log in (step 2), in your own terminal |
| "CANNOT CHECK" (morning check) | run `python trader-alerts/alerts.py clock` and `python trader-entry/fyers.py status` by hand and read what they say |
| "the Fyers login expired at 6:30 AM" | log in again: yesterday's token |
| "Fyers refused the login" | log in again; if it keeps happening, check the App ID in the dashboard |
| "Fyers said too many requests" | Fyers is off for today. Use the ICICIDirect app for prices; no new trades from the pack today |
| "Fyers unavailable (could not reach ...)" | your internet, or Fyers is down (status.fyers.in). The watch retries 5 times, then stops |
| "candles not on the NSE 5m grid" | Fyers sent data in a shape the tool does not trust. Tell Claude; do not trade off it |
| risk check BLOCK | the reason is the answer. Skip the trade or fix the plan, never the limits |

### The login itself

| What happens | Do |
| --- | --- |
| "set FYERS_REDIRECT_URI first" (or the APP_ID or SECRET) | the terminal was opened before `setx`: open a new one. Still missing: `setx` it again |
| the browser shows a Fyers error about the redirect URL | the URL in the dashboard and `FYERS_REDIRECT_URI` differ by a character (http, port, the closing `/`). Make them identical |
| "could not listen on 127.0.0.1:8765" | another program has the port. Pick another port (8766) in BOTH the dashboard and `FYERS_REDIRECT_URI`, new terminal |
| the browser does not open | open the address the login printed, by hand, in the same computer's browser |
| "no redirect came back in 5 minutes" | the login was not finished in time, or a firewall prompt was ignored: allow Python on private networks, run it again |
| "Fyers did not give a token" | the auth code was used or is old: run `login` again from the start |

### Data and tools

| What happens | Do |
| --- | --- |
| `/trader-scanner` etc. not found in Claude Code | the skills are copied in `.claude/skills/`: start Claude Code in the DayTrader folder. After a code change, re-copy them (README, Quick start) |
| the daily scan (Yahoo) fails | it is only the pre-market idea list: watch the stocks you already picked, or retry after a minute |
| "NSE announcements unavailable" | the headlines still come; for filings open nseindia.com in a browser. Do not work around the block |
| the Time Machine refuses a stock ("needs at least 20" full sessions) | a thinly traded stock has gaps in its 5-minute bars. There is no replay for it: decide without the odds, or skip it |
| bars missing in a watch on a thin stock | the stock did not trade in those minutes. The entry still needs a bar that CLOSES above the range high; a thin stock fills worse than the plan's prices |
| Claude hits its usage limit mid-trade | the `/loop` alerts stop with it. Your stop and target orders at ICICIDirect still work: check your positions there, and close by 15:15 yourself |
| the laptop slept | watches and loops paused. On waking they catch up late: check the time and your positions before acting on anything they say |

`--source yahoo` exists for practice and for replaying old days. Its output
says "delayed" on every line. Never use it for a live decision.
