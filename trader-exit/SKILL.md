---
name: trader-exit
description: >-
  Exit Planner for the NSE. Sets your stop and your target before you enter,
  so you know when to get out. Reads the entry from trader-entry (or a price
  you give), puts the stop at the opening-range midpoint by default (or the
  range low, your price, a percent, or a multiple of the ATR), rounds it down
  to the NSE tick, and sets the target at 2R (or 1R, or your price). Refuses a
  stop at or above the entry, a target at or below it, or a stop too tight to
  survive the spread, and says why. Gets you flat by 15:15 IST, before the
  broker's auto square-off. Writes trader/plan.json for the Time Machine, the
  Budget Manager and Price Alerts. Long side only. Use when the user says
  "where's my stop", "set my stop and target", "plan the exit", "when do I get
  out", "stop loss", "what's my R", "risk reward", or right after
  /trader-entry triggers, before /trader-timemachine.
argument-hint: "[--stop or-mid|or-low|price:X|pct:X|atr:K] [--target 2R|1R|price:X]"
---

# trader-exit

The Exit Planner decides how a trade ends before it starts. The stop is where
the setup has failed. The target is where you take what you came for. Both
are set BEFORE the entry, written down and handed on, so nobody has to decide
anything in the middle of a fast move. A stop is a plan, not a guarantee: a
gap or a fast market can fill past it. Day trading loses most people money,
and a neat plan does not change that.

`${CLAUDE_SKILL_DIR}` below is this skill's folder (where this SKILL.md lives).

```bash
python "${CLAUDE_SKILL_DIR}/exit.py" plan                          # trader/entry.json: midpoint stop, 2R target
python "${CLAUDE_SKILL_DIR}/exit.py" plan --stop or-mid --target 2R --write
python "${CLAUDE_SKILL_DIR}/exit.py" plan --stop atr:1.5           # needs the session's bars (Yahoo or --offline)
python "${CLAUDE_SKILL_DIR}/exit.py" plan --symbol HCLTECH --entry 1384.60 --or-high 1381.00 --or-low 1373.80
python "${CLAUDE_SKILL_DIR}/exit.py" show                          # the current trader/plan.json
```

Other flags: `--flat-by 15:10`, `--json`, `--now "2026-11-13 09:36"` (India
time), `--entry PRICE` with a waiting entry.json to plan ahead, `--setup
level`, `--offline FILE` (a saved Yahoo chart JSON for an ATR stop). Prices
are rupees; `1384.60`, `Rs 1,384.60` and `price:Rs 1377.40` all read.

## What it reads and writes

| file | what |
| --- | --- |
| `trader/entry.json` | the trigger from trader-entry: symbol, entry price, time, bar, opening range |
| `trader/config.json` | `flat_by` (15:15), `min_reward_risk` (1.0: a note here, trader-risk enforces it) and `band_warn_pct` (1: how close to a price-band limit, in percent of the previous close, before the plan warns) |
| `trader/sec_list.csv` | optional: NSE's security list (Symbol, Series, Security Name, Band) for the price-band warning. Layout in `docs/sec_list_format.md` |
| Yahoo chart API | only for an `atr:K` stop: the session's bars up to the entry bar, free and unofficial |
| `trader/plan.json` | with `--write`: entry, stop and its rule, target and its R, risk a share, reward:risk, flat by. trader-timemachine, trader-budget and trader-alerts read it |

## Stops and targets

| stop | where it goes |
| --- | --- |
| `or-mid` | the opening-range midpoint (the default for an opening-range breakout) |
| `or-low` | the opening-range low: wider, so fewer shares for the same max loss |
| `price:X` | your price |
| `pct:X` | X percent under the entry |
| `atr:K` | K times the 14-bar ATR under the entry, on the session's bars up to the entry bar. With fewer than 14 bars by then it averages all of them and says so |

A level setup has no opening range to lean on, so it needs a stop you name.

- **Ticks.** Both exits land on the NSE tick, or the exchange rejects the
  order. The tick goes by the price (circular NSE/CMTR/67133): Rs 0.01 below
  250, 0.05 up to 1,000, 0.10 up to 5,000, 0.50 up to 10,000, 1.00 up to
  20,000, 5.00 above. The stop rounds DOWN to the tick (away from the entry)
  and so does the target (the side that is easier to reach); it says so when
  a price moved. NSE sets each stock's tick monthly from the previous month's
  last close, so a stock near a boundary can differ: `--tick 0.05` overrides.
- **The math.** Risk = entry minus stop. Target = entry + R x risk. `2R` by
  default; `1R`, `1.5R` or `price:X` also work.
