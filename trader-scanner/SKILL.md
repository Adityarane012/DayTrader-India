---
name: trader-scanner
description: >-
  Chart Scanner for the NSE. Scans the Nifty charts for setups:
  opening-range breakouts, flags, oversold bounces. Builds the list of stocks
  from the official NSE index lists (Nifty 50, Bank Nifty, Nifty Next 50,
  Nifty 200, or several together), runs a pre-market scan of daily closes
  (20-day closing-high breakout, bull flag, reclaimed the 20-day average,
  oversold, oversold bounce) and an intraday opening-range breakout scan on
  5-minute bars (the 9:15 to 9:30 IST range), then writes
  trader/watchlist.json for trader-news and trader-entry. The opening-range
  scan reads the user's own Fyers login (one request per stock); the
  pre-market scan reads free Yahoo daily closes, finished days only. Use when the user says "scan the market", "scan the Nifty",
  "find me setups", "what is breaking out", "opening range breakouts", "scan
  Bank Nifty", "scan for bull flags", "oversold stocks", "pre-market scan",
  "build my watchlist", "what should I look at today", or at the start of a
  trading day before /trader-news.
argument-hint: "[universe | daily | orb] [--index nifty50|banknifty|niftynext50|nifty200] [--at HH:MM]"
---

# trader-scanner

The Chart Scanner is the first step of a day trade. It reads the charts of
an NSE index and lists the ones that match a rule. That is all it does. A
scan is a list of charts that match a rule, not a list of stocks to buy, and
a setup on a chart is not a prediction. Most people who day trade lose money;
the scanner does not change that. It only saves you from flipping through 50
or 200 charts by hand.

`${CLAUDE_SKILL_DIR}` below is this skill's folder (where this SKILL.md lives).

```bash
python "${CLAUDE_SKILL_DIR}/scan.py" universe                          # the Nifty 50 -> trader/universe.txt
python "${CLAUDE_SKILL_DIR}/scan.py" universe --index banknifty        # or niftynext50, nifty200
python "${CLAUDE_SKILL_DIR}/scan.py" universe --index nifty50,niftynext50 --refresh
python "${CLAUDE_SKILL_DIR}/scan.py" daily                             # before the open -> trader/watchlist.json
python "${CLAUDE_SKILL_DIR}/scan.py" daily --symbols RELIANCE,HCLTECH,M&M
python "${CLAUDE_SKILL_DIR}/scan.py" orb                               # after 9:35 AM IST, Fyers -> trader/watchlist.json
python "${CLAUDE_SKILL_DIR}/scan.py" orb --at 09:45                    # cut the clock at 9:45 AM IST
python "${CLAUDE_SKILL_DIR}/scan.py" orb --watchlist trader/watchlist.json --json
```

Flags: `--min-price 20` (rupees) and `--min-volume` (daily 1,00,000 shares,
orb 0), `--or-minutes 15`, `--source fyers|yahoo` (orb; fyers is the
default), `--max-confirm 200` (orb on Yahoo, stage 2), `--now
"2026-11-13 09:35"` (India time) to pin the clock, `--offline PATH` to read
saved Yahoo files, `--no-write`, `--show N`, `--json`. Exit code 0 when the
scan found something, 1 when it found nothing or could not run (the reason
is one plain line).

## What it reads and writes

| file | what |
| --- | --- |
| `universes/ind_*list.csv` (this folder) | the official index lists from niftyindices.com, as of 2026-11-14 |
| `trader/universe.txt` | written by `universe`: one `SYMBOL.NS\|Company Name` a line, read by `daily` and `orb` |
| `trader/watchlist.json` | written by `daily` and `orb`: `mode`, `as_of`, `universe`, `scanned`, `failed`, `hits[]`. trader-news and trader-entry read `hits[].symbol` |
| `trader/config.json` | read by `orb`: `no_entries_after` (default 15:00) |

## The universe

