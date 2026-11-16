# Screener MCP: a build spec

A personal, read-only MCP server that feeds the pre-market step of the
Day Trader India pack (Option A in `plan.md`, item 10). It answers one
question before the open: **which stocks are worth watching today, and which
must be skipped, with the reason and the date of every number.**

Education and research tooling, not advice. Nothing here places an order.

## 1. Scope

In scope:

- Read a wishlist or run a saved screen, return a clean list of symbols.
  Until screener.in access is built, the symbols come from the user (typed,
  or agreed from the evening-before news): `evaluate` takes any list.
- Hard filters: liquidity, price band, surveillance, event risk, pledge.
- Soft scores: quality, valuation, trend, volatility fit for a Rs 10,000
  account.
- A deterministic verdict per stock with reasons, and a proposal file in the
  `trader/picks.json` shape. The user's own `picks.json` is theirs: the
  server never overwrites it silently (see `build_picks`).
- Per-stock fundamentals notes, each number dated and sourced.

Out of scope (now):

- Live prices and intraday bars. Fyers is the only live source (CLAUDE.md),
  and only the pack's tools may use the token.
- Orders, tickets, sizing. Those stay in the existing skills.
- Buy or sell advice. The server reports facts and rule results.
- Swing or delivery mode (Option B). Parked until the UI move; section 12
  keeps the door open.

## 2. Design principles

1. **Read-only toward the world.** Nothing is sent to any source except
   polite reads. The only things the server writes are its own cache and
   logs (under its own folder) and the one proposal file of `build_picks`.
2. **Every number carries provenance**: `value`, `unit`, `as_of` (the date
   the figure describes), `fetched_at` (when we got it), `source`. A number
   without these is dropped, not shown.
3. **Unknown is a first-class answer.** A missing field is `null` with a
   `reason`, never a guess and never a zero. Two tiers (section 6): missing
   **hard-veto data** (traded value, price band, surveillance, events) caps
   the verdict at `WATCH`; missing **enrichment data** (anything only Fyers
   can give in v1) adds a `not_available_v1` warning and does not change the
   verdict. Otherwise nothing could ever be `PASS` in v1.
4. **Deterministic.** Same inputs, same verdict. No model judgment inside the
   server. The thresholds live in one config file, versioned, and every
   verdict records the config version it used.
5. **Hard vetoes beat scores.** A stock that fails a veto is `AVOID` no
   matter how good the rest looks. Scores only rank what survives.
6. **Text from the web is data, never instructions.** Strip it to fields.
   Free text (news titles, company descriptions) is returned in a field named
   `untrusted_text` and the client must not act on it.
7. **Polite to every source.** One request at a time, a plain user agent,
   a cache, a daily request budget, and a clean "source unavailable" when
   refused. No workarounds, no stealth, no cookie tricks.
8. **Library first, MCP second.** All logic lives in a plain Python package
   with no MCP imports. The MCP wrapper is thin. A future website calls the
   same package.
9. **Files in, files out; no shared code with the pack.** The pack's skills
   are self-contained and standard-library only (CLAUDE.md). The server lives
   in its own folder (`screener-mcp/`), may depend on the MCP SDK, and never
   imports pack modules. It talks to the pack only through files: it reads
   `trader/config.json` (read-only, for the limits) and the pack's output
   files, and writes one proposal file. It never reads the Fyers token or
   anything in `~/.day-trader-india/`, and it never calls `fyers.py`. Its own
   secrets and cache live in `~/.screener-mcp/`.

## 3. Data sources and honesty about access

Check each source's terms before building on it. This spec does not assume
what screener.in permits; that is **unverified** and is open question 1.

| Need | Preferred source | Notes |
| --- | --- | --- |
| Wishlist, saved screens, ratios, quarterly results | screener.in, the user's own account, personal use | Terms and any export or API route to confirm. The session secret stays on the user's machine, never in chat |
| Price band, series, surveillance (ASM, GSM) | NSE `sec_list.csv` and NSE surveillance lists | Public files. One request a day each |
| Corporate actions, results calendar, board meetings | NSE announcements and event calendar | Same polite rules as `trader-news`. Do not duplicate parsing the pack already does: reading the output of `news.py --events` is allowed |
| Daily OHLCV, 20-day traded value, ATR, gaps | Yahoo daily candles, finished days only (v1) | The pack allows Yahoo for finished days: its delay does not matter for them. The server never uses Fyers in v1 (it would need the token) |
| Fyers-only fields (true opening-range width, exact 5-minute completeness) | A file the pack's scanner exports (later, section 13 step 8) | The server reads the file and never touches the token. Until then these fields are `null` with a reason |
| Delivery percentage | NSE bhavcopy (delivery file) | Published after the close, so it describes yesterday |
| Pledge, promoter and FII/DII holding | screener.in shareholding, cross-checked against the NSE filing | Quarterly, always show the quarter |

