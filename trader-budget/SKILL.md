---
name: trader-budget
description: >-
  Budget Manager for the NSE. Sizes every position to your budget and your
  max loss per trade, in rupees. Reads the trade plan from trader-exit
  (entry, stop, target), finds the whole shares that fit inside four limits
  (max loss per trade, position cap, max order, cash after your buffer), says
  which limit decided it, and writes ONE intraday bracket order (entry,
  stop-loss, take-profit) to trader/orders.json. A stop too far away for your
  max loss is a plain refusal, not a smaller order. Nothing is placed. Use
  when the user says "how many shares", "size this trade", "how much should I
  buy", "I have Rs 10,000", "I only want to risk Rs 200 a trade", "set my
  rules", "keep 10% in cash", or after /trader-exit writes a plan.
argument-hint: "[budget in rupees]"
---

# trader-budget

The Budget Manager turns a plan ("buy HCLTECH at 1384.60, stop 1377.40")
into an exact order ("buy 5 shares"), inside rules the user sets once. The
stop decides the size: the further away the stop, the fewer shares. It writes
a proposal only. trader-risk checks it and trader-broker turns it into a
ticket the user places themselves. Day trading loses most people money.
Sizing to a max loss keeps each loss small; it does not make a trade win.

`${CLAUDE_SKILL_DIR}` below is this skill's folder (where this SKILL.md lives).

```bash
python "${CLAUDE_SKILL_DIR}/size.py"                         # trader/plan.json + trader/config.json
python "${CLAUDE_SKILL_DIR}/size.py" --write                 # write trader/orders.json
python "${CLAUDE_SKILL_DIR}/size.py" --limit --write         # a limit order at the plan's entry
python "${CLAUDE_SKILL_DIR}/size.py" --limit 1384.00 --json  # a limit order at 1384.00
```

`--now "2026-11-13 09:36"` pins the clock (India time). A plan for another
day is refused: make a new one with trader-exit.

## What it reads and writes

| file | what |
| --- | --- |
| `trader/config.json` | the rules (start from `config.example.json` in this folder) |
| `trader/plan.json` | the trade: entry, stop, target, setup, flat-by time (trader-exit writes it) |
| `trader/prices.json` | optional: a fresh price above the plan's entry means a bigger risk (trader-alerts writes it) |
| `trader/portfolio.json` | optional: its cash caps the size (trader-broker keeps it) |
| `trader/orders.json` | the one proposed bracket order it writes with `--write` |

## Step 1: set the rules once

If `trader/config.json` does not exist, copy `config.example.json` into
`trader/config.json` and ask the user for each value in plain words. All
money is rupees:

- **budget**: how much money this is for (example Rs 10,000). Only money they can afford to lose.
- **cash_buffer_pct**: how much always stays in cash (default 10).
- **max_loss_per_trade_inr**: the most one trade may lose if the stop fills at the stop, costs included (default 200).
- **max_position_pct**, **max_order_inr**, **min_order_inr**: the biggest position (75% of the
  budget), the biggest order (Rs 7,500) and the smallest order (Rs 100). Set max_order_inr to fit
  the account: a small number here caps every order (the video's warning about upstream's 4000).
- The day limits trader-risk enforces: **max_daily_loss_inr** (500), **max_trades_per_day** (3),
  **min_reward_risk** (1.0), **require_stop** (true), **no_entries_before** / **no_entries_after**
  ("09:30" / "15:00") and **flat_by** ("15:15"), all India time.
- **broker**: who the user places trades with: "icicidirect" in the example, or "dhan", "fyers",
  "zerodha", "angelone", "upstox". It only changes the ticket's instructions.
- **costs**: whose intraday charges to count: "icicidirect_prime_4999" in the example (0.01 % an order),
  "dhan" (the lower of Rs 20 and 0.03 % an order; also what the tools assume when the key is missing),
  "zero", a dict with brokerage_pct and brokerage_cap, or false.
- **blocked**: symbols they never want to trade.
- Keep **paper** true until they have watched it work for a while.

A config with upstream's dollar keys (`max_order_usd` and the like) is
refused with the names to change, so a dollar number is never read as rupees.

## Step 2: size the trade

```bash
python "${CLAUDE_SKILL_DIR}/size.py" --write
```

Whole shares only: NSE equity has no fractional shares. The size is the
smallest of four limits:

| limit | shares |
| --- | --- |
| max loss | the most shares whose loss at the stop PLUS the round trip's costs fits `max_loss_per_trade_inr` |
| position cap | budget x `max_position_pct` / entry |
| max order | `max_order_inr` / entry |
| cash | (budget minus the cash buffer) / entry, never more than the cash in `trader/portfolio.json` |

The entry it sizes at: the limit price with `--limit`. For a market order, the
plan's entry, or the price in `trader/prices.json` if it is fresh (under 15
minutes old) and higher. A price that ran up since the plan means a bigger
loss at the same stop. A lower price never shrinks the risk.

Costs are part of the answer. Every size comes with the round trip's
charges: brokerage (the `costs` preset), STT 0.025 % of the sell value, NSE
transaction charge 0.00307 % and SEBI fee Rs 10 a crore of turnover, stamp
duty 0.003 % of the buy value, GST 18 % on brokerage + transaction + SEBI.
The max loss shown is the loss at the stop plus those costs. Reward:risk is
what the target makes after costs over that loss, and that is the number
held against `min_reward_risk`.

