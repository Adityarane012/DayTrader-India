"""trader-risk tests. Fixtures in tests/fixtures/trader-risk/:

orders-hcl.json        the bracket order trader-budget writes for the worked example
                       (HCLTECH.NS, Fri Nov 13 2026: 5 shares, entry 1384.60, stop
                       1377.40, 2R target 1399.00, Rs 40.08 at the stop with costs),
                       from test_budget's chain. Costs are hand-checked in test_budget.
orders-longterm.json   five whole-share buys at real Nov 13 2026 NSE closes, no stops,
                       for the long-term checks with the day-trade checks off.
"""

import datetime
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr

from _load import load, ROOT, FIX

check = load("trader-risk", "check")
ticket = load("trader-broker", "ticket")

CFG_PATH = os.path.join(ROOT, "trader-budget", "config.example.json")
HCL_PATH = os.path.join(FIX, "trader-risk", "orders-hcl.json")
LT_PATH = os.path.join(FIX, "trader-risk", "orders-longterm.json")
NOW = "2026-11-13 09:36"
TODAY = "2026-11-13"
PRICES = {"RELIANCE.NS": 1339.70, "TCS.NS": 2407.50, "INFY.NS": 1141.50, "ITC.NS": 285.00, "SBIN.NS": 1080.00}
QUOTE_TIME = datetime.datetime(2026, 11, 13, 4, 8, 0)     # a 1386.00 quote at 09:38 IST
# long-term rules with every day-trade check switched off
LT = {"budget": 100000, "cash_buffer_pct": 10, "max_position_pct": 25, "max_order_inr": 20000, "min_order_inr": 100,
      "max_orders_per_day": 10, "require_stop": False, "no_entries_before": None, "no_entries_after": None,
      "max_trades_per_day": 0, "max_daily_loss_inr": 0, "max_loss_per_trade_inr": 0, "min_reward_risk": 0}


def at(text):
    return check.parse_now(text)


def cfg(**over):
    with open(CFG_PATH) as fh:
        c = json.load(fh)
    c.update(over)
    return c


def lt(**over):
    c = dict(LT)
    c.update(over)
    return c


def hcl(**over):
    with open(HCL_PATH) as fh:
        o = json.load(fh)["orders"][0]
    o.update(over)
    return o


def bracket(sym, qty, entry, stop, target):
    return {"symbol": sym, "side": "buy", "qty": str(qty), "type": "market", "time_in_force": "day",
            "order_class": "bracket", "take_profit_limit_price": "%.2f" % target,
            "stop_loss_stop_price": "%.2f" % stop,
            "plan": {"entry": entry, "stop": stop, "target": target}}


def lt_orders():
    with open(LT_PATH) as fh:
        return json.load(fh)["orders"]


def buy(sym, qty):
    return {"symbol": sym, "side": "buy", "qty": str(qty), "type": "market", "time_in_force": "day"}


def placed(sym, side="buy", day=TODAY, max_loss=40.08, kind=None, status="placed"):
    r = {"symbol": sym, "side": side, "status": status, "date": day, "at": day + "T09:40:00+05:30"}
    if max_loss is not None:
        r["max_loss"] = max_loss
    if kind:
        r["kind"] = kind
    return r


def verdicts(res):
    return [r["verdict"] for r in res["results"]]


def reasons(res, i=0):
    return " | ".join(res["results"][i]["reasons"])


def warnings(res, i=0):
    return " | ".join(res["results"][i]["warnings"])


