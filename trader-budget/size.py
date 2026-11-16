#!/usr/bin/env python3
"""Position sizing for trader-budget. Standard library only, no network.

Sizes ONE day trade from trader/plan.json (written by trader-exit) to your
budget and your max loss per trade, in rupees, then writes one bracket order
(entry, stop-loss, take-profit; intraday on the NSE) to trader/orders.json.
It never places anything: trader-risk checks the order and trader-broker
turns it into a ticket you place yourself.

    python size.py                                  # trader/plan.json + trader/config.json
    python size.py --write                          # write trader/orders.json
    python size.py --limit                          # a limit order at the plan's entry
    python size.py --limit 1384.00 --write          # a limit order at 1384.00
    python size.py --now "2026-11-13 09:36" --json  # pin the clock (India time)

How many shares. Whole shares only: NSE equity has no fractional shares.

    shares = floor of the smallest of
      max loss       max_loss_per_trade_inr / risk per share (entry minus stop)
      position cap   budget x max_position_pct / entry
      max order      max_order_inr / entry
      cash           (budget minus the cash buffer) / entry
                     (and no more than the cash in trader/portfolio.json, if you have one)

The entry it sizes at: a limit order's limit price; for a market order the
plan's entry, or the price in trader/prices.json if that is fresh (under 15
minutes old) and higher, because a price that ran up since the plan means a
bigger loss at the same stop. Zero shares (the stop is too far away for your
max loss) is a plain refusal: no order is written. So is a reward:risk under
min_reward_risk (the price ran toward the target since the plan).

Costs. The round trip's charges are part of the sizing: brokerage (the
"costs" preset in the config: "dhan" = the lower of Rs 20 and 0.03 % an order,
"icicidirect_prime_4999" = 0.01 %, "zero", a dict with brokerage_pct and
brokerage_cap, or false to leave costs out), STT 0.025 % of the sell value,
NSE transaction charge 0.00307 % and SEBI fee Rs 10 a crore of turnover, stamp
duty 0.003 % of the buy value, GST 18 % on brokerage + transaction + SEBI. The
max loss per trade is the loss at the stop PLUS the costs, and reward:risk
against min_reward_risk is what is made at the target after costs over that.
A 1R plan on a tight stop usually fails this: costs eat the edge.

Money keys are rupees: max_order_inr, min_order_inr, max_loss_per_trade_inr,
max_daily_loss_inr. A config that still has upstream's *_usd keys is refused
with the names to change, so a dollar number is never read as rupees.
"""

import argparse
import datetime
import json
import math
import os
import sys

# Defaults: config.example.json. Missing keys fall back to these. Money is in rupees.
DEFAULTS = {
    "budget": None,
    "cash_buffer_pct": 10,
    "max_position_pct": 75,
    "max_order_inr": 7500,
    "min_order_inr": 100,
    "max_loss_per_trade_inr": 200,
    "max_daily_loss_inr": 500,
    "max_trades_per_day": 3,
    "max_orders_per_day": 10,
    "min_reward_risk": 1.0,
    "require_stop": True,
    "no_entries_before": "09:30",
    "no_entries_after": "15:00",
    "flat_by": "15:15",
    "broker": "dhan",
    "paper": True,
    "blocked": [],
    "allow_options": False,
    "allow_margin": False,
    "allow_short": False,
}
USD_KEYS = ("max_order_usd", "min_order_usd", "max_loss_per_trade_usd", "max_daily_loss_usd")
EPS = 1e-9
FRESH_MINUTES = 15
SETUP_WORDS = {"orb": "opening-range breakout", "flag": "flag", "bounce": "oversold bounce"}


class SizeError(Exception):
    pass


# ---------------------------------------------------------------- time (India, UTC+5:30)

IST = datetime.timedelta(hours=5, minutes=30)   # India Standard Time: UTC+5:30 all year, no DST



def to_ist(utc):
    """Naive UTC -> naive India time."""
    return utc.replace(tzinfo=None) + IST


def ist_to_utc(local):
    """Naive India time -> naive UTC."""
    return local.replace(tzinfo=None) - IST


def parse_now(text):
    """ISO time -> naive UTC. A time without an offset is taken as India time."""
    if not text:
        return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0, tzinfo=None)
    t = text.strip().replace("Z", "+00:00")
    try:
        dt = datetime.datetime.fromisoformat(t)
    except ValueError:
        raise SizeError("--now wants a time like \"2026-11-13 09:36\" (India) or ...Z (UTC)")
    if dt.tzinfo is None:
        return ist_to_utc(dt)
    return (dt - dt.utcoffset()).replace(tzinfo=None)