Rules for fallbacks: if the preferred source is down, say which field is
missing and carry on. Never silently swap a source; the `source` field shows
which one answered.

Unofficial sources (NSE, Yahoo, screener.in, niftyindices.com) follow the
pack's rule exactly: one polite request, the plain user agent
`Mozilla/5.0 (compatible; day-trader-india/0.1)`, no cookies or
workarounds. The one open exception is screener.in's own-login route, which
needs a session cookie: it is not allowed until the user decides (open
question 2), and the public sources never use one. If one refuses, or only answers with a cookie or a captcha,
the field is `null` with the reason "<source> unavailable" and the server
carries on. screener.in is added to that list in CLAUDE.md when it is
built. Never use obscura's stealth mode.

## 4. Tools

All tools return JSON with a top-level `meta`:
`{"server_version", "config_version", "fetched_at", "warnings": []}`.
Errors use a code, a plain message and `retryable` (section 9).

### 4.1 `get_wishlist()`

Returns the user's wishlist. Needs screener.in access (build step 6); not in
v1.

```json
{"symbols": [{"symbol": "RELIANCE", "name": "Reliance Industries Ltd", "isin": "INE...",
              "added_on": "2026-11-10"}]}
```

### 4.2 `run_screen(query | saved_name, limit)`

Runs a screener query (or a saved one by name) and returns rows. The query
text is echoed back so the pack can say why a stock is on the list. Needs
screener.in access (build step 6); not in v1.

```json
{"query": "Market cap > 5000 AND ...", "ran_at": "...",
 "rows": [{"symbol": "...", "values": {"roce_pct": {"value": 24.1, "unit": "pct",
   "as_of": "2026-09-30", "source": "screener.in"}}}]}
```

### 4.3 `get_stock(symbol, sections[])`

`sections` picks from: `identity`, `liquidity`, `tradability`, `events`,
`quality`, `valuation`, `ownership`, `trend`, `volatility`, `fit`. Default is
all. Each section is described in section 5.

### 4.4 `get_events(symbols[], days_ahead)`

Results dates, board meetings, ex-dividend, split, bonus, record dates,
AGM, in the window. Used for the "skip today" rule.

### 4.5 `evaluate(symbols[], profile)`

The main tool. Runs the hard vetoes and the scores for each symbol under a
named `profile` (`intraday_orb` now; others later) and returns a verdict:

```json
{"symbol": "THINCO", "verdict": "AVOID",
 "vetoes": [{"rule": "adtv_20d_median_cr_floor", "limit": 25.0, "value": 1.5,
             "as_of": "2026-11-13"}],
 "warnings": ["only 9 full 5-minute sessions in 60 days"],
 "score": null, "config_version": "2026-11-16.1"}
```

Verdicts: `PASS` (survives all vetoes, no missing hard-veto data), `WATCH`
(survives, but hard-veto data is unknown or a rule is borderline), `AVOID` (a
veto fired). Missing enrichment data (section 6) is a warning only.
`score` is a 0 to 100 rank among PASS and WATCH only.

### 4.6 `build_picks(symbols[], profile, out_path?)`

Calls `evaluate`, keeps PASS and WATCH, ranks, and writes a **proposal**
to `trader/picks.proposed.json` by default. The shape matches the real
`trader/picks.json`: `{"note": "...", "hits": [{"symbol": "RELIANCE.NS",
"name": "Reliance Industries Ltd"}]}`, with the `.NS` suffix and the press name the news
search uses, plus an extra `notes` string per stock (one dated line) and the
verdict. Test that the existing tools ignore the extra keys before relying
on it. The user decides the final list ("ask, do not assume"): writing
`trader/picks.json` itself needs `confirm=true` and the user's say-so, and
keeps the previous file as `picks.json.bak`.

### 4.7 `explain(symbol)`

Plain-words reasons for the last verdict: which rules fired, with numbers and
dates. No new data is fetched.

### 4.8 `source_status()`

Per source: last success, requests today, budget left, and any refusal or
block seen. Lets the pack say "screener.in unavailable" without guessing.