class TheExample(unittest.TestCase):
    def test_the_hcltech_bracket_passes_every_check(self):
        res = check.check([hcl()], cfg(), now=at(NOW))
        r = res["results"][0]
        self.assertEqual(r["verdict"], "PASS", r["reasons"])
        self.assertEqual(r["reasons"], [])
        self.assertEqual(r["warnings"], [])
        self.assertEqual((r["symbol"], r["kind"], r["entry_ref"], r["stop"], r["target"]),
                         ("HCLTECH.NS", "entry", 1384.6, 1377.4, 1399.0))
        self.assertEqual((r["risk_per_share"], r["gross_loss"], r["costs_at_stop"], r["max_loss"]),
                         (7.2, 36.0, 4.08, 40.08))                # 5 x 7.20, plus the round trip's costs
        self.assertEqual((r["reward_risk"], r["net_reward_risk"]), (2.0, 1.69))   # (72.00 - 4.12) / 40.08
        self.assertEqual(r["value_inr"], 6923.0)
        self.assertEqual(res["cash_after"], 3077.0)
        self.assertEqual(res["date"], TODAY)
        self.assertIs(res["paper"], True)

    def test_6_shares_is_over_the_position_cap_and_the_max_order(self):
        res = check.check([hcl(qty="6")], cfg(), now=at(NOW))
        self.assertEqual(verdicts(res), ["BLOCK"])
        self.assertEqual(res["results"][0]["reasons"],
                         ["size: Rs 8,307.60 is over your Rs 7,500 max order",
                          "position: HCLTECH.NS would be Rs 8,307.60, 83.1% of the Rs 10,000 account, over your 75% cap"])

    def test_25_shares_is_blocked_by_the_max_loss_with_costs(self):
        big = cfg(budget=60000, max_order_inr=60000, max_position_pct=100)
        res = check.check([hcl(qty="25")], big, now=at(NOW))
        # 25 x 7.20 = 180 is under Rs 200 on its own; the costs take it over
        self.assertEqual(res["results"][0]["reasons"],
                         ["loss: 25 shares x 7.20 risk a share = Rs 180 at the stop + Rs 20.38 costs = Rs 200.38, "
                          "over your Rs 200 max loss per trade"])
        self.assertEqual(verdicts(check.check([hcl(qty="24")], big, now=at(NOW))), ["PASS"])
        self.assertEqual(verdicts(check.check([hcl(qty="25")], dict(big, costs=False), now=at(NOW))), ["PASS"])

    def test_costs_can_be_switched_off_or_changed(self):
        r = check.check([hcl()], cfg(costs=False), now=at(NOW))["results"][0]
        self.assertEqual((r["max_loss"], r["costs_at_stop"], r["net_reward_risk"]), (36.0, 0.0, 2.0))
        self.assertIn("max loss Rs 36 (limit Rs 200), reward:risk 2.00 (min 1)", r["info"])
        r = check.check([hcl()], cfg(costs="dhan"), now=at(NOW))["results"][0]
        self.assertEqual((r["max_loss"], r["net_reward_risk"]), (43.33, 1.49))
        with self.assertRaises(check.RiskError):
            check.check([hcl()], cfg(costs="kite"), now=at(NOW))

    def test_fingerprint_is_shared_with_the_broker(self):
        o = hcl()
        self.assertEqual(check.fingerprint(o), ticket.fingerprint(o))
        self.assertEqual(check.fingerprint(dict(o, why="anything", plan={})), check.fingerprint(o))
        self.assertNotEqual(check.fingerprint(dict(o, qty="6")), check.fingerprint(o))
        self.assertNotEqual(check.fingerprint(dict(o, stop_loss_stop_price="1377.00")), check.fingerprint(o))
        self.assertEqual(check.ORDER_FIELDS, ticket.ORDER_FIELDS)

    def test_dollar_keys_are_refused(self):
        with self.assertRaises(check.RiskError) as cm:
            check.check([hcl()], {"budget": 100000, "max_order_usd": 4000}, now=at(NOW))
        self.assertIn("max_order_usd", str(cm.exception))
        self.assertIn("max_order_inr", str(cm.exception))

    def test_cli(self):
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "state", "risk.json")
            none = os.path.join(d, "none")
            buf = io.StringIO()
            with redirect_stdout(buf):
                code = check.main(["--orders", HCL_PATH, "--config", CFG_PATH, "--portfolio", none,
                                   "--prices", none, "--state", none, "--now", NOW, "--out", out])
            text = buf.getvalue()
            self.assertEqual(code, 0)
            self.assertIn("PASS  #1 buy HCLTECH.NS 5 shares, entry", text)
            self.assertIn("entry 1384.60 (the plan's entry), stop 1377.40, target 1399.00: risk 7.20 a share", text)
            self.assertIn("max loss Rs 40.08 with costs (Rs 36 at the stop + Rs 4.08 costs) (limit Rs 200), "
                          "reward:risk 1.69 after costs, 2.00 before (min 1)", text)
            self.assertIn("1 passed, 0 blocked at 2026-11-13 09:36 IST. Cash after the passed orders: "
                          "Rs 3,077 (paper account)", text)
            self.assertIn("not financial advice", text)
            with open(out) as fh:
                rec = json.load(fh)
            self.assertEqual(rec["date"], TODAY)
            self.assertEqual(rec["results"][0]["kind"], "entry")
            self.assertEqual(rec["results"][0]["fingerprint"], check.fingerprint(hcl()))