def parse_utc(text):
    """"2026-10-19T14:52:13Z" -> naive UTC, or None."""
    if not text:
        return None
    try:
        dt = datetime.datetime.fromisoformat(str(text).strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is not None:
        dt = (dt - dt.utcoffset()).replace(tzinfo=None)
    return dt


def utc_iso(now_utc=None):
    now_utc = now_utc or datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    return now_utc.replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------- inputs

def read_json(path, what):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        raise SizeError("no %s at %s" % (what, path))
    except json.JSONDecodeError as e:
        raise SizeError("%s is not valid JSON: %s" % (path, e))


def load_config(path):
    cfg = dict(DEFAULTS)
    if path and os.path.exists(path):
        doc = read_json(path, "config")
        old = [k for k in USD_KEYS if k in (doc or {})]
        if old:
            raise SizeError("%s still has the upstream dollar keys (%s): this pack reads rupees, rename them "
                            "to %s" % (path, ", ".join(old), ", ".join(k[:-4] + "_inr" for k in old)))
        cfg.update(doc)
    return cfg


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def price_time(doc, sym):
    """When this symbol's price is from: the quote's own time (detail[sym].time), else when it
    was fetched (detail[sym].fetched), else the file's as_of."""
    det = ((doc or {}).get("detail") or {}).get(sym) or {}
    for key in ("time", "fetched"):
        t = parse_utc(det.get(key))
        if t:
            return t
    return parse_utc((doc or {}).get("as_of"))


def fresh_price(doc, sym, now_utc, minutes=FRESH_MINUTES):
    """(price, fetched_utc, fresh) for sym from a prices.json doc, or (None, None, False)."""
    if not isinstance(doc, dict):
        return None, None, False
    p = _f((doc.get("prices") or {}).get(sym))
    if p is None or p <= 0:
        return None, None, False
    t = price_time(doc, sym)
    if t is None:
        return p, None, False
    age = (now_utc - t).total_seconds()
    return p, t, -60 <= age <= minutes * 60


# ---------------------------------------------------------------- money helpers

def nse_symbol(sym):
    """RELIANCE -> RELIANCE.NS; .NS and .BO kept: Yahoo's and this pack's form."""
    s = str(sym).strip().upper()
    return s if s.endswith((".NS", ".BO")) else s + ".NS"


def round_cent(x):
    """Round a price to the cent (half up)."""
    return math.floor(float(x) * 100 + 0.5 + EPS) / 100.0


def shares_for(amount, per_share):
    """Whole shares that fit in amount at per_share, in exact integer paise."""
    u, p = int(round(float(amount) * 100)), int(round(float(per_share) * 100))
    if p <= 0 or u <= 0:
        return 0
    return u // p


def _price(x):
    """1377.40 -> "1377.40": the order file keeps prices as strings."""
    return "%.2f" % round_cent(x)


def _num(x):
    """1250 -> "1250", 1118.13 -> "1118.13" (kept as strings in the order file)."""
    x = round(float(x), 2)
    if abs(x - round(x)) < 0.005:
        return str(int(round(x)))
    return "%.2f" % x


def group_in(whole):
    """Indian digit grouping: 1234567 -> 12,34,567 (lakh and crore)."""
    if len(whole) <= 3:
        return whole
    head, tail = whole[:-3], whole[-3:]
    parts = []
    while len(head) > 2:
        parts.insert(0, head[-2:])
        head = head[:-2]
    if head:
        parts.insert(0, head)
    return ",".join(parts + [tail])


def money(x):
    """Rs 74,768.40; Rs 1,00,000 (no .00); -Rs 46.88. Indian digit grouping."""
    x = round(float(x), 2)
    whole, frac = ("%.2f" % abs(x)).split(".")
    return "%sRs %s%s" % ("-" if x < 0 else "", group_in(whole), "" if frac == "00" else "." + frac)


# ---------------------------------------------------------------- intraday costs (NSE equity)
#
# Statutory charges on an intraday (MIS) equity trade, as published by the brokers' charge
# pages on 2026-11-14 (Dhan, Zerodha, ICICIDirect) and the NSE: STT 0.025 % on the sell side,
# NSE transaction charge 0.00307 % of turnover, SEBI fee Rs 10 a crore, stamp duty 0.003 % on
# the buy side, GST 18 % on brokerage + transaction charge + SEBI fee. Brokerage depends on the
# broker and the plan. DP charges apply to delivery sells only, not intraday. Brokers change
# their charges: check a contract note.
STATUTORY = {"stt_sell_pct": 0.025, "txn_pct": 0.00307, "sebi_per_crore": 10.0, "stamp_buy_pct": 0.003,
             "gst_pct": 18.0}
COST_PRESETS = {
    "dhan": {"label": "Dhan intraday: Rs 20 or 0.03 % an order, whichever is lower",
             "brokerage_pct": 0.03, "brokerage_cap": 20.0},
    "icicidirect_prime_4999": {"label": "ICICIDirect Prime 4999 intraday: 0.01 % an order",
                               "brokerage_pct": 0.01, "brokerage_cap": None},
    "zero": {"label": "no brokerage, statutory charges only", "brokerage_pct": 0.0, "brokerage_cap": None},
}


def cost_model(cfg):
    """The config's "costs": a preset name (dhan by default), a dict with brokerage_pct and
    brokerage_cap, or false / "none" to leave costs out."""
    c = (cfg or {}).get("costs", "dhan")
    if c in (False, None, "none", "off"):
        return None
    if isinstance(c, dict):
        try:
            return {"label": str(c.get("label") or "custom brokerage"), "brokerage_pct": float(c.get("brokerage_pct", 0)),
                    "brokerage_cap": None if c.get("brokerage_cap") is None else float(c["brokerage_cap"])}
        except (TypeError, ValueError):
            raise ValueError("costs wants brokerage_pct (and brokerage_cap) as numbers")
    preset = COST_PRESETS.get(str(c).lower())
    if preset is None:
        raise ValueError("unknown costs preset %r: use %s, or a dict with brokerage_pct and brokerage_cap"
                         % (c, ", ".join(sorted(COST_PRESETS))))
    return preset


def round_trip_costs(qty, buy_price, sell_price, model):
    """Rupees to buy qty at buy_price and sell them at sell_price the same day."""
    if not model or qty <= 0:
        return {"brokerage": 0.0, "stt": 0.0, "transaction": 0.0, "sebi": 0.0, "stamp": 0.0, "gst": 0.0,
                "total": 0.0}
    buy, sell = qty * float(buy_price), qty * float(sell_price)

    def brokerage(value):
        b = value * model["brokerage_pct"] / 100.0
        return min(b, model["brokerage_cap"]) if model["brokerage_cap"] is not None else b
    brk = brokerage(buy) + brokerage(sell)
    stt = sell * STATUTORY["stt_sell_pct"] / 100.0
    txn = (buy + sell) * STATUTORY["txn_pct"] / 100.0
    sebi = (buy + sell) * STATUTORY["sebi_per_crore"] / 1e7
    stamp = buy * STATUTORY["stamp_buy_pct"] / 100.0
    gst = (brk + txn + sebi) * STATUTORY["gst_pct"] / 100.0
    out = {"brokerage": brk, "stt": stt, "transaction": txn, "sebi": sebi, "stamp": stamp, "gst": gst}
    out = {k: round(v, 2) for k, v in out.items()}
    out["total"] = round(brk + stt + txn + sebi + stamp + gst, 2)
    return out


# ---------------------------------------------------------------- plan mode (the default)

def size_trade(plan, cfg, budget=None, limit=None, price=None, cash=None, today=None):
    """Pure function: one plan + your rules -> the sizing (a dict). qty may be 0.

    limit  the limit price for a limit order (None = market)
    price  a FRESH latest price; a market order is sized at the higher of it and the plan's entry
    cash   the cash in trader/portfolio.json, if there is one
    today  India date (YYYY-MM-DD); a plan for another day is refused"""
    c = dict(DEFAULTS)
    c.update(cfg or {})
    if not isinstance(plan, dict):
        raise SizeError("the plan is not a JSON object")
    sym = str(plan.get("symbol") or "").strip().upper()
    if not sym:
        raise SizeError("the plan has no symbol (run trader-exit)")
    sym = nse_symbol(sym)
    side = str(plan.get("side") or "buy").strip().lower()
    if side != "buy":
        raise SizeError("this pack sizes long (buy) day trades only; the plan says %r" % side)
    if today and plan.get("date") and str(plan["date"]) != today:
        raise SizeError("the plan is for %s and today is %s in India: make a new plan with trader-exit"
                        % (plan["date"], today))
    entry_plan, stop, target = _f(plan.get("entry")), _f(plan.get("stop")), _f(plan.get("target"))
    for name, v in (("entry", entry_plan), ("stop", stop), ("target", target)):
        if v is None or v <= 0:
            raise SizeError("the plan needs a positive %s (run trader-exit); a bracket order needs entry, "
                            "stop and target" % name)
    blocked = {nse_symbol(b) for b in (c.get("blocked") or [])}
    if sym in blocked:
        raise SizeError("%s is on your blocked list" % sym)

    budget = float(budget if budget is not None else (c.get("budget") or 0))
    if budget <= 0:
        raise SizeError("no budget: pass --budget or set \"budget\" in trader/config.json")
    buf_pct = float(c.get("cash_buffer_pct") or 0)
    if not 0 <= buf_pct < 100:
        raise SizeError("cash_buffer_pct must be between 0 and 100")

    if limit is not None:
        ref, ref_from = round_cent(limit), "limit"
    elif price is not None and round_cent(price) > round_cent(entry_plan):
        ref, ref_from = round_cent(price), "price"
    else:
        ref, ref_from = round_cent(entry_plan), "plan"
    stop, target = round_cent(stop), round_cent(target)
    if stop >= ref:
        raise SizeError("the stop %s is not below the entry %s; a long trade needs its stop underneath"
                        % (_price(stop), _price(ref)))
    if target <= ref:
        raise SizeError("the target %s is not above the entry %s: the move has already happened. "
                        "Skip it or make a new plan with trader-exit" % (_price(target), _price(ref)))
    risk_c = int(round((ref - stop) * 100))
    reward_c = int(round((target - ref) * 100))
    risk = risk_c / 100.0

    cash_buffer = round(budget * buf_pct / 100.0, 2)
    available = budget - cash_buffer
    cash_note = "budget %s minus the %s cash buffer" % (money(budget), money(cash_buffer))
    if cash is not None and cash - cash_buffer < available - 0.005:
        available = cash - cash_buffer
        cash_note = "cash %s in trader/portfolio.json minus the %s buffer" % (money(cash), money(cash_buffer))
    available = max(round(available, 2), 0.0)

    try:
        model = cost_model(c)
    except ValueError as e:
        raise SizeError(str(e))

    def net_loss_of(n):
        """What n shares lose if the stop fills at the stop: the risk plus the round trip's costs."""
        return round(n * risk_c / 100.0 + round_trip_costs(n, ref, stop, model)["total"], 2)

    limits = []
    max_loss = _f(c.get("max_loss_per_trade_inr"))
    if max_loss:
        n = shares_for(max_loss, risk)
        while n > 0 and net_loss_of(n) > max_loss + 0.005:
            n -= 1                          # costs come out of the same max loss
        limits.append({"name": "max loss", "inr": max_loss, "per": risk, "shares": n,
                       "how": "%s max loss / (%s risk a share%s)" % (money(max_loss), _price(risk),
                                                                   " + costs" if model else "")})
    cap_pct = _f(c.get("max_position_pct"))
    if cap_pct:
        cap = round(budget * cap_pct / 100.0, 2)
        limits.append({"name": "position cap", "inr": cap, "per": ref, "shares": shares_for(cap, ref),
                       "how": "%s%% of %s = %s / %s" % (_num(cap_pct), money(budget), money(cap), _price(ref))})
    max_order = _f(c.get("max_order_inr"))
    if max_order:
        limits.append({"name": "max order", "inr": max_order, "per": ref, "shares": shares_for(max_order, ref),
                       "how": "%s / %s" % (money(max_order), _price(ref))})
    limits.append({"name": "cash", "inr": available, "per": ref, "shares": shares_for(available, ref),
                   "how": "%s = %s / %s" % (cash_note, money(available), _price(ref))})

    qty = max(0, min(l["shares"] for l in limits))
    bound = [l["name"] for l in limits if l["shares"] == qty]
    for l in limits:
        l["binds"] = l["name"] == bound[0]
    cost = round(qty * ref, 2)
    gross_loss = round(qty * risk_c / 100.0, 2)
    gross_gain = round(qty * reward_c / 100.0, 2)
    costs_stop = round_trip_costs(qty, ref, stop, model)
    costs_target = round_trip_costs(qty, ref, target, model)
    loss = round(gross_loss + costs_stop["total"], 2)          # what the trade really loses at the stop
    net_gain = round(gross_gain - costs_target["total"], 2)    # what it really makes at the target
    gross_rr = reward_c / float(risk_c)
    net_rr = (net_gain / loss) if loss > 0 else gross_rr
    refusal = None
    if qty == 0:
        if bound[0] == "max loss":
            refusal = ("one share risks %s (entry %s minus stop %s)%s, more than your %s max loss per trade. "
                       "No order. Skip this trade, or plan a closer stop with trader-exit."
                       % (money(risk), _price(ref), _price(stop),
                          (" plus %s costs" % money(round_trip_costs(1, ref, stop, model)["total"])) if model else "",
                          money(max_loss)))
        else:
            refusal = ("one share of %s costs %s, more than your %s limit (%s). No order."
                       % (sym, money(ref), bound[0], limits[[l["name"] for l in limits].index(bound[0])]["how"]))
    elif _f(c.get("min_reward_risk")) and net_rr < _f(c["min_reward_risk"]) - EPS:
        after = "" if not model else (" after costs (%s made at the target, %s lost at the stop; %.2f before costs)"
                                      % (money(net_gain), money(loss), gross_rr))
        refusal = ("reward:risk %.2f%s (target %s, entry %s, stop %s) is under your minimum %s, so trader-risk "
                   "would block it. No order. Skip it, or make a new plan with trader-exit%s."
                   % (net_rr, after, _price(target), _price(ref), _price(stop), _num(c["min_reward_risk"]),
                      " (a farther target)" if model and gross_rr >= _f(c["min_reward_risk"]) else ""))
    elif cost < float(c.get("min_order_inr") or 0) - 0.005:
        refusal = ("%d share%s of %s is %s, under your %s minimum order. No order."
                   % (qty, "" if qty == 1 else "s", sym, money(cost), money(c["min_order_inr"])))
    return {
        "symbol": sym, "side": "buy", "setup": plan.get("setup", ""), "date": plan.get("date"),
        "entry_time": plan.get("entry_time", ""), "entry_plan": round_cent(entry_plan),
        "entry": ref, "entry_from": ref_from, "stop": stop, "target": target,
        "risk_per_share": risk, "reward_risk": round(reward_c / float(risk_c), 2),
        "stop_label": plan.get("stop_label", ""), "target_label": plan.get("target_label", ""),
        "budget": budget, "cash_buffer_pct": buf_pct, "cash_buffer": cash_buffer, "cash_available": available,
        "max_loss_per_trade_inr": max_loss, "limits": limits, "qty": qty, "bound_by": bound[0],
        "cost": cost, "max_loss": loss, "gross_loss": gross_loss, "gross_gain": gross_gain, "net_gain": net_gain,
        "costs_at_stop": costs_stop["total"], "costs_at_target": costs_target["total"],
        "costs_detail": costs_target, "costs": model["label"] if model else None,
        "net_reward_risk": round(net_rr, 2), "flat_by": plan.get("flat_by") or c.get("flat_by"),
        "order_type": "limit" if limit is not None else "market", "refusal": refusal,
    }


def bracket_order(s):
    """The one proposed order: a bracket (entry, stop-loss, take-profit) in the order file's
    fields (strings), plus why and the plan. trader-broker turns it into a ticket for your broker."""
    if s["refusal"] or s["qty"] <= 0:
        return None
    o = {"symbol": s["symbol"], "side": "buy", "qty": str(int(s["qty"])), "type": s["order_type"],
         "time_in_force": "day"}
    if s["order_type"] == "limit":
        o["limit_price"] = _price(s["entry"])
    setup = SETUP_WORDS.get(s["setup"], s["setup"] or "day trade")
    why = ("%s on %s: %d shares, bound by your %s (%d x %s = %s at the stop%s)"
           % (setup, s["symbol"], s["qty"], {"max loss": "%s max loss per trade" % money(s["max_loss_per_trade_inr"] or 0),
                                             "position cap": "position cap", "max order": "max order",
                                             "cash": "cash after the buffer"}[s["bound_by"]],
              s["qty"], _price(s["risk_per_share"]), money(s["gross_loss"]),
              (", %s with costs" % money(s["max_loss"])) if s["costs"] else ""))
    o.update({
        "order_class": "bracket",
        "take_profit_limit_price": _price(s["target"]),
        "stop_loss_stop_price": _price(s["stop"]),
        "why": why,
        "plan": {"entry": s["entry"], "stop": s["stop"], "target": s["target"],
                 "risk_per_share": s["risk_per_share"], "max_loss": s["max_loss"],
                 "gross_loss": s["gross_loss"], "costs_at_stop": s["costs_at_stop"],
                 "costs_at_target": s["costs_at_target"], "net_gain": s["net_gain"],
                 "net_reward_risk": s["net_reward_risk"], "setup": s["setup"],
                 "entry_time": s["entry_time"], "flat_by": s["flat_by"]},
    })
    return o


def plan_report(s, order, notes=()):
    lines = []
    setup = SETUP_WORDS.get(s["setup"], s["setup"] or "setup")
    lines.append("%s buy, %s, entry %s%s" % (s["symbol"], setup, _price(s["entry_plan"]),
                                            (" at " + s["entry_time"]) if s["entry_time"] else ""))
    lines.append("Stop %s%s. Target %s%s." % (_price(s["stop"]), (": " + s["stop_label"]) if s["stop_label"] else "",
                                             _price(s["target"]),
                                             (": " + s["target_label"]) if s["target_label"] else ""))
    for n in notes:
        lines.append(n)
    src = {"plan": "the plan's entry", "price": "the latest price, above the plan's entry",
           "limit": "your limit price"}[s["entry_from"]]
    lines.append("Sized at %s (%s). Risk %s a share (entry %s minus stop %s). Reward:risk %.2f."
                 % (_price(s["entry"]), src, _price(s["risk_per_share"]), _price(s["entry"]), _price(s["stop"]),
                    s["reward_risk"]))
    lines.append("")
    lines.append("Limits (whole shares; the smallest one wins):")
    for l in s["limits"]:
        lines.append("  %-13s %-72s %3d shares%s" % (l["name"], l["how"], l["shares"],
                                                      "  <- binds" if l["binds"] else ""))
    lines.append("")
    if order is None:
        lines.append("No order: " + s["refusal"])
        lines.append("Education and tooling, not financial advice.")
        return "\n".join(lines)
    lines.append("Size: %d shares of %s = %s at %s. At the stop: %d x %s = %s."
                 % (s["qty"], s["symbol"], money(s["cost"]), _price(s["entry"]), s["qty"],
                    _price(s["risk_per_share"]), money(s["gross_loss"])))
    if s["costs"]:
        d = s["costs_detail"]
        lines.append("Costs for the round trip, about %s (%s): brokerage %s, STT %s, exchange and SEBI %s, "
                     "stamp duty %s, GST %s."
                     % (money(s["costs_at_target"]), s["costs"], money(d["brokerage"]), money(d["stt"]),
                        money(round(d["transaction"] + d["sebi"], 2)), money(d["stamp"]), money(d["gst"])))
        lines.append("After costs: max loss %s at the stop, %s made at the target, reward:risk %.2f (%.2f before costs)."
                     % (money(s["max_loss"]), money(s["net_gain"]), s["net_reward_risk"], s["reward_risk"]))
    lines.append("A stop is an order, not a promise: in a fast market it can fill below %s." % _price(s["stop"]))
    lines.append("")
    lines.append("Proposed bracket order (intraday, NSE; nothing has been placed):")
    how = "limit %s" % order["limit_price"] if order["type"] == "limit" else "market"
    lines.append("  buy %s %s, %s, day, take-profit %s, stop-loss %s"
                 % (order["qty"], order["symbol"], how, order["take_profit_limit_price"],
                    order["stop_loss_stop_price"]))
    if s["flat_by"]:
        lines.append("Flat by %s IST: anything still open then gets closed, before the broker's auto "
                     "square-off (trader-alerts rings, trader-broker flatten)." % s["flat_by"])
    lines.append("")
    lines.append("Next: trader-risk checks it, then trader-broker asks you yes or no.")
    lines.append("Education and tooling, not financial advice.")
    return "\n".join(lines)


# ---------------------------------------------------------------- orders file

def write_orders(path, orders, cfg, source="", now_utc=None):
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    doc = {
        "created_by": "trader-budget",
        "created_at": utc_iso(now_utc),
        "status": "proposed",
        "paper": bool(cfg.get("paper", True)),
        "note": ("Proposals only. Nothing is placed until trader-risk passes each order "
                 "and you say yes to it in the chat."),
        "source": source,
        "orders": orders,
    }
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=2)
        fh.write("\n")
    os.replace(tmp, path)