## 5. The data model, and why each field earns its place

This is for a Rs 10,000 account that day-trades with a Rs 200 max loss, a
Rs 500 daily limit and at most 3 trades. Those numbers are read from
`trader/config.json` (`max_loss_per_trade_inr`, `max_daily_loss_inr`,
`max_trades_per_day`), never hard-coded. Fields are chosen to answer whether a
stock can be traded cheaply, safely and with a sane stop. They are not a
general research database.

### 5.1 Identity

`symbol` (NSE, bare inside the server; `.NS` is added only when writing the
picks proposal), `name`, `isin`, `series` (must be `EQ` for the profile),
`sector`, `industry`, `index_membership` (Nifty 50, Next 50, Nifty 200,
none), `fno_eligible` (bool; informational only, F&O is a non-goal). The ISIN
is the stable key: tickers change.

### 5.2 Liquidity (hard data, the most important section)

- `adtv_20d_inr_cr`: average daily traded value over the last 20 finished
  sessions, in rupees crore. Median alongside the mean (`adtv_20d_median`),
  because one block-deal day skews the mean.
- `avg_volume_20d`, `volume_cv` (spread of daily volume; a high value means
  erratic liquidity).
- `traded_days_20d`: sessions with any trade. A gap here is a thin stock.
- `full_sessions_5m_60d`: how many of the last 60 sessions have every
  5-minute bar. This is what makes the Time Machine refuse a thinly traded
  stock (9 full sessions of 60 in one real case; its minimum is 20). v1 reads Yahoo's 5-minute history
  (source `yahoo`, rough); later the pack's export gives the Fyers count.
  It is a warning, not a veto: no odds from the Time Machine is a reason to
  decide without them, not to drop the stock. A stock that thin is caught by the
  traded value floor instead.
- `spread_proxy_pct`: `null` in v1 (needs real opening bars). Later, an
  estimate from the median bar range at the open and the tick size, labelled
  as an estimate.
- `position_vs_adtv_pct`: our order value (the pack's `max_order_inr`) as a
  share of daily traded value. On Rs 10,000 this is tiny for liquid names,
  and the check exists to catch the thin ones.

### 5.3 Tradability and exchange risk (hard vetoes)

- `price_band_pct` (2, 5, 10, 20, or `none`) and `band_as_of`. A stop or
  target near the band is a gap-and-no-fill risk; the near-the-band warning
  on a real plan stays in the pack (`plan.md`, item 3). Here the band only
  screens out stocks that are too tightly limited.
- `surveillance`: ASM stage, GSM stage, trade-for-trade segment, any
  circuit-only status. Any of these is a veto for the intraday profile.
- `suspended_or_halted` (bool).
- `circuit_hits_20d`: count of days that closed at a circuit. A stock that
  keeps hitting circuits cannot be exited on demand. It needs no Fyers: from
  the daily candles, count days whose close sits within one tick of the
  previous close times (1 plus or minus the band), using the band from
  `sec_list.csv`. A stock with no band has no circuit.
- `price_inr` (previous close) and `lot_affordability`: whole shares the
  pack's sizing would allow (the smallest of `max_order_inr`,
  `max_position_pct` of `budget`, and cash after `cash_buffer_pct`, all read
  from `trader/config.json`), so a Rs 5,000 stock that gives 1 share is
  flagged early.

### 5.4 Events (hard vetoes for today, soft for the week)

- `results_date`, `board_meeting_date`, `purpose` (as filed).
- `ex_date` for dividend, split, bonus, rights; `record_date`.
- `corporate_action_adjusted` (bool): are the daily prices adjusted for the
  action? If not, a split looks like a crash in the indicators.
- `recent_filing_flags`: pledge invocation, auditor resignation, SEBI order,
  promoter sale, block or bulk deal in the last 5 sessions (from filings
  only, each with a date and a link-free id).
- `fundraise_pending`: QIP, rights, OFS (a QIP launched over a weekend is the kind of note to catch).

### 5.5 Quality (soft score, and a few vetoes)

All figures state `basis` (consolidated or standalone), `period`, and
whether they are TTM, annual or a quarter. Mixing bases is the easiest way
to be wrong.

- Growth: sales and profit, 3-year and TTM, and the latest quarter YoY.
- Returns: ROCE, ROE, with the 3-year median (one good year is not quality).
- Leverage: debt to equity, interest cover, net debt to EBITDA.
- Earnings quality: operating cash flow to net profit (3-year), receivable
  days and inventory days trend, other income as a share of profit.
