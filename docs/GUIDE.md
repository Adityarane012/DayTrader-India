# Day Trader India: the full guide

The long version of the [README](../README.md): what changed from upstream, the
Fyers setup, a worked example with real numbers, every command and the fine
print. Start with the README; come here for the detail.

9 Claude skills for day trading on the NSE: scan the Nifty charts, track breaking news, time every entry and exit, and replay every outcome before you risk a rupee.

A hard fork of Jake Schincariol's
[Day Trader skill](https://github.com/Jakeschincariol/day-trader-skill) (MIT)
for the Indian market. `plan.md` records the decisions, what is built and what is
next; `PIPELINE.md` is the trading day step by step; `CLAUDE.md` is the
handover every new Claude chat in this folder reads first; `UPSTREAM.md` the
upstream commit it started from.

The tools are plain standard-library Python (3.8 or newer, nothing to pip
install). Live prices (the entry timer, the alerts, the 9:35 opening-range
scan) come from your own free Fyers API app and nowhere else: Yahoo's NSE
data runs 15 to 30 minutes behind (see "Live prices with Fyers" below).
Finished days and the news come from free public data: Yahoo Finance daily
closes and 60-day history, NSE's corporate announcements, Google News and
the official index lists at niftyindices.com.

What changed from upstream, in short:

- **NSE symbols**: `RELIANCE.NS`, `M&M.NS`, `BAJAJ-AUTO.NS` (a bare `RELIANCE`
  gets the `.NS`). Upstream turned every `.NS` into `-NS`, which Yahoo does
  not know, and its risk check only took 1 to 5 letters.
- **India time**: IST (UTC+5:30, no daylight saving), the 9:15 to 15:30
  session, the 2026 NSE holiday list, no early closes. The opening range is
  9:15 to 9:30; no new entries after 15:00; every day trade flat by 15:15,
  before your broker's auto square-off.
- **Costs and ticks**: every size and every risk check counts the round
  trip's charges (brokerage, STT, exchange and SEBI fees, stamp duty, GST),
  and stops and targets land on the NSE tick for the price.
- **Rupees**: the config is in rupees (`max_loss_per_trade_inr` ...), with
  Indian digit grouping (Rs 1,00,000). A config with upstream's dollar keys is
  refused, so a dollar number is never read as rupees.
- **The Nifty**: the scanner scans the Nifty 50, Bank Nifty, Nifty Next 50 or
  Nifty 200 from the official lists.
- **News that exists**: Yahoo's headline feed is nearly empty for NSE
  symbols, so the news monitor reads NSE's own announcements and Google News.
- **Live prices from Fyers**: the entry timer, the alerts and the
  opening-range scan read your own Fyers login. Without a login that day, or
  when Fyers cannot answer, they stop and say why; they never switch to
  Yahoo's delayed data on their own.
- **You place the trade**: there is no Indian broker connection for orders. The last
  skill gives you a ticket and the steps for your broker's app (ICICIDirect
  in the example config), and records what you did.
- **Removed**: the Earnings Analyst and the Pelosi Tracker (US-only sources),
  the 13F weights mode, the US pattern-day-trader check.

## Install

In Claude Code, copy the skill folders into your skills folder:

```bash
git clone <this repo> day-trader-india
cp -r day-trader-india/trader-* ~/.claude/skills/
```

Or project-local: copy the same folders into your repo's `.claude/skills/`.
In this repo that copy is kept out of git; after any change to a skill,
refresh it from the repo folder (Git Bash) and the tests check it matches:

```bash
for d in trader-*; do find "$d" -type f ! -path "*__pycache__*" -exec cp --parents {} .claude/skills/ \; ; done
```
On Windows the commands use `python` (the python.org installer does not put
`python3` on the PATH). Then copy `trader-budget/config.example.json` to
`trader/config.json` in your project and set your own numbers.

## Live prices with Fyers