`universe --index NAME` takes the constituents of an NSE index from the
official list at niftyindices.com (company name, industry, symbol, series,
ISIN; series EQ only). The lists of 2026-11-14 ship in `universes/`;
`--refresh` asks niftyindices.com for today's list first, one request, and
if it does not answer it says so and uses the shipped one. Index changes
happen twice a year, so refresh after a rebalance.

| `--index` | stocks |
| --- | --- |
| `nifty50` (default) | 50, the video's list |
| `banknifty` | 14 banks: for Bank Nifty, scan the banks inside it. The scanner never trades the index itself and does not do F&O |
| `niftynext50` | the 50 after the Nifty 50 |
| `nifty200` | 200, the Nifty 50 and the Next 50 among them |

Several at once (`--index nifty50,banknifty`) are merged, each stock once:
59 for those two. Your own list works too: `--symbols` or `--watchlist FILE`
(one symbol a line, or a watchlist.json).

## The daily scan (before the open)

Yahoo's spark endpoint returns closes for 20 symbols a request, so the Nifty
50 is 3 requests and the Nifty 200 is 10. Liquidity comes from the spark
meta: last price at least `--min-price` and the last session's volume at
least `--min-volume`; every Nifty stock clears the defaults. Run it before
the open or after the close: during the session the volume is the day's so
far, and today's daily bar is left out until 15:30.

The setups are computed from daily closes only (spark has no highs or lows):

| setup | the rule on closes |
| --- | --- |
| `breakout_20d` | the last close is above every close of the 20 sessions before it |
| `bull_flag` | up more than 10 % over the 10 sessions before the last 5, then the last 5 closes inside a 5 % range |
| `reclaim_ma20` | the close before was under its 20-day average, the last close is above it |
| `oversold` | RSI 14 (Wilder) under 30 |
| `oversold_bounce` | RSI 14 was under 30 yesterday and today closed up |

Hits are listed most traded first (price times volume, rupees).

## The opening-range breakout scan (during the session)

The opening range is the first `--or-minutes` (15) of the session: the 9:15,
9:20 and 9:25 five-minute bars. A hit is the first completed 5-minute bar to
CLOSE above the range high, at that bar's close time.