- Ownership risk: promoter holding and its change over 4 quarters, pledged
  share of promoter holding, FII and DII change.
- Governance flags: auditor change, related-party size where available,
  qualified audit opinion. Veto only on the severe ones, and always show the
  filing date.

For a day trader these rarely decide a trade. They decide which stocks never
enter the list: a high-pledge, negative-cash-flow company that gaps on a
rumour is an avoidable risk. These fields need screener.in (build step 7);
until then they are `null` enrichment data.

### 5.6 Valuation (context only, never a veto)

P/E, P/B, EV/EBITDA, each against the stock's own 5-year median and the
sector median, with the sector median's sample size. Report the percentile,
not an opinion. A cheap-looking number on a shrinking business is a trap, so
this section never moves a verdict alone.

### 5.7 Trend and relative strength (daily, from finished days)

- Daily closes: 20-day closing-high distance, 20 and 50-day average
  position, 52-week high and low distance.
- Relative strength: stock return vs the Nifty over 20 and 60 days.
- The same setup tags the existing scanner uses (breakout, bull flag,
  reclaimed the 20-day average, oversold bounce), so the two never disagree.
  Do not import or copy `trader-scanner` code (principle 9). Read the tags
  from the scanner's own output file, `trader/watchlist.json` (written by
  `scan.py daily`), and say when that file's date is not today's.

### 5.8 Volatility and fit (what links a stock to the Rs 200 rule)

- `atr14_pct` and `avg_day_range_pct` (a small cap can run about 7% a day).
- `typical_or_range_pct`: the median opening-range width in percent over 20
  sessions. A very narrow range gives a stop that the spread eats; a very
  wide one gives a stop that breaks the max loss. `null` in v1: Yahoo's
  opening ranges are too narrow (`plan.md`, section 3), so a Yahoo figure
  would mislead. Filled later from the pack's export.
- `gap_stats`: median and 90th-percentile overnight gap in percent, and how
  often the stock gaps beyond its own range (daily candles, so v1 has it).
- `max_loss_at_stop_inr_est`: an estimate only in v1, because the pack's
  real stop (the opening-range midpoint) needs the real opening range. Use
  a stand-in stop of half the median 20-day daily range, the shares from
  `lot_affordability`, and label it `estimate`. Over the config
  `max_loss_per_trade_inr` is a warning, never a veto: the real check stays
  in `trader-risk` and `trader-budget`, which see the actual plan.
- `cost_drag_pct`: the estimated round-trip charges as a share of a 2R
  target on that stand-in stop. Read the preset named by `costs` in
  `trader/config.json` (now `icicidirect_prime_4999`); never hard-code
  rates. If costs eat a large part of the target, the stock is a poor fit at
  this account size. A warning, not a veto.
- `beta_60d` and `correlation_to_picks`: two picks that move together are one
  bet, not two. Flag a list where several picks sit in the same sector.

## 6. Verdict rules (profile `intraday_orb`)

Every value below is a starting guess, not a finding, to be tuned on paper
days. They live in `screener_mcp/profiles/intraday_orb.json`.

Data tiers:

- **Hard-veto data**: series, traded value, price band, surveillance,
  events. If one is `null`, the stock is capped at `WATCH`.
- **Enrichment data**: 5-minute completeness, opening-range width, spread,
  the stand-in max loss, cost drag, valuation, most of quality, and pledge
  until screener.in is built (its only source, build step 7). If one is
  `null`, add a `not_available_v1` warning and leave the verdict alone.
  Pledge becomes hard-veto data at step 7, when a real source exists.

Hard vetoes (any one gives `AVOID`):

| Rule | Starting value |
| --- | --- |
| Series | `EQ` only |
| `adtv_20d_median` | below Rs 25 cr is `AVOID`; Rs 25 to 100 cr is `WATCH` with a warning; Rs 100 cr and above passes this rule |
| Surveillance (ASM, GSM, T2T) | none |
| Results or board meeting today or tomorrow | none |
| Ex-date for a split, bonus or rights today | none |
| Price band | 5% or tighter is `AVOID`; 10% is `WATCH` with a warning |
| Whole shares allowed by `lot_affordability` | at least 1 (below 1 is `AVOID`); a warning below 5 |
| Pledged share of promoter holding | from step 7: `AVOID` above 20% (a guess; open question 4). In v1: not available, a warning only |
| Severe governance flag filed in the last 90 days | none |