class DayTradeChecks(unittest.TestCase):
    def one(self, order, now=NOW, **over):
        return check.check([order], cfg(**over), now=at(now))

    def test_a_stop_is_required(self):
        o = hcl()
        for k in ("order_class", "take_profit_limit_price", "stop_loss_stop_price", "plan"):
            o.pop(k)
        o["plan"] = {"entry": 1384.60}
        res = self.one(o)
        self.assertIn("stop: no stop", reasons(res))
        res = self.one(o, require_stop=False, min_reward_risk=0)
        self.assertEqual(verdicts(res), ["PASS"])
        self.assertIn("no stop", warnings(res))

    def test_a_plan_stop_counts_but_warns(self):
        o = hcl()
        for k in ("order_class", "take_profit_limit_price", "stop_loss_stop_price"):
            o.pop(k)
        res = self.one(o)
        self.assertEqual(verdicts(res), ["PASS"])
        self.assertIn("in the plan only", warnings(res))
        self.assertEqual(res["results"][0]["max_loss"], 40.08)

    def test_stop_and_target_on_the_right_side(self):
        self.assertIn("must be below the entry 1384.60", reasons(self.one(hcl(stop_loss_stop_price="1385.00"))))
        res = self.one(hcl(take_profit_limit_price="1384.00"))
        self.assertIn("target: the target 1384.00 must be above the entry 1384.60", reasons(res))

    def test_reward_risk(self):
        # a 1R target: 36.00 - 4.10 made against 40.08 lost
        res = self.one(hcl(take_profit_limit_price="1391.80"))
        self.assertEqual(res["results"][0]["reasons"],
                         ["reward:risk: 0.80 after costs, 1.00 before (target 1391.80, entry 1384.60, stop 1377.40) "
                          "is under your minimum 1"])
        self.assertEqual(verdicts(self.one(hcl(take_profit_limit_price="1391.80"), min_reward_risk=0.5)), ["PASS"])
        self.assertEqual(verdicts(self.one(hcl(take_profit_limit_price="1391.80"), costs=False)), ["PASS"])

    def test_a_fresh_higher_price_is_the_entry(self):
        later = at("2026-11-13 09:40")
        res = check.check([hcl()], cfg(), prices={"HCLTECH.NS": 1386.0}, now=later,
                          price_times={"HCLTECH.NS": QUOTE_TIME})
        r = res["results"][0]
        self.assertEqual((r["entry_ref"], r["entry_ref_from"], r["risk_per_share"], r["max_loss"]),
                         (1386.0, "price", 8.6, 47.08))
        self.assertEqual((r["verdict"], r["reward_risk"], r["net_reward_risk"]), ("PASS", 1.51, 1.29))
        self.assertIn("HCLTECH.NS last 1386.00 is above the plan's entry 1384.60", " ".join(r["info"]))

    def test_a_stale_or_future_price_is_not_used(self):
        for now in ("2026-11-13 10:00", "2026-11-13 09:36"):
            res = check.check([hcl()], cfg(), prices={"HCLTECH.NS": 1386.0}, now=at(now),
                              price_times={"HCLTECH.NS": QUOTE_TIME})
            self.assertEqual(verdicts(res), ["PASS"], now)
            self.assertEqual(res["results"][0]["entry_ref"], 1384.6)
            self.assertIn("older than 15 minutes", warnings(res))

    def test_a_lower_price_does_not_shrink_the_risk(self):
        res = check.check([hcl()], cfg(), prices={"HCLTECH.NS": 1380.00}, now=at(NOW))
        self.assertEqual(res["results"][0]["entry_ref"], 1384.6)

    def test_a_limit_order_uses_its_limit_price(self):
        o = hcl(type="limit", limit_price="1384.00")
        res = check.check([o], cfg(), prices={"HCLTECH.NS": 1386.0}, now=at(NOW))
        r = res["results"][0]
        self.assertEqual((r["entry_ref"], r["gross_loss"], r["max_loss"], r["verdict"]), (1384.0, 33.0, 37.08, "PASS"))

    def test_daily_loss_and_trades_per_day(self):
        two = {"orders": [placed("INFY.NS"), placed("TCS.NS")]}
        res = check.check([hcl()], cfg(), state=two, now=at(NOW))
        self.assertEqual(verdicts(res), ["PASS"])
        self.assertIn("today before this: 2 of 3 trades, Rs 80.16 of Rs 500 daily loss", res["results"][0]["info"][-1])
        three = {"orders": [placed("INFY.NS", max_loss=200), placed("TCS.NS", max_loss=150),
                            placed("SBIN.NS", max_loss=150)]}
        res = check.check([hcl()], cfg(), state=three, now=at(NOW))
        why = reasons(res)
        self.assertIn("trades: 3 entries placed today", why)
        self.assertIn("daily loss: Rs 500 already at risk today plus Rs 40.08 for this one = Rs 540.08, over "
                      "your Rs 500 daily loss limit", why)
        yesterday = {"orders": [placed(s, day="2026-11-12") for s in ("INFY.NS", "TCS.NS", "SBIN.NS")]}
        self.assertEqual(verdicts(check.check([hcl()], cfg(), state=yesterday, now=at(NOW))), ["PASS"])

    def test_exits_and_declines_do_not_count_as_trades(self):
        st = {"orders": [placed("INFY.NS"), placed("INFY.NS", side="sell", kind="exit", max_loss=None),
                         placed("TCS.NS", status="declined"), placed("SBIN.NS", status="failed")]}
        res = check.check([hcl()], cfg(), state=st, now=at(NOW))
        self.assertEqual(verdicts(res), ["PASS"])
        self.assertEqual(res["today"]["entries_placed"], 1)

    def test_the_batch_counts_toward_the_daily_limits(self):
        orders = [bracket(s, 1, 500.0, 460.0, 580.0) for s in ("AAA", "BBB", "CCC", "DDD")]   # Rs 40.28 each with costs
        res = check.check(orders, cfg(max_daily_loss_inr=150), now=at(NOW))
        self.assertEqual(verdicts(res), ["PASS", "PASS", "PASS", "BLOCK"])
        why = reasons(res, 3)
        self.assertIn("trades: 0 entries placed today plus 3 passed earlier", why)
        self.assertIn("daily loss: Rs 120.84 already at risk today plus Rs 40.28 for this one = Rs 161.12", why)

    def test_entry_window_india_time(self):
        cases = [("2026-11-13 09:29", "no new entries before 09:30 IST (it is 09:29)"),
                 ("2026-11-13 15:01", "no new entries after 15:00 IST (it is 15:01)"),
                 ("2026-11-13 09:00", "the market is closed (Fri 2026-11-13 09:00 IST; the session is 09:15 to 15:30)"),
                 ("2026-11-13 15:35", "the market is closed"),
                 ("2026-11-14 10:15", "the market is closed today (weekend"),
                 ("2026-11-10 10:15", "the market is closed today (NSE holiday: Diwali-Balipratipada"),
                 ("2026-11-24 10:15", "the market is closed today (NSE holiday: Prakash Gurpurb"),
                 ("2026-11-13T03:59:00Z", "no new entries before 09:30 IST (it is 09:29)")]
        for now, want in cases:
            res = self.one(hcl(), now=now)
            self.assertIn("window: " + want, reasons(res), now)
        for now in ("2026-11-13 09:30", "2026-11-13 15:00", "2026-11-13T04:00:00Z", "2026-11-26 10:15",
                    "2026-12-24 14:59", "2026-07-07T04:06:00Z"):
            self.assertEqual(verdicts(self.one(hcl(), now=now)), ["PASS"], now)
        res = self.one(hcl(), now="2026-11-14 10:15", no_entries_before=None, no_entries_after=None)
        self.assertEqual(verdicts(res), ["PASS"])
        self.assertIn("NSE holiday list", " ".join(self.one(hcl(), now="2027-01-04 10:00")["warnings"]))
        with self.assertRaises(check.RiskError):
            self.one(hcl(), no_entries_before="9.30am")

    def test_the_window_uses_india_time_not_the_machine(self):
        self.assertEqual(check.to_ist(at("2026-11-13 09:36")), datetime.datetime(2026, 11, 13, 9, 36))
        self.assertEqual(at("2026-11-13 09:36"), datetime.datetime(2026, 11, 13, 4, 6))
        self.assertEqual(at("2026-07-01 09:36"), datetime.datetime(2026, 7, 1, 4, 6))     # no DST

    def test_there_is_no_pdt_rule(self):
        def trade(day):
            return [placed("X" + day[-2:], day=day), placed("X" + day[-2:], side="sell", day=day, kind="exit",
                                                            status="filled", max_loss=None)]
        st = {"orders": trade("2026-11-09") + trade("2026-11-11") + trade("2026-11-12")}
        res = check.check([hcl()], cfg(pdt_guard=True), state=st, now=at(NOW))
        self.assertEqual(verdicts(res), ["PASS"])
        self.assertNotIn("day_trades_5d", res["today"])
        self.assertFalse(hasattr(check, "day_trades"))

    def test_a_short_entry_when_allowed(self):
        short = {"symbol": "HCLTECH.NS", "side": "sell", "qty": "5", "type": "market", "time_in_force": "day",
                 "order_class": "bracket", "take_profit_limit_price": "1370.20", "stop_loss_stop_price": "1391.80",
                 "plan": {"entry": 1384.60}}
        res = self.one(short)
        self.assertIn("short: selling more HCLTECH.NS than you hold", reasons(res))
        res = self.one(short, allow_short=True)
        r = res["results"][0]
        self.assertEqual((r["verdict"], r["kind"], r["max_loss"], r["reward_risk"]), ("PASS", "entry", 40.1, 2.0))
        res = self.one(dict(short, stop_loss_stop_price="1380.00"), allow_short=True)
        self.assertIn("must be above the entry 1384.60 for a sell", reasons(res))

    def test_nse_order_format(self):
        self.assertIn("notional (rupee amount) order is not supported",
                      reasons(self.one(dict(hcl(qty=None), notional="74768"))))
        self.assertIn("whole shares only", reasons(self.one(hcl(qty="5.5"))))
        self.assertIn("needs time_in_force day", reasons(self.one(hcl(time_in_force="ioc"))))
        self.assertIn("unknown time_in_force 'gtc'", reasons(self.one(hcl(time_in_force="gtc"))))
        self.assertIn("unknown order type 'trailing_stop'", reasons(self.one(hcl(type="trailing_stop"))))
        o = hcl()
        o.pop("take_profit_limit_price")
        self.assertIn("needs both take_profit_limit_price and stop_loss_stop_price", reasons(self.one(o)))
        self.assertIn("needs a stop_loss_stop_price", reasons(self.one(dict(hcl(), stop_loss_stop_price=None,
                                                                            stop_loss_limit_price="1377.00"))))
        self.assertIn("as a string", warnings(self.one(hcl(stop_loss_stop_price=1377.40))))

    def test_extended_hours_is_refused(self):
        lim = {"symbol": "ITC.NS", "side": "buy", "qty": "1", "type": "limit", "limit_price": "285",
               "time_in_force": "day", "extended_hours": True}
        res = check.check([lim], lt(), prices=PRICES, today=TODAY)
        self.assertIn("no extended-hours session", reasons(res))


