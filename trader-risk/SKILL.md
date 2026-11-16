---
name: trader-risk
description: >-
  Risk Manager for the NSE. Checks every trade against your limits and stops
  anything over them, before it can become a ticket. For a day trade: a stop
  is required, the loss at the stop must fit your max loss per trade in
  rupees (measured from the higher of the plan's entry and a fresh price),
  reward:risk must meet your minimum, the day's total risk must fit your
  daily loss limit, no more than your trades per day, and no new entries
  outside your entry window (9:30 to 15:00 IST) or when the NSE is closed. It
  also keeps the basics: NSE symbols, blocked symbols, order size, position
  cap, cash buffer, margin, short sales, F&O and crypto, whole shares only,
  malformed or bad bracket orders, duplicates and a daily order limit.
  Getting out is never blocked by a day limit. Prints PASS or BLOCK with the
  reason and records the verdicts so trader-broker only shows an order that
  passed. Use when the user says "check my order", "is this safe", "risk
  check", "does this break my rules", "can I take this trade", "how much
  have I risked today", or before /trader-broker, always.
argument-hint: "[path to orders.json]"
---

# trader-risk

The Risk Manager is the gate between a proposal and a ticket. Every order
written by trader-budget or trader-broker's flatten passes through it. A
BLOCK is final for that order: it does not go to the user for a yes, and it
never becomes a ticket. Most people who day trade lose money. These limits
keep each loss and each day's losses small. They do not make a trade win.

`${CLAUDE_SKILL_DIR}` below is this skill's folder (where this SKILL.md lives).

```bash
python "${CLAUDE_SKILL_DIR}/check.py"                           # trader/ files; writes trader/state/risk.json
python "${CLAUDE_SKILL_DIR}/check.py" --json
python "${CLAUDE_SKILL_DIR}/check.py" --no-write                # look without recording
python "${CLAUDE_SKILL_DIR}/check.py" --now "2026-11-13 09:36"  # pin the clock (India time)
```

## What it reads and writes

| file | what |
| --- | --- |
| `trader/orders.json` | the proposed orders (trader-budget, or trader-broker's flatten) |
| `trader/config.json` | the limits, in rupees (trader-budget ships `config.example.json`) |
| `trader/portfolio.json` | cash and holdings; if missing, a fresh account funded with the budget |
| `trader/prices.json` | a fresh price raises the entry it measures risk from; also values holdings |
| `trader/state/broker.json` | what was placed today: duplicates, trades per day, daily loss |
| `trader/state/risk.json` | the verdicts it writes, with a fingerprint of each exact order |

## Entries and exits

An **entry** opens or adds to a position: a buy, or a sell that would go
short. An **exit** only reduces what you already hold. Getting out must
always be possible, so an exit is checked for format, asset and short sales
only. Every other rule (day limits, entry window, loss, reward:risk, blocked
list, size, duplicates) turns into a warning for an exit, never a BLOCK.

## The checks

Orders are checked in file order, as if each passed order had filled, so a
batch that is fine order by order but breaks a limit together is caught.

| check | blocks when |
| --- | --- |
| format | no symbol, side not buy or sell, both or neither of qty and notional; any notional (rupee amount) order or fractional qty (NSE equity is whole shares); extended hours; a limit order with no limit price; a type other than market, limit, stop (SL-M) or stop_limit (SL); a validity other than DAY or IOC; a bracket that is not DAY or misses its stop-loss or take-profit |
| asset | an option or future (an NSE F&O symbol like NIFTY26NOV24000CE or SBIN26NOVFUT) while `allow_options` is false; crypto or anything that is not an NSE or BSE symbol (RELIANCE.NS, M&M.NS, BAJAJ-AUTO.NS, 500325.BO) |
| short | a sell of more than you hold (`allow_short` false) |
| blocked | (entries) the symbol is on the `blocked` list |
| size | (entries) under `min_order_inr` or over `max_order_inr` |
| position | (entries) the stock would be over `max_position_pct` of the account |
| cash | (entries) the buy would leave less than the cash buffer, or need margin |
| stop | (entries) no stop while `require_stop` is true (a bracket `stop_loss_stop_price`, or the order's plan stop); a stop on the wrong side of the entry |
| loss | (entries) qty x (entry minus stop) PLUS the round trip's costs over `max_loss_per_trade_inr` |
| reward:risk | (entries) what the target makes after costs, over what the stop loses with costs, under `min_reward_risk` |
| daily loss | (entries) the max losses (with costs) of today's entries, plus this one, over `max_daily_loss_inr` |
| trades | (entries) `max_trades_per_day` entries already placed today |
| window | (entries) before `no_entries_before` or after `no_entries_after`, or the NSE is closed |
| duplicate | (entries) the same symbol and side twice in one batch, or already placed today |
| daily limit | (entries) `max_orders_per_day` orders already placed today |

How the numbers work:

- **Symbols.** A bare symbol gets `.NS` (RELIANCE is RELIANCE.NS). Upstream's
  rule allowed 1 to 5 letters, so it blocked RELIANCE, M&M and BAJAJ-AUTO on
  its own; this one takes NSE symbols with `&` and `-`.
- **The entry it measures from**: the limit price for a limit order. For a
  market order, the HIGHER of the plan's entry and a fresh price from
  `trader/prices.json` (under 15 minutes old). A plan written at 9:36 cannot
  understate the risk at 10:00 after the price ran up. An older price is not
  used, and it says so.
- **Costs** are counted the same way trader-budget counts them: brokerage
  from the config's `costs` preset ("icicidirect_prime_4999" in the example
  config; "dhan" when the key is missing; "zero", a dict, or false), STT 0.025 % of the sell value, NSE transaction
  charge 0.00307 % and SEBI fee Rs 10 a crore of turnover, stamp duty 0.003 %
  of the buy value, GST 18 % on brokerage + transaction + SEBI. On a small
  account they decide a lot: a 1R target that looks fine before costs is
  usually blocked after them.
- **Daily loss** counts the full max loss of every entry placed today, win or
  lose, as trader-broker logged it. Two full-size Rs 200 trades and one more use up a
  Rs 500 day.
- **The window** is India time (UTC+5:30, no daylight saving), worked out in
  the tool, never from the computer's clock zone. The session is 9:15 to
  15:30; weekends and NSE holidays are closed; the NSE has no early closes.
  Set both `no_entries_*` to null to switch the window off.
- **No PDT rule.** The US pattern-day-trader rule does not apply on the NSE,
  so there is no check for it.
- **Rupees.** A config with upstream's `*_usd` keys is refused with the names
  to change, so a dollar number is never read as rupees.

Warnings do not block, but say them to the user: a LIVE account, a number
sent as a number instead of a string, a stop that lives only in the plan and
not at the broker, a price too old to use, a date past the 2026 holiday list.

## Steps

1. If the price may have moved since the plan, refresh it first
   (trader-alerts: `alerts.py quote HCLTECH --write`, a Fyers quote from the
   user's login). check.py itself never goes online. A price that came from
   Yahoo still counts (it can only raise the entry the risk is measured
   from), with a warning that it runs behind: get a Fyers quote and check
   again.
2. Run `check.py`. Exit code 0 means every order passed, 1 means at least one
   was blocked.
3. Tell the user the result in plain words, order by order: the max loss at
   the stop, reward:risk, and how much of today's limits it uses. For a
   BLOCK, give the reason and the fix (fewer shares, a closer stop from
   trader-exit, wait for the window, or skip the trade). Never change a
   limit yourself.
4. If the order changes in any way, run the check again. trader-broker matches
   each order to its verdict by fingerprint, so an edited order is not ready
   until it passes again, and a verdict from yesterday does not count today.

## Example: HCLTECH, Friday 2026-11-13

The HCLTECH bracket from trader-budget at 9:36 AM, on a fresh Rs 10,000
paper account with the example config:

```
PASS  #1 buy HCLTECH.NS 5 shares, entry
          entry 1384.60 (the plan's entry), stop 1377.40, target 1399.00: risk 7.20 a share
          max loss Rs 40.08 with costs (Rs 36 at the stop + Rs 4.08 costs) (limit Rs 200), reward:risk 1.69 after costs, 2.00 before (min 1)
          today before this: 0 of 3 trades, Rs 0 of Rs 500 daily loss

1 passed, 0 blocked at 2026-11-13 09:36 IST. Cash after the passed orders: Rs 3,077 (paper account).
```

One more share and it is blocked, by the size limits, not the loss:

```
        - size: Rs 8,307.60 is over your Rs 7,500 max order
        - position: HCLTECH.NS would be Rs 8,307.60, 83.1% of the Rs 10,000 account, over your 75% cap
```

The same order with a 1R target (1391.80) is blocked on costs: "reward:risk:
0.80 after costs, 1.00 before". Checked at 9:40 with a fresh 1392.00 quote it
is blocked too (0.40 after costs: half the move is gone). At 9:25 it is
blocked by the window (no new entries before 9:30), and at 15:05 by the
15:00 cutoff. The 15:15 sell that closes the position passes: it is an exit.

## Rules

- A PASS only means the order is allowed to be shown to the user. It is not a yes.
- Every number comes from the config, the order, the portfolio, the prices or the broker log.
- A Fyers quote is one reading and a Yahoo price runs behind; the broker's price
  is the one that fills, and a stop can fill worse than its price in a fast market.

## What it never does

It never places an order, never edits an order to make it pass, never
loosens a limit, never blocks a sell that only gets the user out, and never
treats a PASS as the user's yes.

## Safety

- Education and tooling, not financial advice. A PASS is a rules check, not a recommendation. Not SEBI-registered advice.
- Paper trading by default (`"paper": true`): practice, written down, not placed. Going live is the user's own decision, in their own config.
- Nothing in this pack places an order. trader-broker shows a ticket only when trader-risk passed that exact order
  today, and records a yes only when the user typed an explicit yes for that one order in the chat. The user then
  places it themselves, in their own broker's app, and records the result.
- No F&O, margin (MIS leverage), short selling or leverage unless the config allows it and the user confirms.
- Broker logins, passwords, PINs, OTPs and API keys never go in the chat.
