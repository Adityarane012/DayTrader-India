# Upstream

This repo is a hard fork of
[Jakeschincariol/day-trader-skill](https://github.com/Jakeschincariol/day-trader-skill)
(MIT), vendored unchanged in the first commit of this repo.

| | |
|---|---|
| Upstream commit | `3d0f4ef6986f4984b7c6bd46f7ff4f87744c3abd` |
| Upstream date | 2026-10-20, "The Trader skill v2: 11 day-trading skills" |
| Imported | 2026-11-14 |

## What changed in the fork

- India only: NSE symbols (`RELIANCE.NS`, `M&M.NS`), IST clock (UTC+5:30),
  NSE session 09:15-15:30, the 2026 NSE holiday list, flat by 15:15.
- Rupee config keys (`*_inr`) with Indian digit grouping; upstream's `*_usd`
  keys are refused.
- Scanner universes are the official Nifty index lists, not Nasdaq Trader's.
- News reads NSE corporate announcements and Google News instead of SEC 8-Ks.
- Stops and targets land on the NSE tick; budget and risk count the round
  trip's costs.
- The Time Machine replays to the flat-by time and accepts sessions with
  Yahoo's missing late bars.
- `trader-broker` renders a ticket the user places in their own broker's app;
  the Alpaca connection is gone.
- Removed: `trader-analyst`, `trader-pelosi`, budget's weights mode, the
  pattern-day-trader check, the Stooq quote source.
- Commands call `python`, not `python3`.

## Pulling upstream fixes

There is no shared history to merge. To pick up an upstream fix, diff the
upstream file against `3d0f4ef` and apply the change by hand, then move the
commit hash above forward.