class Symbols(unittest.TestCase):
    def one(self, order, **over):
        return check.check([order], lt(**over), prices=dict(PRICES, **{"M&M.NS": 3360.0, "BAJAJ-AUTO.NS": 11000.0}),
                           today=TODAY)["results"][0]

    def test_nse_symbols_that_upstream_blocked(self):
        # upstream's ticker rule (1 to 5 letters) blocked all three on its own
        for sym in ("RELIANCE.NS", "M&M.NS", "BAJAJ-AUTO.NS"):
            r = self.one(buy(sym, 1))
            self.assertEqual(r["verdict"], "PASS", (sym, r["reasons"]))
            self.assertEqual(r["symbol"], sym)

    def test_a_bare_symbol_gets_the_ns(self):
        r = self.one(buy("reliance", 1))
        self.assertEqual((r["symbol"], r["verdict"], r["value_inr"]), ("RELIANCE.NS", "PASS", 1339.7))
        self.assertTrue(check.TICKER.match("500325.BO"))

    def test_derivatives_are_off_unless_allowed(self):
        for sym in ("NIFTY26NOV24000CE", "BANKNIFTY26NOV52000PE", "SBIN26NOVFUT", "BE270617C00100000"):
            opt = {"symbol": sym, "side": "buy", "qty": "75", "type": "limit", "limit_price": "12.50",
                   "time_in_force": "day"}
            r = self.one(opt)
            self.assertEqual(r["verdict"], "BLOCK", sym)
            self.assertIn("derivative", " ".join(r["reasons"]), sym)
        r = self.one(dict(opt, symbol="NIFTY26NOV24000CE"), allow_options=True)
        self.assertEqual(r["verdict"], "PASS")
        self.assertTrue(r["warnings"])

    def test_crypto_and_junk_symbols(self):
        for sym in ("BTC/USD", "RELIANCE NS", "HCL$"):
            r = self.one(buy(sym, 1))
            self.assertIn("NSE or BSE symbol", " ".join(r["reasons"]), sym)