# ---------------------------------------------------------------- main

def run_plan(a, cfg):
    now = parse_now(a.now)
    today = to_ist(now).date().isoformat()
    plan = read_json(a.plan, "plan (run trader-exit first)")
    limit = None
    if a.limit is not None:
        if a.limit == "plan":
            limit = _f((plan or {}).get("entry"))
        else:
            limit = _f(a.limit)
            if limit is None or limit <= 0:
                raise SizeError("--limit wants a price, like --limit 1384.00")
    sym = nse_symbol((plan or {}).get("symbol") or "") if (plan or {}).get("symbol") else ""
    notes, price = [], None
    ppath = a.prices or ("trader/prices.json" if os.path.exists("trader/prices.json") else None)
    if ppath and limit is None and sym:
        pdoc = read_json(ppath, "prices")
        p, t, fresh = fresh_price(pdoc, sym, now)
        if p is not None and fresh:
            price = p
            src = (((pdoc or {}).get("detail") or {}).get(sym) or {}).get("source")
            if src == "yahoo":
                notes.append("%s's price in %s is Yahoo's, which runs behind: get a Fyers quote "
                             "(trader-alerts: alerts.py quote %s --write) before you trust this size."
                             % (sym, ppath, sym[:-3]))
            if round_cent(p) > round_cent(_f(plan.get("entry")) or 0):
                notes.append("%s last %s (as of %s IST) is above the plan's entry %s, so the risk "
                             "is bigger: sized at %s." % (sym, _price(p), to_ist(t).strftime("%H:%M"),
                                                          _price(plan.get("entry")), _price(p)))
        elif p is not None:
            notes.append("%s in %s is %s: not used (older than %d minutes). Sized at the plan's entry."
                         % (sym, ppath, ("from " + to_ist(t).strftime("%Y-%m-%d %H:%M") + " IST")
                            if t else "undated", FRESH_MINUTES))
    cash = None
    if a.portfolio and os.path.exists(a.portfolio):
        pf = read_json(a.portfolio, "portfolio")
        cash = _f(pf.get("cash")) if isinstance(pf, dict) else None
    s = size_trade(plan, cfg, a.budget, limit, price, cash, today)
    order = bracket_order(s)
    if order and a.write:
        src = "trader/plan.json (%s %s %s)" % (s["symbol"], s["setup"] or "plan", s["date"] or today)
        write_orders(a.write, [order], cfg, src, now)
    if a.json:
        print(json.dumps({"sizing": s, "orders": [order] if order else [], "notes": notes}, indent=2))
    else:
        print(plan_report(s, order, notes))
        if order and a.write:
            print("Wrote 1 proposed bracket order to %s" % a.write)
    return 0 if order else 1


def main(argv=None):
    ap = argparse.ArgumentParser(description="Size a day trade to your budget and max loss (trader-budget).")
    ap.add_argument("--plan", default="trader/plan.json", help="the trade plan (default trader/plan.json)")
    ap.add_argument("--config", default="trader/config.json", help="rules (default trader/config.json)")
    ap.add_argument("--budget", type=float, help="override the budget in the config")
    ap.add_argument("--limit", nargs="?", const="plan", metavar="PRICE",
                    help="a limit order instead of market, at the plan's entry or at PRICE")
    ap.add_argument("--prices", help="prices JSON (default trader/prices.json if it exists)")
    ap.add_argument("--portfolio", default="trader/portfolio.json",
                    help="your account; its cash caps the size if it exists")
    ap.add_argument("--now", help="pretend it is this India time, e.g. \"2026-11-13 09:36\"")
    ap.add_argument("--write", nargs="?", const="trader/orders.json", metavar="PATH",
                    help="write the proposed order (default trader/orders.json)")
    ap.add_argument("--json", action="store_true", help="print JSON instead of the report")
    a = ap.parse_args(argv)
    try:
        cfg = load_config(a.config)
        return run_plan(a, cfg)
    except SizeError as e:
        print("size.py: %s" % e, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