Needed for anything live. Without today's login the entry timer, the
alerts' price checks and the opening-range scan stop and tell you to log in.
`--source yahoo` runs them on Yahoo's delayed data, for practice only.

1. Create an app in the Fyers API dashboard
   (fyers.in/web/api-dashboard/user-apps) with the Market Data permission and
   the redirect URL `http://127.0.0.1:8765/`.
2. In your own terminal (Windows), then open a new one:
   ```
   setx FYERS_APP_ID "your app id"
   setx FYERS_SECRET_ID "your secret id"
   setx FYERS_REDIRECT_URI "http://127.0.0.1:8765/"
   ```
   The secret goes there, never in a chat.
3. Each trading day after 6:30 AM (Fyers tokens expire then), best between
   9:00 and 9:10 AM, and at the latest before 9:35 (the first possible
   entry): `python trader-entry/fyers.py login`. Your browser opens Fyers' login;
   your PIN and TOTP go there. The tool catches the redirect itself and saves
   the day's token in `~/.day-trader-india/`, outside the repo.
   `fyers.py status` says until when.

`fyers.py` reads prices only: no order, funds or holdings call. It keeps
itself under the free plan's limits (stops at 40 requests a minute and 4,500
a day; Fyers' limits are 50 and 5,000), and after a "too many requests" it
leaves Fyers alone for the day. The opening-range scan waits for the next
minute instead, so the Nifty 50 takes about a minute. The same file sits in
`trader-entry`, `trader-alerts` and `trader-scanner` (a test keeps them
identical). The pre-market scan, the news monitor and the Time Machine use
finished days, so they stay on the free sources.

## The nine

| command | job | what it does |
| --- | --- | --- |
| `/trader-scanner` | Chart Scanner | Scans the Nifty 50, Bank Nifty, Nifty Next 50 or Nifty 200 for setups: opening-range breakouts, flags, oversold bounces. |
| `/trader-news` | News Monitor | NSE announcements and Google News for every stock you watch, and what moves it; before the open, today's results and board meetings and the market's headlines (ET, Livemint, Moneycontrol). |
| `/trader-entry` | Entry Timer | Watches a setup bar by bar and tells you the moment to get in. |
| `/trader-exit` | Exit Planner | Sets your stop and your target before you enter, and gets you flat by 15:15. |
| `/trader-timemachine` | Time Machine | Replays the rest of the session 10,000 times from the stock's own recent bars, plus every past day the setup fired. |
| `/trader-budget` | Budget Manager | Sizes every position to your budget and your max loss per trade, in rupees. |
| `/trader-risk` | Risk Manager | Checks every trade against your limits and stops anything over them. |
| `/trader-broker` | Order Ticket | Turns a passed order into a ticket you place yourself in your broker's app. It never places an order. |
| `/trader-alerts` | Price Alerts | Rings when a price, a stop, the 15:15 flat-by or the 9:15 opening bell hits. |

## How to use it

**The whole trading day, step by step (what to run, when, who runs it, and
what to loop): [`PIPELINE.md`](../PIPELINE.md).**

Everything lands in a `trader/` folder in your project, and each skill reads
what the last one wrote:

```
scanner -> news -> entry -> exit -> timemachine -> budget -> risk -> broker   (one trade)
alerts: stop, target, flat by 15:15                                           (while it is open)
news                                                                          (on a schedule)
```

An example: HCLTECH, Friday 13 November 2026, real data.

1. **`/trader-scanner`** at 9:35 AM IST: of the Nifty 50, 13 had closed above
   their 15-minute opening range. HCLTECH.NS is one: range 1373.80 to
   1381.00, the 9:30 bar closed at 1384.60, 0.26 % over the top.
2. **`/trader-news`**: NSE's announcements for HCLTECH and the Google News
   headlines, newest first. That week's NSE filings were routine (a copy of a
   newspaper publication, general updates), and an intraday trade is out by
   15:15 anyway.
