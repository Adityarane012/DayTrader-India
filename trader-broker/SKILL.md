---
name: trader-broker
description: >-
  Order Ticket for the NSE. Turns an order that passed trader-risk into a
  plain ticket you place yourself in your own broker's app (ICICIDirect in
  the example config, or Dhan, Fyers, Angel One, Zerodha, Upstox), with the
  steps to do it: a Super Order on Dhan, or a warning that two separate exit
  orders are not linked. A bracket shows its stop-loss, take-profit and the max loss at the
  stop. Records your yes word for word, then the result you report (placed
  with the broker's order id, skipped, or failed) and the fills, so
  trader-risk can hold the daily limits. Builds the sell ticket that closes a
  day trade by 15:15, before the broker's auto square-off. It never places
  an order and never talks to a broker. Use when the user says "place the
  order", "buy it", "give me the ticket", "how do I enter this in ICICIDirect",
  "close my position", "flatten", "get me out", "I placed it", "it filled",
  or after /trader-risk passes.
argument-hint: "[order number]"
---

# trader-broker

The Order Ticket is the last step before money moves, so it is the strictest.
This pack has no broker connection for India: you place every order
yourself, in your own broker's app. A ticket is shown as ready only after two
gates, every time, for every order:

1. **trader-risk passed this exact order today** (matched by fingerprint).
2. **The user typed an explicit yes for this one order** in the chat.

The third gate is the user's own hands: they place it in the broker's app,
and nothing here can do it for them. Then they report what happened, so the
daily trade and loss limits count it. Day trading loses most people money;
a clean ticket does not change that.

`${CLAUDE_SKILL_DIR}` below is this skill's folder (where this SKILL.md lives).

```bash
python "${CLAUDE_SKILL_DIR}/ticket.py" show                     # every ticket, READY or not
python "${CLAUDE_SKILL_DIR}/ticket.py" approve --index 1 --reply "yes"
python "${CLAUDE_SKILL_DIR}/ticket.py" result --index 1 --status placed --broker-id ID --filled-qty 5 --filled-price 1384.70
python "${CLAUDE_SKILL_DIR}/ticket.py" result --index 1 --status skipped --note "moved too fast"
python "${CLAUDE_SKILL_DIR}/ticket.py" fill --symbol HCLTECH --side sell --qty 5 --price 1399.00
python "${CLAUDE_SKILL_DIR}/ticket.py" flatten --symbol HCLTECH --qty 5
python "${CLAUDE_SKILL_DIR}/ticket.py" log
```

`ticket.py` never talks to a broker. It renders tickets, checks that a reply
is a real yes for that order, builds the flatten ticket, and keeps the log in
`trader/state/broker.json`. `--now "2026-11-13 09:36"` pins the clock (India time).

## What it reads and writes

| file | what |
| --- | --- |
| `trader/orders.json` | the proposed orders (trader-budget writes it; `flatten` replaces it) |
| `trader/state/risk.json` | trader-risk's verdicts; only a PASS from today is READY |
| `trader/state/broker.json` | every yes, no, placed, skipped, failed and filled, with each entry's max loss |
| `trader/portfolio.json` | cash and shares, updated by `fill` and by `result --filled-qty` |
| `trader/plan.json` | the flat-by time for `flatten` |
| `trader/config.json` | `broker` (icicidirect, dhan, fyers, angelone, zerodha, upstox) for the steps; `paper` |

## Paper or live

`"paper": true` (the default) means practice. The ticket says to write the
trade down, not to place it, and the fills you record are practice fills.
That is the way to watch the whole pack work for a while before any real
rupee moves. With `"paper": false` the ticket says LIVE and gives the steps
for the broker in the config.

## Placing it in your broker's app

- **Dhan**: one Super Order. Buy, product Intraday, market or
  limit, with the target and the stop loss on the same order. Dhan links the
  two exits: when one fills, the other is canceled.
- **ICICIDirect and any other broker**: use its bracket or OCO order if it has one. If you
  place the two exits as separate sell orders (a stop-loss SL-M and a limit),
  they are NOT linked. The moment one fills, cancel the other, or it sells
  shares you no longer hold and leaves you short.
- Product **Intraday** (MIS) is what a day trade is: the broker squares it off
  itself from about 15:20, for a fee, if you have not. The pack's flat-by is
  15:15 so you get out first, on your own terms.
- The order id your broker shows goes in `result --broker-id`.

## Steps: the entry

1. Run `ticket.py show`. Read the ticket to the user exactly as printed: the
   order in plain words, the stop-loss, the take-profit, the max loss at the
   stop, PAPER or LIVE, and the steps for their broker.
2. Ask for an explicit yes for this one order. Never take "ok", "sure", "go",
   a yes for several orders, or a yes with a condition. Then run `ticket.py
   approve --index N --reply "<their reply, word for word>"`. If it says Not
   recorded, ask again with the ticket.
3. The user places it in their app (or writes it down, on paper). Ask what
   happened, and record it: `result --index N --status placed --broker-id ID`
   (with `--filled-qty` and `--filled-price` when it filled), or `skipped`, or
   `failed`. A placed entry counts toward today's trades and daily loss.

## Steps: while it is open, and out by 15:15

4. Offer `/trader-alerts` for the stop, the target and the flat-by time.
5. When an exit fills (the stop, the target, or a manual sell), record it with
   `ticket.py fill`.
6. At the flat-by time, if it is still open: `ticket.py flatten --symbol SYM`
   writes a sell ticket for the shares in `trader/portfolio.json` (or `--qty`
   from the broker's positions screen). It goes through `/trader-risk` (an
   exit is never blocked by the day limits) and the user's yes like any other.
   In the app, cancel the open stop-loss and target first (or exit the Super
   Order), then sell.

## Example: HCLTECH, Friday 2026-11-13

The bracket from trader-budget, passed by trader-risk at 9:36 AM, with
`"paper": false` and the example config's broker:

```
ORDER 1 of 1, LIVE: real money, you place it, ICICIDirect
  BUY 5 HCLTECH.NS, market, good for today
  stop-loss 1377.40
  take-profit 1399.00
  max loss about Rs 40.08 with Rs 4.08 costs if the stop fills at 1377.40 (it can fill worse in a fast market)
  why: opening-range breakout on HCLTECH.NS: 5 shares, bound by your position cap (5 x 7.20 = Rs 36 at the stop, Rs 40.08 with costs)
  READY: trader-risk PASS, waiting for your yes
  In ICICIDirect: Buy 5 HCLTECH (NSE), product Intraday, Market.
  Use your broker's bracket or OCO order if it has one: target 1399.00, stop loss 1377.40.
  If you place the two exits as separate sell orders (a stop-loss SL-M at 1377.40 and a
  limit at 1399.00, 5 shares each), they are NOT linked: the moment one fills, cancel
  the other, or it sells shares you no longer hold and leaves you short.
  Reply "yes" to take this one order, or "no" to skip it. Nothing is sent from here.
```

The max loss on the ticket is trader-risk's number for this exact order,
costs included. The user says yes, places it, and reports a fill of 5 at
1384.70: cash goes from Rs 10,000 to Rs 3,076.50. A second HCLTECH buy that
day is blocked by trader-risk as a duplicate, and Rs 40.08 of the Rs 500
daily loss is used.

## What it never does

It never places, modifies or cancels an order, never logs in to a broker,
never takes a yes for more than one order, never treats a PASS as a yes, and
never runs from a background watch: nobody is there to say yes.

## Safety

- Education and tooling, not financial advice. A PASS is a rules check, not a recommendation. Not SEBI-registered advice.
- Paper trading by default (`"paper": true`): practice, written down, not placed. Going live is the user's own decision, in their own config.
- Nothing in this pack places an order. trader-broker shows a ticket only when trader-risk passed that exact order
  today, and records a yes only when the user typed an explicit yes for that one order in the chat. The user then
  places it themselves, in their own broker's app, and records the result.
- No F&O, margin (MIS leverage), short selling or leverage unless the config allows it and the user confirms.
- Broker logins, passwords, PINs, OTPs and API keys never go in the chat.
