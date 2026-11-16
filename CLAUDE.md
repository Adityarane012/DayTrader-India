# Day Trader India: handover for every new chat

Claude Code loads this file at the start of every chat in this folder. Read
it before doing anything. The detail lives in three other files:

- `plan.md`: every decision the user made, what is built, what real data
  showed, the costs, and **Next** (the open work, in order).
- `PIPELINE.md`: the trading day step by step (when to run what, who does
  what, what loops), and what to do when something breaks.
- `trader/YYYY-MM-DD.md` (kept out of git): the plan for one trading day,
  written the night before. Read today's if it exists.

## What this is

A hard fork of an open-source Claude skill pack (MIT, `UPSTREAM.md`), ported
to the NSE for day-trading **research and paper trading** on a small account
(Rs 10,000 in the example config). Nine skills in `trader-*/`, each a SKILL.md
plus standard-library Python. Education, not advice: most day traders lose
money.

**Private state lives elsewhere.** The user's own account, watch list, days
and decisions are in `CLAUDE.local.md` and `trader/private/` (both out of
git). Read them if they exist. Never copy their contents into a tracked file
or a commit message: this repo is meant to be published. Before any publish,
run `python scripts/leak_check.py`.

The chain: scanner -> news -> entry -> exit -> timemachine -> budget -> risk
-> broker, with alerts while a trade is open. Each step writes a file in
`trader/` that the next one reads.

## Rules that are not negotiable

- **Nothing places an order.** No broker order API, ever. The user places
  every trade by hand in their broker's app (ICICIDirect in the example
  config). `"paper": true` stays until the user
  changes it themselves in `trader/config.json`.
- **A ticket needs the user's own explicit yes, for that one order**, every
  time. Never take "ok", a yes for several orders, or a yes with a condition.
  Never run trader-broker from a background job or a loop.
- **Secrets never pass through the chat.** Never ask for, read, print or
  store the Fyers secret, PIN, TOTP or access token. Never run
  `fyers.py login` for the user: they run it in their own terminal. The
  token lives in `~/.day-trader-india/` and only the tools read it. Do not
  print environment variables that hold secrets.
- **Fyers is the only live price source.** No automatic fallback to Yahoo
  (its NSE data runs 15 to 30 minutes behind and its opening range is too
  narrow). `--source yahoo` only when the user asks, for practice or replays.
- **Go easy on Fyers.** Free plan: 50 data requests a minute, 5,000 a day;
  more than 3 per-minute overruns block the account for the day. It
  answered HTTP 429 to requests a third of a second apart, so `fyers.py`
  sends one a second, stops at 40 a minute and 4,500 a day, and after any
  429 stops itself for the day. Do not make Fyers calls just to look around.
  Never clear that stop without the user's say-so.
- **Unofficial sources (NSE, Yahoo, Google News, niftyindices.com)**: one
  polite request, plain user agent `Mozilla/5.0 (compatible;
  day-trader-india/0.1)`, no cookies or workarounds. If one refuses, say
  "<source> unavailable" and carry on. Never use obscura's stealth mode.
- **Ask, do not assume**, on anything that affects money, data or the
  user's account. The user decides; give an opinion and a recommendation.
  If a user choice looks risky (a thinly traded stock, more watches than
  they can follow), say so once, plainly, then respect the choice.

## Where things are

| Path | What |
| --- | --- |
| `trader-<skill>/` | SKILL.md + the tool. Self-contained: no shared module |
| `trader-alerts/fyers.py` | the Fyers login, quotes, candles and request pacing. **Identical copies** in `trader-entry/` and `trader-scanner/`; a test fails if they differ. Edit the alerts copy, then run `python scripts/sync_fyers.py` (it copies it over the other two and over the installed `.claude/skills/` copies; `--check` only reports) |
| `README.md`, `docs/GUIDE.md` | the short README (what, when, quick start) and the long guide (Fyers setup, worked example, fine print). A test pins the README's title, one-line description, upstream link, `## Fine print` heading and the nine `/trader-*` names |
| `docs/` | also `SCREENER_MCP.md` (the screener MCP spec) and `sec_list_format.md` (the price-band list contract) |
| `scripts/morning_check.py` | the 9:00 check: market open? Fyers login good? One line, no Fyers request |
| `scripts/sync_fyers.py` | copies the master `trader-alerts/fyers.py` over its copies (and the installed ones). Run it after every edit to the master |
| `scripts/make_public_snapshot.py` | builds the clean public repo as a NEW git repo with one commit by a GitHub noreply identity; runs the leak check before and after; never adds a remote or pushes |
| `scripts/leak_check.py` | before any publish: fails if a private term (from `trader/private/denylist.txt`) is in the tracked files or, with `--history`, in any commit message, change or non-noreply author email |
| `.claude/skills/` | the installed copy Claude Code loads (out of git). After any change to a skill, resync it (README, Quick start, step 2) or a test fails |
| `.claude/worktrees/` | scratch copies for parallel agents (out of git). The repo-wide tests skip it. Remove with `git worktree remove` when done |
| `trader/` | runtime files, out of git: `config.json`, `universe.txt`, `watchlist.json`, `picks.json`, `entry.json`, `plan.json`, `orders.json`, `prices.json`, `alerts.json`, `state/`, the day notes |
| `~/.day-trader-india/` | `fyers-token.json` (never open it) and `fyers-calls.json` (the request count and the stop flag) |
| `tests/` | `python -m unittest discover -s tests` (465 tests, about 25 s, offline; 1 slow counter test is skipped unless `DAYTRADER_SLOW_TESTS=1`, see `tests/test_fyers_counter.py`). Fixtures are real answers, dated in each test file's docstring, except `tests/fixtures/trader-exit/sec_list_sample.csv`, which is hand-made |