class Exits(unittest.TestCase):
    PF = {"cash": 3077.0, "positions": [{"ticker": "HCLTECH.NS", "shares": 5,
                                          "lots": [{"date": TODAY, "shares": 5, "cost": 6923.0}]}]}
    SELL = {"symbol": "HCLTECH.NS", "side": "sell", "qty": "5", "type": "market", "time_in_force": "day"}

    def test_getting_out_is_never_blocked_by_the_day_limits(self):
        full = {"orders": [placed("HCLTECH.NS"), placed("INFY.NS"), placed("TCS.NS")] +
                          [placed("T%d" % i, max_loss=1) for i in range(6)] +
                          [placed("HCLTECH.NS", side="sell", kind="exit", max_loss=None)]}
        c = cfg(blocked=["HCLTECH"], max_order_inr=100, max_daily_loss_inr=50)
        res = check.check([self.SELL], c, portfolio=self.PF, state=full, now=at("2026-11-13 15:16"))
        r = res["results"][0]
        self.assertEqual((r["verdict"], r["kind"]), ("PASS", "exit"), r["reasons"])
        why = warnings(res)
        for word in ("blocked:", "duplicate:", "daily limit:"):
            self.assertIn("exit, not blocked: " + word, why)
        self.assertNotIn("price", why)
        res = check.check([self.SELL], cfg(), portfolio=self.PF, now=at("2026-11-14 12:00"))
        self.assertEqual(verdicts(res), ["PASS"])

    def test_a_partial_exit_and_the_rest(self):
        half = dict(self.SELL, qty="2")             # 2 + 2 of the 5 held; a third 2 is one too many
        res = check.check([half, half], cfg(), portfolio=self.PF, prices={"HCLTECH.NS": 1390.0}, now=at(NOW))
        self.assertEqual(verdicts(res), ["PASS", "PASS"])
        self.assertEqual([r["kind"] for r in res["results"]], ["exit", "exit"])
        self.assertIn("exit, not blocked: duplicate", warnings(res, 1))
        res = check.check([half, half, half], cfg(), portfolio=self.PF, prices={"HCLTECH.NS": 1390.0}, now=at(NOW))
        self.assertEqual(verdicts(res), ["PASS", "PASS", "BLOCK"])
        self.assertIn("short:", reasons(res, 2))

    def test_format_asset_and_short_still_apply_to_a_sell(self):
        res = check.check([dict(self.SELL, type="limit")], cfg(), portfolio=self.PF, now=at(NOW))
        self.assertIn("needs a limit_price", reasons(res))
        res = check.check([dict(self.SELL, qty="6")], cfg(), portfolio=self.PF, now=at(NOW))
        self.assertIn("short: selling more HCLTECH.NS than you hold (5 shares)", reasons(res))
        res = check.check([self.SELL], cfg(), now=at(NOW))
        self.assertIn("record the fill first", reasons(res))

    def test_buy_then_sell_in_one_batch(self):
        res = check.check([hcl(), self.SELL], cfg(), now=at(NOW))
        self.assertEqual(verdicts(res), ["PASS", "PASS"])
        self.assertEqual(res["results"][1]["kind"], "exit")


