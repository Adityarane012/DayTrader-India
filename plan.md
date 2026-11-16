# DayTrader India: decisions, status, next

A hard fork of Jake Schincariol's **Day Trader skill** for the Indian market
(NSE), following Bhupesh Thukral's video *"AI Trading in the Indian Stock
Market: Claude Day Trader Skill Setup"* (2026-10-31).

- Upstream: https://github.com/Jakeschincariol/day-trader-skill (see `UPSTREAM.md`)
- Video: https://www.youtube.com/watch?v=vZktd88MtTI

> Education and research tool. Not financial advice. Paper trade first. Most
> day traders lose money; nothing here changes that.

## 1. Decisions

| Topic | Decision |
|---|---|
| Approach | Hard fork, India only. Each skill folder is self-contained (no shared module) |
| Example account | Rs 10,000. Rs 200 max loss a trade, Rs 500 a day, 3 trades a day, 75 % position cap, 10 % cash buffer |
| Example broker | **ICICIDirect** (Prime 4999 plan). The user places every order; the pack never does |
| Costs | `icicidirect_prime_4999` preset: 0.01 % brokerage an order, plus the statutory charges in section 4 |
| Live data | **Fyers** API, free Standard plan (50 data requests a minute, 5,000 a day). App ID, secret and redirect URL are in the user's environment variables `FYERS_APP_ID`, `FYERS_SECRET_ID`, `FYERS_REDIRECT_URI`, never in the repo or the chat |
| Live-feed code | Standard library REST (`fyers.py`), not `fyers-apiv3` and no websocket: nothing to install, no third-party code holding the token, and one request per bar or per alert check is enough (user agreed 2026-11-15) |
| Fyers login | The user runs `fyers.py login` each trading day after 6:30 AM; PIN and TOTP in the browser; redirect `http://127.0.0.1:8765/` caught by the tool. Token in `~/.day-trader-india/`, outside the repo |
| Where live prices go | **Fyers only** (user, 2026-11-15: Yahoo's NSE data is 15 to 30 minutes behind). Entry timer, alerts and the 9:35 opening-range scan read Fyers and stop, saying why, when it cannot answer; no automatic Yahoo fallback. `--source yahoo` only when asked, for practice. Risk and budget warn about a Yahoo price but still count it, since it can only raise the risk. The pre-market daily scan and the Time Machine stay on Yahoo: finished days |
| Login time | After 6:30 AM; best 9:00 to 9:10 AM (the pre-open gives a quote to test with); at the latest before 9:35, the first possible entry |
| Universes | Nifty 50 (default), Bank Nifty, Nifty Next 50, Nifty 200, from the official lists |
| Session | IST. 09:15-15:30, opening range 09:15-09:30, entries 09:30-15:00, flat by 15:15 |
| Default target | 2R. A 1R target on a tight stop does not clear costs on this account |
| Unofficial endpoints | Yahoo and NSE get one polite request. If a source refuses, the tool says "<source> unavailable" and carries on. No workarounds |
| Circuit-band check | Skipped while trading only the Nifty 50 (no fixed bands). Many other stocks have a daily band of 2, 5, 10 or 20 %, so trader-exit warns when a stop or target is near the day's band (built, Next item 3) |
| Watch list | The user's own picks, kept in `trader/picks.json` (with company names for the news search), not only the scanner's hits. Which stocks are in it is private and is not recorded in this repo |
| Alerts while a trade is open | `/loop 3m /trader-alerts check`, chosen over a PowerShell loop that would use no Claude tokens. Upper estimate about 20 million tokens a day; the loop stops if Claude's usage limit is hit |
| Morning brief | Inside trader-news (`--events --market`), not a tenth skill (user, 2026-11-16). Results and board meetings, and market headlines. FII/DII figures, block deals and the RBI calendar were left out by the user for now |
| Skills in Claude Code | Copied into `.claude/skills/` (kept out of git). A repo test fails when a copy is stale; README, Quick start, has the resync line |
| Handover | `CLAUDE.md` (loaded by every new chat here) holds the context and the rules; a day's own plan goes in `trader/YYYY-MM-DD.md` |
| Python | Commands use `python`, not `python3` (Windows) |
| Git | Its own repo in `DayTrader/`, branch `main`, kept on the user's computer with no remote. A public copy is a clean snapshot made separately, after `scripts/leak_check.py` passes; the user creates the GitHub repo and pushes, Claude never pushes unless asked. The user's days, picks and results are private and live outside git (`CLAUDE.local.md`, `trader/`) |

## 2. What is built

Nine skills, all on NSE symbols, IST and rupees, with offline tests on real
data fetched 14 to 16 Nov 2026 (465 tests):

| Skill | What it does now |
|---|---|
| trader-scanner | Index universes; daily setups (Yahoo daily closes); opening-range breakouts on Fyers 5-minute bars |
| trader-news | NSE corporate announcements, Google News (India), Yahoo headlines, today's move; `--events` (NSE results and board meetings, today + 3 days) and `--market` (ET, Livemint, Moneycontrol headlines) for the morning brief |
| trader-entry | Bar-by-bar opening-range or level trigger, on Fyers bars |
| trader-exit | Stop and target on the NSE tick; flat by 15:15 |
| trader-timemachine | 10,000 replays to the flat-by, plus the rule on every past session |
| trader-budget | Sizes to the limits, with the round trip's costs in the loss and in reward:risk |
| trader-risk | PASS or BLOCK on the limits, costs, entry window, NSE order format |
| trader-broker | A ticket the user places in their broker's app; records the yes and the result |
| trader-alerts | Stop, target, flat-by and opening-bell alerts on the NSE clock; Fyers quotes |

Also built, 2026-11-16 evening:

- `scripts/morning_check.py`: the 9:00 check (market open? Fyers login good?),
  one line, no Fyers request. After 15:30 it says the market is closed.
- A lock around the Fyers request counter (all three `fyers.py` copies), after
  watches died on a file-swap race (item 9).
- The price-band warning in trader-exit, with once-a-day notes for a missing
  or old `trader/sec_list.csv` and a flag for a duplicate EQ row (item 3).
- `docs/`: this repo's long guide (`GUIDE.md`), the screener MCP spec
  (`SCREENER_MCP.md`) and the band-list contract (`sec_list_format.md`). The
  README is now short.

Removed from upstream: the Earnings Analyst and Pelosi Tracker (US-only data),
the 13F weights mode, the US pattern-day-trader check, the Alpaca connection.

The worked example (HCLTECH.NS, Fri 13 Nov 2026), reproduced by the tests:
entry 1384.60 at 9:35 AM, stop 1377.40, 2R target 1399.00, 5 shares
(Rs 6,923). Loss at the stop Rs 36 + Rs 4.08 costs = Rs 40.08; gain at the
target Rs 67.88; reward to risk 1.69 after costs. The Time Machine calls it
close to break-even, and on the 58 past sessions the setup fired 32 times:
2 target, 16 stop, 14 neither.

## 3. What the real data showed

- Yahoo's NSE 5-minute bars usually lack 15:15, 15:20 and 15:25, so no session
  has all 75 bars. The Time Machine needs bars only up to its flat-by.
- Yahoo sends 0 volume for the 9:15 bar (the opening auction is not in it).
- Yahoo's headline feed is nearly empty for NSE symbols, so news reads NSE's
  own announcements and Google News.
- Headlines carry the rupee sign, which crashed print() on a Windows console.
- The NSE tick schedule matched about 730,000 real prices with no exception,
  using each stock's previous month-end close.
- Fyers, first live run (2026-11-16, Friday's data): quotes for M&M and
  BAJAJ-AUTO resolve as `NSE:<SYMBOL>-EQ`; candles sit on the 5-minute grid,
  all 75 bars, with real volume at 9:15, and quiet minutes come back as flat
  zero-volume bars. Yahoo's 9:15 bar leaves out the opening trades, so its
  opening range is too narrow: HCLTECH's range high is 1385.00 on Fyers, not
  1381.00, and a breakout seen on Yahoo's bars did not happen on Fyers' bars.
- Fyers answered HTTP 429 to history requests a third of a second apart,
  inside its published 5 a second: requests are now one a second.
- Moneycontrol's RSS feeds stopped updating years ago; ET Markets and
  Livemint's are live.
- Costs decide small trades: a 1R target on the example makes Rs 31.90
  against Rs 40.08 lost (0.80), so it is refused.

## 4. Costs (rates checked 2026-11-14 on the brokers' and NSE's pages)

| Charge | Rate |
|---|---|
| Brokerage, ICICIDirect Prime 4999, intraday | 0.01 % an order |
| Brokerage, Dhan, intraday (other preset) | the lower of Rs 20 and 0.03 % an order |
| STT | 0.025 % of the sell value |
| NSE transaction charge | 0.00307 % of turnover |
| SEBI fee | Rs 10 a crore of turnover |
| Stamp duty | 0.003 % of the buy value |
| GST | 18 % on brokerage + transaction charge + SEBI fee |

Not verified: whether ICICIDirect applies a minimum brokerage per order on
the Prime plan. ICICIDirect's page lists only the 0.01 % rate; one third-party
review says there is no minimum. On Rs 7,000 orders a minimum would change the
numbers a lot, so check the first contract note against the pack's estimate.

## 5. Next

Status: everything built is tested offline (465 tests, one slow one opt-in)
and the whole chain was rehearsed on real data. Fyers has been used live
(quotes and 5-minute bars through the watches). The user's own paper days
and their results are private and are not recorded here.

1. **Paper days**: the brief, the 9:00 morning check and Fyers login, the
   watches, the 9:35 scan, any trigger through to a paper ticket, the alert
   loop, flat by 15:15. Check each trigger by hand against the broker's
   chart. Whatever looks wrong decides the order of the rest of this list.
   A Fyers login that comes after 9:35 loses the opening entry window, so
   `scripts/morning_check.py` at 9:00 is step 0 of the day.
2. **The Time Machine on Fyers history**: it still replays Yahoo's 60 days,
   whose opening ranges are too narrow (section 3), so its history likely
   counts breakouts that did not happen. The Standard plan has a year of
   intraday Fyers candles (about 60 requests a run, at one a second).
3. **Price bands** (done 2026-11-16): many stocks have daily bands of 2, 5,
   10 or 20 %. At a band trading can stop and a stop order may not fill. `exit.py plan` now warns when the stop or target is within
   `band_warn_pct` (config, default 1) of the day's limit, from NSE's
   security list saved as `trader/sec_list.csv` (Symbol, Series, Security
   Name, Band) and the previous close (`--prev-close` or `prev_close` in
   entry.json). The parser contract, shared with the screener MCP, is in
   `docs/sec_list_format.md`; the fixture is
   `tests/fixtures/trader-exit/sec_list_sample.csv` (hand-made).
   trader-entry now writes `prev_close` into `entry.json` at a live trigger
   (one extra Fyers quote). Still open: nothing downloads `sec_list.csv`, and
   the real NSE file's layout is unverified.
4. **Real Fyers answers as test fixtures**: save one real quotes and one real
   history answer (no token in either) in place of the docs' examples.
5. **The news "move" line on Fyers**: `news.py` still prices each stock's
   move from Yahoo; during the session that is the last Yahoo price shown.
6. **First real contract note**: compare its charges with the pack's
   estimate, including whether ICICIDirect has a minimum brokerage, and fix
   the preset if they differ.
7. **2027 NSE holiday list**: NSE publishes it in December; add it to the six
   tools that carry the calendar.
8. **Publishing** (the user's decision): the user creates the GitHub repo and
   pushes it themselves, from a clean snapshot, not from this repo's full
   history (which holds private notes in old commits). `.gitignore` is set
   (`trader/`, `CLAUDE.local.md`, secrets, scratch folders), the README is
   short and the long guide is `docs/GUIDE.md`. `scripts/leak_check.py` checks
   a folder or repo, and with `--history` every commit, for private terms (kept
   in a private file) and for any author email that is not a GitHub noreply
   address. The `homepage` and `repository` in `.claude-plugin/` still point at
   the upstream project and should be changed to the new repo. Never push
   without being told.
9. **Fyers request counter race** (found in live use): several
   `entry.py watch` processes wake at the same moment (bar close plus the
   fixed GRACE) and rewrite `~/.day-trader-india/fyers-calls.json` together.
   Windows refuses one `os.replace` (`PermissionError: WinError 32`) and
   that watch dies. **Fixed 2026-11-16**: every read-modify-write of the counter now runs under a
   lock file (`fyers-calls.json.lock`, made with `O_CREAT | O_EXCL`, stale
   after 120 s), and `os.replace` retries briefly on `PermissionError`, in
   all three copies. `tests/test_fyers_counter.py` runs 8 processes x 200
   counts per copy: the old code loses the race every time (7 of 8
   processes crash with WinError 32), the new code ends at exactly 1,600.
   Not yet seen in a live session.
10. **Screener MCP and a fundamentals filter (Option A, the user's
    decision)**: the user is building a personal screener.in MCP. Use it
    before the open only: wishlist or saved screen, then drop stocks that
    fail liquidity, price band, surveillance, results-date and pledge
    checks, run `scan.py daily` on the rest, and write `trader/picks.json`
    with a short dated fundamentals note per stock. Stops, targets and size
    stay rule-based from price action. Until the MCP exists the picks are
    chosen by hand or from the evening-before news.
11. **Swing or delivery mode (Option B)**: parked until the move to a UI or
    website. It needs daily-chart stops, overnight gap and delivery cost
    rules, and a new config section. Not before several paper days on
    Option A.
12. **`fyers.py` is three copies** (decided: keep three, add a sync script):
    it is copied into `trader-alerts/` (the master), `trader-entry/` and
    `trader-scanner/` so each skill folder works on its own, and a test keeps
    them identical. `python scripts/sync_fyers.py` now copies the master over
    the others and over the installed `.claude/skills/` copies; `--check`
    only reports. One shared module was rejected: it would stop a skill
    folder working when copied alone.
13. **Request pacing by send time** (fixed 2026-11-16, not yet seen in a live
    session): `_spend` used to record the time a call was asked for and then
    sleep, so two requests could leave well under a second apart (about 0.3 s
    in a hand-traced case), the spacing that drew an HTTP 429. It now
    reserves the next slot under the lock (`slot = max(now, last slot +
    MIN_GAP)`, records the slot), releases the lock, then sleeps until the
    slot, so the lock is held for milliseconds and a scan waiting for the
    minute cap cannot hold up the watches. Tests: `SlotReservation` in
    `tests/test_fyers.py`.
14. **`budget()` reads the counter without the lock** (fixed 2026-11-16): a
    read that lands mid-swap used to come back empty and show 0; it now
    retries briefly (not by taking the lock, which can be held for a while).
15. **Download the price-band list**: nothing downloads NSE's `sec_list.csv`,
    so the band warning needs `trader/sec_list.csv` saved by hand. The real
    file's column layout is still unverified: save one real copy and run the
    parser on it first. (`prev_close` is now written by trader-entry.)

Later, if wanted: FII/DII provisional figures and block and bulk deals in the
brief, an RBI policy calendar, an earnings analyst on Indian quarterly
results, a scheduled pre-market run.

## 6. Non-goals

- No auto-trading. No order is placed by the pack, and no ticket is ready
  without trader-risk's PASS and an explicit yes
- No F&O, no shorting, no MIS leverage by default
- No scalping: even with a live feed the setups are 1-minute and 5-minute bars