## Conventions

- Python 3.8 or newer, standard library only. Run it as `python` (Windows
  has no `python3`).
- NSE symbols as `RELIANCE.NS`; a bare one gets `.NS`. Fyers wants
  `NSE:RELIANCE-EQ`, and `M&M` must be URL-encoded as `M%26M`.
- India time (UTC+5:30, no DST) is worked out in the code, never from the
  computer's time zone. Session 9:15 to 15:30, opening range 9:15 to 9:30,
  entries 9:30 to 15:00, flat by 15:15. NSE holidays: 2026 only.
- Money in rupees with Indian grouping (Rs 1,00,000). Config keys end in
  `_inr`; a config with `_usd` keys is refused.
- Stops and targets round down to the NSE tick for the price.
- No em dashes anywhere in the repo (a test checks). Plain words in user
  output; say what is unknown or unverified.
- The identical "## Safety" block ends every SKILL.md (a test checks).
- Commits: the user's global rules (imperative subject, body says why and
  how it was verified). Commit as you go on `main`; never push unless asked.

## Traps in this environment

- **Shell heredocs mangle backslashes and quotes.** `\\n` has come out as a
  real newline and `\\s` as `\s`. For any Python with escapes, write the
  script to the scratchpad with the Write tool, then run it. Patch scripts
  should assert each replacement matches exactly once.
- Broad commands like `rm -rf` and env-var dumps get refused by the
  permission checker. Use narrow commands; do not try to get around a refusal.
- A Claude Code session started before a `setx` does not see the new
  variable. Only `fyers.py login` needs the `FYERS_*` variables; the other
  tools read the saved token.
- Windows sleep pauses background watches and `/loop`. They catch up late
  on waking.
- Live tool runs write into `trader/`. For a rehearsal, run from a scratch
  folder with its own `trader/` and `DAY_TRADER_INDIA_HOME` so the real
  state stays clean.

## Where things stand

(The user's own days, picks and results are in `CLAUDE.local.md`, not here.)

- Built and tested: all nine skills; Fyers-only live data; the morning
  brief (`news.py --events --market`); a full rehearsal on real data, entry
  to the 15:15 exit, matched to the paisa. 465 tests.
- Done: a lock around the shared Fyers request counter (all three `fyers.py`
  copies); requests paced by send time, not by when they were asked for;
  `budget()` retries a read that lands mid-swap; trader-entry writes
  `prev_close` into `entry.json` at a live trigger; `scripts/morning_check.py`
  (run at 9:00); the price-band warning in trader-exit (needs
  `trader/sec_list.csv` saved by hand); once-a-day notes for a missing or old
  band list. None of the counter and pacing changes has been seen in a live
  session yet.
- Known gaps, in `plan.md` section 5: nothing downloads `sec_list.csv` and the
  real file's layout is unverified; no real Fyers answers saved as fixtures;
  the Time Machine still uses Yahoo history; `fyers.py` is three copies.
- A personal screener.in MCP is being built separately (Option A: a
  pre-market filter; spec in `docs/SCREENER_MCP.md`, the band-list contract
  in `docs/sec_list_format.md`). It shares no code with the pack.
- Publishing: the local repo is never given a remote. A clean snapshot is
  published instead (see `CLAUDE.local.md`), after `scripts/leak_check.py`
  passes. Claude never pushes unless asked.
- Open work, in order: `plan.md`, section 5.

## Starting a session

0. At 9:00 IST on a trading day, before anything else: `python scripts/morning_check.py`
   (one line: OK, LOG IN TO FYERS NOW, or MARKET CLOSED TODAY; no Fyers request).
1. Read today's `trader/YYYY-MM-DD.md`, if there is one.
2. On a trading day, before anything live: `python trader-entry/fyers.py status`.
   If there is no login today, ask the user to run `login` in their terminal.
3. Follow `PIPELINE.md`. For code work, run the tests before and after, and
   resync `.claude/skills/` after changing a skill.