3. **`/trader-entry`** watched HCLTECH bar by bar. At 9:34 it said waiting
   (the 9:30 bar was still forming). At 9:35 it said triggered: the 9:30 bar
   (bar 3) closed above the range high, at 1384.60.
4. **`/trader-exit`**: the stop at the opening-range midpoint, 1377.40, so
   7.20 a share at risk; target two times that risk, 1399.00, both on the
   Rs 0.10 tick; flat by 15:15 either way.
5. **`/trader-timemachine`** replayed the rest of the day to 15:15 10,000
   times, each 5-minute bar drawn from HCLTECH's own bars at that time of day
   over the previous 58 sessions (seed 19, so anyone can repeat it): target
   first 27.0 %, stop first 67.8 %, still open at 15:15 5.2 %. A 2R target
   breaks even at 33 % of the trades that hit one side; this one got 28 %.
   It also re-ran the same rule on those 58 real sessions: it fired 32
   times, 2 hit the target, 16 the stop, 14 neither. Its verdict: close to
   break-even, and the history is worse. That is the point of looking before
   you risk a rupee.
6. **`/trader-budget`** with a Rs 10,000 account and a Rs 200 max loss per
   trade: the 75 % position cap allows 5 shares (Rs 6,923). At the stop that
   is 5 x 7.20 = Rs 36, plus about Rs 4.08 of costs (brokerage, STT, exchange
   charges, stamp duty, GST): Rs 40.08. At the target it makes Rs 72 minus
   Rs 4.12 = Rs 67.88, so reward to risk is 1.69 after costs, not 2. It
   writes one bracket order: buy 5 HCLTECH, stop-loss 1377.40, take-profit
   1399.00.
7. **`/trader-risk`** checks it against your limits: the max loss with costs,
   the daily loss limit, trades per day, reward to risk after costs, the
   entry window (9:30 to 15:00), position size and cash. PASS or BLOCK, with
   the reason.
8. **`/trader-broker`** shows you the ticket in plain words and the steps:
   in ICICIDirect, buy 5 HCLTECH (NSE), product Intraday, with target
   1399.00 and stop loss 1377.40, and a warning that two separate exit orders
   are not linked. You type yes for that exact order, place it yourself, and
   tell it the order id and the fill.
9. **`/trader-alerts`** rings on the stop, the target and at 15:15 to flatten
   whatever is still open.

### On a Rs 10,000 account

The example config is a Rs 10,000 account risking at most Rs 200 a trade and
Rs 500 a day, with ICICIDirect Prime 4999 charges. At that size the 75 %
position cap decides every trade (about Rs 7,000 of stock), and costs still
bite: about Rs 4.12 for the round trip above, a ninth of the Rs 36 at risk. A
1R target on the same trade (1391.80) makes Rs 31.90 against Rs 40.08 lost
after costs, reward to risk 0.80, and the pack refuses it. Tight targets on a small
account mostly feed the costs; the pack shows the number after costs so you
see that before you trade, not on the contract note.

## The tools

All standard-library Python. The data tools read public endpoints and are
polite about it.

```bash
python trader-scanner/scan.py universe --index nifty50                # the Nifty 50 (or banknifty, niftynext50, nifty200)
python trader-scanner/scan.py daily                                   # pre-market setups
python trader-scanner/scan.py orb --at 09:35                          # opening-range breakouts so far
python trader-news/news.py --symbols HCLTECH --hours 12               # NSE filings, headlines, today's move
python trader-news/news.py --events --market                          # today's results + market headlines
python trader-entry/entry.py check HCLTECH --setup orb                # waiting / triggered / expired
python trader-entry/entry.py watch HCLTECH --every 30                 # bar by bar until it triggers
python trader-exit/exit.py plan --stop or-mid --target 2R --write     # -> trader/plan.json
python trader-timemachine/timemachine.py run --write                  # 10,000 replays + the history
python trader-budget/size.py --write                                  # -> trader/orders.json
python trader-risk/check.py                                           # PASS / BLOCK per order
python trader-broker/ticket.py show                                   # the tickets, READY or not
python trader-alerts/alerts.py add --from-plan                        # stop, target, flat by 15:15
python trader-alerts/alerts.py check                                  # rings what hit, once
```