Warnings only, never a veto: `full_sessions_5m_60d` below 20,
`max_loss_at_stop_inr_est` over the config limit, high `cost_drag_pct`, a
10% band.

Soft score (0 to 100, rank only): liquidity depth, trend and relative
strength, volatility fit, quality, event cleanliness. Weights live in the
profile file. Report the score's parts, never only the total.

`WATCH` when a hard-veto field is `null` (for example no surveillance list
today) or a borderline rule fired (a 10% band, traded value Rs 25 to 100 cr).

## 7. Caching and request budgets

- Slow fields (fundamentals, ownership, results history): cache for the
  quarter or until a new result date passes, whichever is first.
- Daily fields (bands, surveillance, daily candles, delivery): cache for the
  trading day, keyed by the date.
- Events: refresh at most twice a day (evening and 8:45).
- Budget per source per day, a hard stop at the budget, and a stop for the
  day on any 429, block or captcha page. Clearing a stop needs the user's
  say-so, same as the Fyers rule in CLAUDE.md.
- Cache is a local SQLite file (standard `sqlite3`) in `~/.screener-mcp/`,
  keyed by `(source, key, as_of)`, so old answers stay for replay and tests.
- Two server processes must not corrupt the cache or the request counter:
  use SQLite transactions or a lock. The pack's Fyers counter once lost two
  watches to exactly this race (`plan.md`, item 9).

## 8. Correctness traps to design for

- **Units**: rupees, crore (1 crore = 10,000,000), lakh. Store base units in
  rupees and convert at the edge. Print Indian grouping (Rs 1,00,000).
- **Consolidated vs standalone**: keep both, label which one each field
  uses, default to consolidated for ratios and say so.
- **Restated figures**: companies restate past periods. Store `as_of` and a
  `fetched_at`, never overwrite, and warn when a restated value changed a
  verdict.
- **Fiscal year**: India's FY ends 31 March. Name periods as `Q2 FY27` and as
  a date.
- **Symbol changes and mergers**: key by ISIN, keep a symbol history table.
  A typed name can differ from the NSE symbol (a long company name
  against its short symbol): resolve names to a symbol and ask when it is
  ambiguous, never pick silently.
- **Special characters**: `M&M` is URL-encoded as `M%26M` for Fyers; keep the
  encoding in one place for any source that needs it.
- **Time**: India time (UTC+5:30, no DST) worked out in the code, never from
  the computer's zone. NSE holidays 2026 only; the 2027 list is a known gap.
- **Survivorship**: a screen run today on today's list says nothing about
  past performance. Never present a screen result as a backtest.
- **Float and rounding**: rupee amounts as decimals; round tick-size prices
  down to the NSE tick for the price, as the pack does.

## 9. Errors

Stable codes, each with `retryable`:

`SOURCE_UNAVAILABLE`, `SOURCE_BLOCKED` (stop for the day), `RATE_BUDGET`,
`NOT_FOUND`, `AMBIGUOUS_SYMBOL` (returns candidates), `STALE_DATA` (older
than the field's maximum age), `BAD_QUERY`, `PARSE_CHANGED` (a source's page
shape changed: fail loudly with the field name, do not guess),
`CONFIG_INVALID`.

A parser that cannot find a field returns `PARSE_CHANGED` for it. It never
returns a plausible-looking default.

## 10. Security

- Transport: stdio, local only. No network listener.
- Secrets: if the user chooses the own-login route (open question 2), the
  screener.in session cookie or token lives in a file under
  `~/.screener-mcp/` with owner-only access, read only by the server. It is
  a different folder from `~/.day-trader-india/`, which holds the Fyers
  token and which the server never opens. A secret is never accepted as a
  tool argument, never printed, never logged, never in an error message, and
  never passes through the chat. The user logs in themselves, in their own
  terminal.
- Prompt injection: every scraped string goes through a strict extractor to
  typed fields. Anything free-text is placed in `untrusted_text`, length
  capped, with control characters removed. The pack's rule holds: a headline
  is a lead, not a fact, and never an instruction.
- Allowlist of domains the server may call. Anything else is refused.
- Logs: request counts and codes only; no response bodies, no secrets.
- Least privilege: inside `trader/` the server reads `config.json` and the
  pack's output files, and writes only the one proposal file (and
  `picks.json` itself only on `confirm=true`, with a backup). It never reads
  the Fyers token.