- **Refused, with the reason.** A stop at or above the entry. A target at or
  below it. A risk under 0.05% of the price: too tight to survive the
  spread, normal wiggle would stop you out. An entry.json that has not
  triggered (unless you give `--entry`). A short: this pack plans longs only.
- **Price bands.** Many stocks have a daily band of 2, 5, 10 or 20 percent
  of the previous close (small caps often 20 or 10). At the band
  trading can stop and a stop order may not fill. With `trader/sec_list.csv`
  saved and the previous close given (`--prev-close`, or `prev_close` in
  entry.json), the plan warns, in plain words, when the stop or the target
  is within `band_warn_pct` (default 1) of the day's upper or lower limit,
  or beyond it. The limits round to the tick, inside the band. It is a
  warning, never a refusal. No file, no previous close or an unknown symbol:
  it says "band unknown" once and carries on. A missing file is noted once
  per India day, not on every plan (the note is remembered in
  `trader/state/`). It also says so, once a day, if the saved list is older
  than the latest trading day (bands may have changed), and if the planned
  stock appears twice in the EQ series (the last row is used). A stock with
  no band says so.
- **Flat by.** 15:15 IST by default (or `flat_by` in the config). Out by
  then, win or lose, no overnight hold. That is before the broker's auto
  square-off of intraday (MIS) positions, which most brokers run from about
  15:20 and charge a fee for. A flat-by at or after the 15:30 close is
  refused, and so is an entry at or after the flat-by time. The NSE has no
  early closes.

## Steps

1. Run it right after `/trader-entry` triggers. Before that, `--entry PRICE`
   plans ahead at the level you expect.
2. Use the default stop for an opening-range breakout unless the user names
   another. A level setup needs one: ask.
3. Run `exit.py plan --write`. Read back the entry, the stop and its rule,
   the target and its rule, the risk a share, reward:risk and flat by.
4. If it refuses, say the reason and the fix (a wider stop, a farther
   target). Never loosen anything on your own.
5. Say once that the stop is a plan, not a guarantee.
6. Hand off to `/trader-timemachine` to replay the plan, then `/trader-budget`
   to size it to the max loss per trade. Offer `/trader-alerts` for the stop,
   the target and the flat-by time. Claude can keep `entry.py watch` running
   in the background or on a `/loop` until a setup triggers, then come here.

## Example: HCLTECH, Friday 2026-11-13

HCLTECH.NS, real data. The entry is 1384.60 at 9:35 AM (the 9:30 bar, bar 3)
and the opening range is 1373.80 to 1381.00. `exit.py plan --write` (the
defaults: midpoint stop, 2R target):

```
Exit plan: HCLTECH.NS long, Fri 2026-11-13, opening-range breakout on 5-minute bars
  Entry         Rs 1,384.60 at 9:35 AM (bar 3)
  Stop          Rs 1,377.40  opening-range midpoint: (Rs 1,381.00 + Rs 1,373.80) / 2 = Rs 1377.4
  Target        Rs 1,399.00  2R (two times the risk)
  Risk a share  Rs 7.20 (0.52% of the entry)
  Reward:risk   2.0
  Flat by       15:15 IST, win or lose: no overnight hold
```

Both exits are on the Rs 0.10 tick for a stock between 1,000 and 5,000. A 1R
target would be Rs 1,391.80, but a 0.52 % move does not clear the round
trip's costs on a small account: `/trader-budget` and `/trader-risk` measure
reward:risk after costs and refuse it. `/trader-budget` shows which limit
sizes the trade.

## Rules

- The stop and the target are set before the entry, never after.
- Never move a stop further from the entry once the trade is on.
- Plain numbers only: entry, stop, target, risk a share, reward:risk. It
  never prints a P&L or a return.
- Nothing here promises winning trades or money. A 1R target is not a
  prediction that the price gets there.
- Long side only. This pack plans longs only.

## What it never does

It never places an order, never sizes a position, never widens a stop to
make a plan pass, and never calls a stop a guarantee.

## Safety

- Education and tooling, not financial advice. A PASS is a rules check, not a recommendation. Not SEBI-registered advice.
- Paper trading by default (`"paper": true`): practice, written down, not placed. Going live is the user's own decision, in their own config.
- Nothing in this pack places an order. trader-broker shows a ticket only when trader-risk passed that exact order
  today, and records a yes only when the user typed an explicit yes for that one order in the chat. The user then
  places it themselves, in their own broker's app, and records the result.
- No F&O, margin (MIS leverage), short selling or leverage unless the config allows it and the user confirms.
- Broker logins, passwords, PINs, OTPs and API keys never go in the chat.