On Fyers (the default; needs the user's login for the day, `fyers.py
login` in trader-entry or trader-alerts): one candle request per stock, with
real highs and lows, so there is no stage 2. `fyers.py` stops itself at 40
requests a minute (Fyers allows 50), so the Nifty 50 takes about a minute
(40, a wait, then 10) and Bank Nifty a few seconds. It checks first that the
day's requests are enough, and stops the scan, saying after how many stocks,
if the login goes or Fyers says too many requests. It never switches to
Yahoo on its own: Yahoo's NSE bars run 15 to 30 minutes behind, and a late
breakout list is a wrong one.

With `--source yahoo` (practice, replays) it takes two Yahoo stages:

1. Stage 1, every symbol: spark closes of today's 5-minute bars, 20 a
   request. A chart goes on only if a completed bar after the range closed at
   or above the highest close of the range. That is a necessary condition
   (the range high is at least every range close), so no breakout is lost.
2. Stage 2, each candidate: the v8 chart with real highs and lows, one
   request each. Range high = the highest high of the range bars, range low =
   the lowest low. It checks at most `--max-confirm` (200), the most traded
   first, and prints PARTIAL with the count it skipped.

A chart is usable only when every 5-minute bar from 9:15 to the cutoff is
there; a missing bar means a halt, no trades, or one of Yahoo's gaps (its
NSE data usually lacks the 15:15 to 15:25 bars, after the entry cutoff
anyway). Null closes are dropped, a bar off the 5-minute grid (the live tick)
is dropped, and a bar counts only once it is complete. Before 9:35 AM, on a
weekend or NSE holiday, after the close, or after `no_entries_after` (15:00)
it prints one plain line and writes nothing.

## Data and limits

- `orb` reads Fyers (above). `daily` reads Yahoo's daily closes: finished
  days, so Yahoo's delay does not change them.
- Yahoo's chart and spark endpoints are free, unofficial and run behind. Bars are
  5-minute bars, bar by bar. query2 first, query1 on a 429 or 5xx, one retry
  after a 5-second wait on a 429. Not for scalping.
- Partial results are said as partial: "Fetched 48 of 50 charts (2 failed or
  had no data)". Never round a partial scan up to "the whole index".
- NSE holidays for 2026 (circular NSE/CMTR/71775). The NSE has no early closes.

## Steps

1. Once a week, or after an index rebalance: `scan.py universe` (with
   `--index` for the list the user trades, `--refresh` to fetch today's).
2. Before the open: `scan.py daily`. Tell the user the counts (fetched,
   liquid, scanned, hits) and the top few by setup.
3. After 9:35 AM IST: `scan.py orb` (needs the user's Fyers login for the
   day; if it says there is none, ask them to log in, do not use
   `--source yahoo` for the live scan). Tell the user how many usable charts
   broke their range and when, and that a later hit is closer to the price
   now.
4. The user picks one chart. Hand it on: `/trader-news SYMBOL` (what is
   moving it), then `/trader-entry SYMBOL` (the entry bar by bar). Never pick
   for them.

## Example: Friday 2026-11-13

A replay of the Nifty 50 at 9:35 AM IST, on saved real Yahoo charts (a
saved file is always read as Yahoo; live, the same scan reads Fyers)
(`tests/fixtures/trader-scanner/wall5m-2026-11-13.json.gz`):

```
python scan.py orb --offline wall5m-2026-11-13.json.gz --now "2026-11-13 09:35"
Opening-range breakout scan, Fri 2026-11-13 9:35 AM IST: 15-minute range (9:15 AM to 9:30 AM), 5-minute bars, Yahoo.
Fetched 50 of 50 charts; 50 usable; 26 candidates, 26 confirmed with real highs and lows.
13 of 50 charts closed above their opening-range high by 9:35 AM:
   9:35 AM  BAJFINANCE.NS    Rs 1107.10  range 1,091.75 to 1,105.75  +0.12% over
   ...
   9:35 AM  HCLTECH.NS       Rs 1384.60  range 1,373.80 to 1,381.00  +0.26% over
```

HCLTECH's range is the 9:15 to 9:25 bars, high 1381.00, low 1373.80; the 9:30
bar closed at 1384.60, 0.26 % over the high, at 9:35 AM. By 10:00 it is 29
of 50, by 15:00 34. The pre-market scan for Monday Nov 16 (closes through
Friday) tags 14 of the 50, most of them bull flags in a strong November, with
RELIANCE first by rupees traded. The user picks HCLTECH and Claude hands it to
`/trader-news HCLTECH`, then `/trader-entry HCLTECH`.

## Rules

- Say what was scanned: which index, how many symbols, how many charts came
  back, how many were usable, and the time of the data.
- Say "matched a rule", never "a buy", "a winner" or "a good trade".
- Never print a P&L, a return or a profit figure.
- A hit is stale once the price has moved on. Re-run before acting on it.

## What it never does

It never places, sizes or checks an order, never says which stock to buy,
never calls data live, and never promises that a setup works.

## Safety

- Education and tooling, not financial advice. A PASS is a rules check, not a recommendation. Not SEBI-registered advice.
- Paper trading by default (`"paper": true`): practice, written down, not placed. Going live is the user's own decision, in their own config.
- Nothing in this pack places an order. trader-broker shows a ticket only when trader-risk passed that exact order
  today, and records a yes only when the user typed an explicit yes for that one order in the chat. The user then
  places it themselves, in their own broker's app, and records the result.
- No F&O, margin (MIS leverage), short selling or leverage unless the config allows it and the user confirms.
- Broker logins, passwords, PINs, OTPs and API keys never go in the chat.
