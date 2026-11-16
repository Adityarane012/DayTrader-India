# Day Trader India

9 Claude skills for day trading on the NSE: scan the Nifty charts, track breaking news, time every entry and exit, and replay every outcome before you risk a rupee.

> Education and research, not financial advice. Most day traders lose money.
> It starts in **paper mode** and **never places an order**: you place every
> trade yourself, by hand, in your broker's app.

Built for a small account (the example is Rs 10,000), the NSE, India time and
rupees. A fork of Jake Schincariol's
[Day Trader skill](https://github.com/Jakeschincariol/day-trader-skill) (MIT).
Everything is plain Python 3.8+ with nothing to install.

## What it does

One trade passes through the skills in order. Each reads the file the last one
wrote (in a `trader/` folder) and writes its own.

```
scanner -> news -> entry -> exit -> timemachine -> budget -> risk -> broker
   find     read   when to  stop &   replay the    how many  check   a ticket
  setups    news    get in  target    odds          shares   limits  for YOU
                          alerts ring while the trade is open
```

If the risk check says **BLOCK**, you do not trade. No trade is a fine day.

## When to use it: a trading day

India time. Full steps in [`PIPELINE.md`](PIPELINE.md).

| When | What | Command |
| --- | --- | --- |
| Evening before, or about 8:45 | Find setups, read the news | `/trader-scanner daily`, `/trader-news` |
| **9:00** | Is the market open? Are you logged in to Fyers? | `python scripts/morning_check.py` |
| 9:00 to 9:10 | Log in to Fyers, in your own terminal | `python trader-entry/fyers.py login` |
| 9:15 to 15:00 | Watch your picks for a breakout | `/trader-entry` (watch), or `/trader-scanner orb` at 9:35 |
| A stock triggers | Plan, replay, size, check, ticket | `/trader-exit`, `/trader-timemachine`, `/trader-budget`, `/trader-risk`, `/trader-broker` |
| Trade is open | Stop, target and 15:15 alerts | `/loop 3m /trader-alerts check` |
| **15:15** | Be flat | `/trader-broker flatten` |
| After 15:30 | The day's log | `/trader-broker log` |

**Do not use it** on a weekend or NSE holiday, without that day's Fyers login
(live steps stop on purpose and never fall back to delayed prices), or on a
stock with results or a board meeting today.

## Quick start

You need Python 3.8+, [Claude Code](https://claude.com/claude-code), and for
live prices a free Fyers API app.

1. **Get it and open it in Claude Code.**
   ```bash
   git clone <this repo> day-trader-india && cd day-trader-india
   ```
2. **Install the skills** (Git Bash; use `python`, not `python3`, on Windows):
   ```bash
   mkdir -p .claude/skills
   for d in trader-*; do find "$d" -type f ! -path "*__pycache__*" -exec cp --parents {} .claude/skills/ \; ; done
   ```
   Run this again after changing any skill; a test checks the copy is current.
3. **Set your limits.** Copy `trader-budget/config.example.json` to
   `trader/config.json` and edit the numbers. Keep `"paper": true` until you
   have a few paper days you trust.
4. **Live prices (Fyers).** Create an app in the Fyers API dashboard, set
   `FYERS_APP_ID`, `FYERS_SECRET_ID` and `FYERS_REDIRECT_URI`, then log in
   each trading day after 6:30 AM. Details: [`docs/GUIDE.md`](docs/GUIDE.md).
   The login, PIN and secret never go in the chat.
5. **Try it:** `python scripts/morning_check.py`, then ask Claude
   "start the trading day".

## The nine skills

| Command | Job |
| --- | --- |
| `/trader-scanner` | Scan the Nifty for setups: opening-range breakouts, flags, bounces |
| `/trader-news` | NSE filings and headlines for your stocks; the morning brief |
| `/trader-entry` | Watch a setup bar by bar and say when to get in |
| `/trader-exit` | Stop and target before you enter; flat by 15:15; price-band warning |
| `/trader-timemachine` | Replay the rest of the day 10,000 times, plus past days |
| `/trader-budget` | Size the position to your budget and max loss, costs included |
| `/trader-risk` | Check every trade against your limits |
| `/trader-broker` | A ticket you place yourself; records your yes and the result |
| `/trader-alerts` | Ring on a stop, a target, 15:15 or the opening bell |

## The rules it keeps

- **Nothing places an order.** The ticket needs your own "yes", for that one order.
- **Paper first.** `"paper": true` is the default.
- **Live prices come from Fyers only**, never silently from delayed Yahoo data.
- **Secrets stay out of the chat**, the repo and the logs.
- **Your limits come from `trader/config.json`**, never from the code.

## Where things are

| Path | What |
| --- | --- |
| `trader-*/` | The nine skills: a `SKILL.md` plus the Python tool |
| `trader/` | Your runtime files (config, picks, plans). Not in git |
| `scripts/` | `morning_check.py` (the 9:00 check) and developer helpers: `sync_fyers.py`, `leak_check.py`, `make_public_snapshot.py` |
| `PIPELINE.md` | The trading day step by step, and what to do when it breaks |
| `docs/GUIDE.md` | The long guide: Fyers setup, a worked example, every command |
| `plan.md` | Decisions, what is built, what is next |
| `CLAUDE.md` | Handover for new Claude chats in this folder |
| `docs/` | Also the screener MCP spec and the `sec_list.csv` format |

## Tests

```bash
python -m unittest discover -s tests          # offline, about 30 seconds
DAYTRADER_SLOW_TESTS=1 python -m unittest discover -s tests -p "test_fyers_counter.py"   # the slow one
```

## Fine print

**Not financial advice.** This software reads public data and does arithmetic.
It does not know your situation and cannot see the future. You can lose money.
Talk to a SEBI-registered adviser if you need advice.

**A stop is a plan, not a guarantee.** In a fast market or across a gap a stop
can fill well past its price. Cost figures are estimates; your contract note is
the truth. The Time Machine is a simulation, not a prediction.

**The free data is unofficial** (Yahoo, NSE, Google News) and can be late,
incomplete or refuse requests; the tools then say so and carry on. Fyers prices
are polled, not streamed. Intraday gains are taxable business income in India;
nothing here is tax advice. More in [`docs/GUIDE.md`](docs/GUIDE.md).

MIT licence. Upstream by [Jake Schincariol](https://opusjake.ai).