## 11. Testing

- Fixtures are real saved answers, each dated in its file docstring, as the
  pack does. No token or cookie in any fixture.
- Unit tests for every rule with the number and date in the failure message.
- Golden-file tests: the same fixtures must always give the same verdicts.
- A test that every numeric field in every tool output has `as_of`, `unit`
  and `source`.
- A test that the server's own text (its spec, docs, messages and reasons)
  has no em dash (the repo rule). Scraped text in `untrusted_text` is data
  and is exempt: a headline may legitimately contain one.
- A test that the proposal file loads in the existing tools, with the extra
  keys ignored. `news.py` reads `trader/watchlist.json` by default, so the
  test passes `--watchlist trader/picks.proposed.json` explicitly. It reads
  only `hits[].symbol` and `hits[].name` (checked in `news.py`,
  `watch_from_files`), so extra keys are safe there; `watch_from_files` also
  adds symbols from `trader/plan.json` and `trader/portfolio.json`, so a
  stale plan can add a stock the proposal did not list.
- A test that the server never opens anything under `~/.day-trader-india/`.
- Offline by default. A live test is a separate, opt-in command that makes
  one polite request per source.
- Property tests on units: crore to rupee round trips, Indian grouping.

## 12. Built for later (do not build now)

- **UI or website**: the library package returns plain dataclasses and JSON.
  The MCP wrapper and a future web API are two thin shells over it. Keep
  profiles, config and cache independent of MCP.
- **Swing or delivery mode (Option B)**: add a `swing` profile, not a rewrite.
  It reuses sections 5.2 to 5.7 and adds: weekly trend, longer ATR, results
  proximity over weeks, delivery and holding costs, gap and overnight risk
  fields, and a stop and target from daily structure. The risk and ticket
  tools in the pack would need new rules first; the spec for that is a
  separate document.
- **Backtesting the screen**: keep every daily snapshot (verdicts and
  inputs) so that, in time, you can ask whether PASS stocks did better than
  AVOID ones. Point-in-time data matters: store what was known on the day.
- **More universes**: Nifty 200, Midcap, F&O list as profile inputs.
- **Alerts feed**: a daily "what changed since yesterday" diff of the
  verdicts (new AVOIDs, new events).
- **Multi-user**: not needed. If ever wanted, per-user secrets and per-user
  caches, never shared.

## 13. Build order

1. Package skeleton, config loader, profile file, units and time helpers,
   tests. No network.
2. NSE `sec_list.csv` (bands, series), surveillance lists and the events
   calendar, from saved fixtures first, then one live fetch each.
3. Yahoo daily candles (finished days only): traded value, ATR, gaps,
   circuit hits, trend. No Fyers.
4. The `evaluate` engine: vetoes, score parts, verdicts, `explain`.
5. `build_picks` writing the proposal file, and a test that
   `news.py --watchlist` reads it unchanged.
6. The MCP wrapper and `source_status`. This is v1: the user supplies the
   symbols.
7. screener.in `get_wishlist` and `run_screen`, once access and terms are
   confirmed; then fundamentals, ownership and valuation sections.
8. Option 2 for the Fyers-only fields: a small change in the pack so that
   `trader-scanner` exports the true opening-range width and 5-minute
   completeness to a file the server reads. The server still never touches
   the token. Fits with the Time Machine on Fyers history (`plan.md`,
   item 2).
9. A week of paper days. Compare verdicts to what actually happened and tune
   the profile. Record what changed and why.

## 14. Open questions (unverified, need the user)

1. What screener.in allows for automated personal access (terms of use, any
   export or API route). Until confirmed, do not build the scraper.
2. How screener.in data reaches the server (build step 7). Either an
   exception in CLAUDE.md for the user's own login (a session cookie in
   `~/.screener-mcp/`, the user logs in in their own terminal), or no cookie
   at all: a wishlist or screen export that the user downloads themselves
   and the server reads as a file. The export route needs no secret and
   avoids the cookie rule; it is the lower-risk default.
3. Where the server runs (this laptop only, or elsewhere later), and whether
   `screener-mcp/` lives in this repo or its own.
4. The liquidity floor and pledge limit the user is comfortable with. The
   Rs 100 cr, Rs 25 cr and 20% values are guesses.
5. Whether the profile should also exclude a sector (for example PSU banks
   on a results week) or keep it to the rules above.
6. Whether to keep daily snapshots from the start (recommended; it costs
   little and enables the later backtest).