class LongTermChecks(unittest.TestCase):
    """The account checks still hold with every day-trade check off."""

    def one(self, order, **over):
        return check.check([order], lt(**over), prices=PRICES, today=TODAY)["results"][0]

    def test_the_five_buys_pass_on_a_fresh_1_lakh_account(self):
        res = check.check(lt_orders(), lt(), prices=PRICES, today=TODAY)
        self.assertEqual(verdicts(res), ["PASS"] * 5)
        self.assertEqual(res["cash_after"], 10748.7)
        self.assertEqual(res["results"][0]["value_inr"], 18755.8)
        self.assertEqual(res["results"][0]["amount"], "14 shares")

    def test_a_sixth_buy_is_blocked_three_ways(self):
        res = check.check(lt_orders() + [buy("RELIANCE.NS", 5)], lt(), prices=PRICES, today=TODAY)
        self.assertEqual(verdicts(res), ["PASS"] * 5 + ["BLOCK"])
        why = reasons(res, 5)
        self.assertIn("cash: leaves Rs 4,050.20 cash, under your 10% buffer of Rs 10,000", why)
        self.assertIn("position: RELIANCE.NS would be Rs 25,454.30, 25.5% of the Rs 1,00,000 account", why)
        self.assertIn("duplicate:", why)

    def test_the_day_trade_config_blocks_buys_without_a_stop(self):
        res = check.check(lt_orders(), cfg(), prices=PRICES, now=at(NOW))
        self.assertEqual(verdicts(res)[0], "BLOCK")
        self.assertIn("stop: no stop", reasons(res))

    def test_max_and_min_order(self):
        self.assertIn("Rs 28,500 is over your Rs 20,000 max order",
                      " ".join(self.one(buy("ITC.NS", 100), max_position_pct=100)["reasons"]))
        self.assertIn("Rs 285 is under your Rs 500 minimum order",
                      " ".join(self.one(buy("ITC.NS", 1), min_order_inr=500)["reasons"]))

    def test_blocked_list(self):
        r = self.one(buy("ITC.NS", 10), blocked=["ITC"])
        self.assertEqual(r["verdict"], "BLOCK")
        self.assertIn("blocked list", r["reasons"][0])

    def test_format_rules(self):
        both = dict(buy("ITC.NS", 10), notional="2850")
        self.assertIn("exactly one of qty or notional", " ".join(self.one(both)["reasons"]))
        nolimit = {"symbol": "ITC.NS", "side": "buy", "qty": "1", "type": "limit", "time_in_force": "day"}
        self.assertIn("needs a limit_price", " ".join(self.one(nolimit)["reasons"]))
        bad = {"symbol": "ITC.NS", "side": "hold", "qty": "1"}
        self.assertIn("side must be buy or sell", " ".join(self.one(bad)["reasons"]))

    def test_numbers_should_be_strings(self):
        r = self.one({"symbol": "ITC.NS", "side": "buy", "qty": 10, "type": "market", "time_in_force": "day"})
        self.assertEqual(r["verdict"], "PASS")
        self.assertIn("as a string", r["warnings"][0])

    def test_share_orders_need_a_price(self):
        q = buy("ZZZZ", 2)
        self.assertIn("no price for ZZZZ.NS", " ".join(self.one(q)["reasons"]))
        r = self.one(buy("ITC.NS", 2))
        self.assertEqual(r["verdict"], "PASS")
        self.assertAlmostEqual(r["value_inr"], 570.0)

    def test_margin(self):
        r = check.check([buy("RELIANCE.NS", 10)], lt(cash_buffer_pct=0, max_position_pct=100),
                        portfolio={"cash": 10000, "positions": []}, prices=PRICES, today=TODAY)["results"][0]
        self.assertIn("margin", " ".join(r["reasons"]))

    PF = {"cash": 10748.7, "positions": [{"ticker": "ITC.NS", "shares": 70,
                                          "lots": [{"date": "2026-11-13", "shares": 70, "cost": 19950.0}]}]}

    def test_short_sales_are_blocked(self):
        sell = {"symbol": "ITC.NS", "side": "sell", "qty": "80", "type": "market", "time_in_force": "day"}
        r = check.check([sell], lt(), portfolio=self.PF, prices=PRICES, today=TODAY)["results"][0]
        self.assertIn("short:", " ".join(r["reasons"]))
        sell["qty"] = "30"
        r = check.check([sell], lt(), portfolio=self.PF, prices=PRICES, today=TODAY)["results"][0]
        self.assertEqual(r["verdict"], "PASS")

    def test_a_sell_frees_cash_for_a_later_buy(self):
        orders = [{"symbol": "ITC.NS", "side": "sell", "qty": "40", "type": "market", "time_in_force": "day"},
                  buy("SBIN.NS", 15)]
        res = check.check(orders, lt(max_position_pct=100), portfolio=self.PF, prices=PRICES, today=TODAY)
        self.assertEqual(verdicts(res), ["PASS", "PASS"])
        res = check.check([buy("SBIN.NS", 15)], lt(max_position_pct=100), portfolio=self.PF, prices=PRICES,
                          today=TODAY)
        self.assertEqual(verdicts(res), ["BLOCK"])

    def test_daily_limit_and_already_placed_today(self):
        st = {"orders": [{"symbol": "T%d.NS" % i, "side": "buy", "status": "placed", "at": TODAY + "T10:00:00"}
                         for i in range(10)]}
        res = check.check([buy("ITC.NS", 10)], lt(), prices=PRICES, state=st, today=TODAY)
        self.assertIn("daily limit", reasons(res))
        res = check.check([buy("ITC.NS", 10)], lt(), prices=PRICES, state=st, today="2026-11-16")
        self.assertEqual(verdicts(res), ["PASS"])
        itc = {"orders": [{"symbol": "ITC", "side": "buy", "status": "placed", "at": TODAY + "T10:00:00"}]}
        res = check.check([buy("ITC.NS", 10)], lt(), prices=PRICES, state=itc, today=TODAY)
        self.assertIn("already placed today", reasons(res))
        declined = {"orders": [{"symbol": "ITC.NS", "side": "buy", "status": "declined", "at": TODAY + "T10:00:00"}]}
        self.assertEqual(verdicts(check.check([buy("ITC.NS", 10)], lt(), prices=PRICES, state=declined,
                                              today=TODAY)), ["PASS"])

    def test_live_account_warns(self):
        res = check.check([buy("ITC.NS", 10)], lt(paper=False), prices=PRICES, today=TODAY)
        self.assertIn("LIVE", res["warnings"][0])