```bash
python -m unittest discover -s tests -v
```

The Fyers tests use the example answers printed in Fyers' docs and the real
HCLTECH bars recast as Fyers candles; no test talks to Fyers or sees a real
login.

The tests run offline, on fixtures cut from real data fetched 14 to 16 November
2026: HCLTECH's 5-minute bars for the 60 days to 13 November, the Nifty 50's
5-minute charts that day and their daily closes, the official index lists,
NSE announcements, Google News and Yahoo answers. They reproduce every number
in the example above, and the scanner's and the Time Machine's history
results are checked against a second, independent count in the tests.

## Fine print

**Not financial advice.** This is software that reads public data and does
arithmetic. It does not know your situation and it cannot see the future.
Most people who day trade lose money. You can lose money. Decide for
yourself, and talk to a SEBI-registered adviser if you need advice.

**Nothing in this pack places an order.** `/trader-broker` shows a ticket
only after `/trader-risk` passes that exact order and you type yes for it in
the chat. You place it yourself, in your own broker's app. No F&O, margin
(MIS leverage) or short selling unless you turn them on.

**Paper first.** `"paper": true` is the default in `config.example.json`: the
tickets say "practice: write it down, do not place it". Broker logins, PINs,
OTPs and API keys never go in the chat.

**The Time Machine is a simulation, not a prediction.** It is built from the
stock's own last 60 days of 5-minute bars. The future can do things those 60
days never did: a results day, a circuit, a headline. Treat its odds as a
reality check, never as a promise.

**A stop is a plan, not a guarantee.** In a fast market or across a gap, a
stop order can fill well past its price. The max loss shown is the loss at
the stop price plus the round trip's estimated costs. The cost rates are the
published ones as of 2026-11-14; your contract note is the truth.

**Fyers prices are a reading, not a guarantee.** The entry timer, the
alerts and the opening-range scan read Fyers' bars and quotes, polled, not streamed:
a price can pass a level between two checks. Fyers' answers here were built
from its published docs; check the first live day against your broker's
chart.

**The free data is unofficial.** Yahoo Finance's chart endpoint is not an
official API: it runs 15 to 30 minutes behind on the NSE, can change or rate-limit you, and it gives 1-minute or
5-minute bars, not every trade, with gaps (its NSE data usually lacks the
15:15 to 15:25 bars, and the 9:15 bar has no volume). NSE's announcements
endpoint is unofficial and sometimes refuses automated requests: the news
monitor then says "NSE announcements unavailable" and goes on with the
headlines. Not for scalping. Check anything that matters against your broker
before you act on it.

**Taxes.** Intraday equity gains are speculative business income in India.
Nothing here is tax advice.

## Files

```
trader-scanner/     SKILL.md, scan.py, universes/ (official Nifty index lists)
trader-news/        SKILL.md, news.py
trader-entry/       SKILL.md, entry.py, fyers.py (Fyers login and prices; same file as in trader-alerts)
trader-exit/        SKILL.md, exit.py
trader-timemachine/ SKILL.md, timemachine.py
trader-risk/        SKILL.md, check.py
trader-budget/      SKILL.md, size.py, config.example.json
trader-broker/      SKILL.md, ticket.py
trader-alerts/      SKILL.md, alerts.py, fyers.py, alerts.example.json
                    (fyers.py also in trader-scanner, for the opening-range scan)
tests/              unittest suite + offline fixtures
CLAUDE.md           the handover for new Claude chats: the rules, the layout, the traps, where things stand
PIPELINE.md         the trading day step by step: when to run what, and what to loop
plan.md             decisions, status and what is next; UPSTREAM.md the upstream record
```

MIT. Upstream by [Jake Schincariol](https://opusjake.ai).