It refuses, and writes no order, when: the size is zero shares, the order is
under the minimum, reward:risk after costs is under `min_reward_risk`, the stop is not
below the entry, the target is not above it (the move already happened), the
plan is for another day, the symbol is blocked, or the plan is a short. Say
the reason to the user in one line.

## Step 3: show the user

Show the four limits, which one decided the size, the shares, the rupees,
the costs, the max loss at the stop with costs and reward:risk after costs.
Say plainly that a stop is an order, not a
promise: in a fast market it can fill below the stop. Then hand over to
`/trader-risk`.

## Example: HCLTECH, Friday 2026-11-13

Opening-range breakout: entry 1384.60 at 9:35 AM, stop 1377.40 (the
opening-range midpoint), target 1399.00 (2R). Risk 7.20 a share. The example
config: Rs 10,000 budget, 10% cash buffer, Rs 200 max loss, ICICIDirect
Prime 4999 costs.

| limit | the math | shares |
| --- | --- | --- |
| max loss | Rs 200 / (7.20 risk a share + costs) | 24 |
| position cap | 75% of Rs 10,000 = Rs 7,500 / 1384.60 | **5 (decides it)** |
| max order | Rs 7,500 / 1384.60 | 5 |
| cash | Rs 10,000 minus Rs 1,000 = Rs 9,000 / 1384.60 | 6 |

```
Size: 5 shares of HCLTECH.NS = Rs 6,923 at 1384.60. At the stop: 5 x 7.20 = Rs 36.
Costs for the round trip, about Rs 4.12 (ICICIDirect Prime 4999 intraday: 0.01 % an order): brokerage Rs 1.39, STT Rs 1.75, exchange and SEBI Rs 0.44, stamp duty Rs 0.21, GST Rs 0.33.
After costs: max loss Rs 40.08 at the stop, Rs 67.88 made at the target, reward:risk 1.69 (2.00 before costs).
```

On a Rs 10,000 account the position cap binds long before the max loss: a
trade is about Rs 7,000 of stock whatever the loss limit says. Costs still
matter: Rs 4.08 on a Rs 36 loss is a ninth more, and that is why this example
uses the 2R target. With a 1R target (1391.80) the same 5 shares make
36.00 - 4.10 = Rs 31.90 against Rs 40.08 lost, reward:risk 0.80 after costs,
and it is refused. Say this plainly to the user: on a small account a tight
target mostly feeds the costs.

It writes:

```json
{"symbol": "HCLTECH.NS", "side": "buy", "qty": "5", "type": "market", "time_in_force": "day",
 "order_class": "bracket", "take_profit_limit_price": "1399.00", "stop_loss_stop_price": "1377.40",
 "why": "opening-range breakout on HCLTECH.NS: 5 shares, bound by your position cap (5 x 7.20 = Rs 36 at the stop, Rs 40.08 with costs)",
 "plan": {"entry": 1384.6, "stop": 1377.4, "target": 1399.0, "risk_per_share": 7.2, "max_loss": 40.08,
          "gross_loss": 36.0, "costs_at_stop": 4.08, "costs_at_target": 4.12, "net_gain": 67.88,
          "net_reward_risk": 1.69, "setup": "orb", "entry_time": "9:35 AM", "flat_by": "15:15"}}
```

`why` and `plan` are notes for trader-risk and trader-broker, not part of the
order. With the stop at 380.00 instead, one share would risk 1,004.60, more
than the Rs 200 max loss: no order. If the price is 1392.00 by 9:40, half
the move is gone: 7.00 to the target against 14.60 to the stop, reward:risk
0.40 after costs: refused.

## Rules

- Proposals only. This skill never talks to a broker.
- Never size money the user has not said is for this. Ask for the budget and the max loss.
- Every number comes from the config, the plan or the prices. Nothing is guessed.
- No projections: never say what a trade will make. A target is a plan, not a forecast.
- Prices come from trader-alerts' Fyers quotes. A Yahoo price is used only if it is higher than the
  plan's entry (bigger risk), and the size says it runs behind. The broker's price is the one that fills.
- Costs are estimates from published rates (checked 2026-11-14). Brokers change their charges:
  the contract note is the truth. Auto square-off fees and DP charges are not included.

## What it never does

It never places, approves or schedules an order, never raises a limit on its
own, never shrinks a stop to fit more shares, and never sizes F&O, margin
(MIS leverage) or short positions.

## Safety

- Education and tooling, not financial advice. A PASS is a rules check, not a recommendation. Not SEBI-registered advice.
- Paper trading by default (`"paper": true`): practice, written down, not placed. Going live is the user's own decision, in their own config.
- Nothing in this pack places an order. trader-broker shows a ticket only when trader-risk passed that exact order
  today, and records a yes only when the user typed an explicit yes for that one order in the chat. The user then
  places it themselves, in their own broker's app, and records the result.
- No F&O, margin (MIS leverage), short selling or leverage unless the config allows it and the user confirms.
- Broker logins, passwords, PINs, OTPs and API keys never go in the chat.