class Cli(unittest.TestCase):
    def test_a_yahoo_price_is_called_delayed(self):
        later = at(NOW)
        res = check.check([hcl()], cfg(), prices={"HCLTECH.NS": 1386.0}, now=later,
                          price_times={"HCLTECH.NS": later}, price_sources={"HCLTECH.NS": "yahoo"})
        r = res["results"][0]
        self.assertTrue(any("Yahoo's, which runs behind" in w for w in r["warnings"]), r["warnings"])
        res = check.check([hcl()], cfg(), prices={"HCLTECH.NS": 1386.0}, now=later,
                          price_times={"HCLTECH.NS": later}, price_sources={"HCLTECH.NS": "fyers"})
        self.assertFalse(any("Yahoo" in w for w in res["results"][0]["warnings"]))
        self.assertEqual(check.price_sources({"detail": {"HCLTECH": {"source": "yahoo"}}}), {"HCLTECH.NS": "yahoo"})

    def test_prices_file_freshness(self):
        with tempfile.TemporaryDirectory() as d:
            pp = os.path.join(d, "prices.json")
            with open(pp, "w") as fh:
                json.dump({"as_of": "2026-11-13T04:09:00Z", "prices": {"HCLTECH.NS": 1392.0},
                           "detail": {"HCLTECH.NS": {"time": "2026-11-13T04:08:00Z",
                                                     "fetched": "2026-11-13T04:09:00Z"}}}, fh)
            none = os.path.join(d, "none")
            base = ["--orders", HCL_PATH, "--config", CFG_PATH, "--portfolio", none, "--prices", pp,
                    "--state", none, "--no-write"]
            buf = io.StringIO()
            with redirect_stdout(buf):
                self.assertEqual(check.main(base + ["--now", "2026-11-13 09:40"]), 1)
            self.assertIn("entry 1392.00 (the latest price), stop 1377.40", buf.getvalue())
            self.assertIn("max loss Rs 77.08 with costs", buf.getvalue())
            # the price ran half way to the target: reward:risk is now under the minimum
            self.assertIn("reward:risk: 0.40 after costs, 0.48 before (target 1399.00, entry 1392.00, stop 1377.40)",
                          buf.getvalue())
            buf = io.StringIO()
            with redirect_stdout(buf):
                self.assertEqual(check.main(base + ["--now", "2026-11-13 10:00"]), 0)
            self.assertIn("entry 1384.60 (the plan's entry)", buf.getvalue())

    def test_long_term_orders_with_a_config_file(self):
        with tempfile.TemporaryDirectory() as d:
            c = os.path.join(d, "config.json")
            with open(c, "w") as fh:
                json.dump(lt(), fh)
            pp = os.path.join(d, "prices.json")
            with open(pp, "w") as fh:
                json.dump({"prices": {k[:-3]: v for k, v in PRICES.items()}}, fh)    # bare symbols read too
            none = os.path.join(d, "none")
            out = os.path.join(d, "state", "risk.json")
            buf = io.StringIO()
            with redirect_stdout(buf):
                code = check.main(["--orders", LT_PATH, "--config", c, "--portfolio", none, "--prices", pp,
                                   "--state", none, "--today", TODAY, "--out", out])
            self.assertEqual(code, 0, buf.getvalue())
            self.assertIn("5 passed, 0 blocked", buf.getvalue())
            with open(out) as fh:
                rec = json.load(fh)
            self.assertEqual(rec["date"], TODAY)
            self.assertTrue(all(len(r["fingerprint"]) == 16 for r in rec["results"]))

    def test_errors_are_one_line(self):
        err = io.StringIO()
        with redirect_stderr(err):
            self.assertEqual(check.main(["--orders", "/nonexistent.json", "--no-write"]), 1)
        self.assertIn("no orders file", err.getvalue())
        err = io.StringIO()
        with redirect_stderr(err):
            self.assertEqual(check.main(["--orders", HCL_PATH, "--now", "noon", "--no-write"]), 1)
        self.assertIn("--now wants", err.getvalue())
        self.assertNotIn("Traceback", err.getvalue())
        err = io.StringIO()
        with redirect_stderr(err):
            self.assertEqual(check.main(["--orders", HCL_PATH, "--today", "monday", "--no-write"]), 1)
        self.assertIn("--today wants", err.getvalue())
        with tempfile.TemporaryDirectory() as d:
            c = os.path.join(d, "config.json")
            with open(c, "w") as fh:
                json.dump({"budget": 5000, "max_loss_per_trade_usd": 50}, fh)
            err = io.StringIO()
            with redirect_stderr(err):
                self.assertEqual(check.main(["--orders", HCL_PATH, "--config", c, "--now", NOW, "--no-write"]), 1)
            self.assertIn("rename them to max_loss_per_trade_inr", err.getvalue())
            self.assertEqual(len(err.getvalue().strip().splitlines()), 1)


if __name__ == "__main__":
    unittest.main()
