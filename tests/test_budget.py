"""trader-budget tests. Fixture: tests/fixtures/trader-budget/plan-hcl.json, the plan
trader-exit writes for the worked example (HCLTECH.NS, Fri Nov 13 2026: entry 1384.60,
stop 1377.40, 2R target 1399.00, risk 7.20 a share), sized on the example config: a
Rs 10,000 account, Rs 200 max loss a trade, ICICIDirect Prime 4999 intraday costs.

The cost numbers are checked by hand in HandCheckedCosts, from the published rates."""

import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr

from _load import load, ROOT, FIX

size = load("trader-budget", "size")

CFG = os.path.join(ROOT, "trader-budget", "config.example.json")
PLAN = os.path.join(FIX, "trader-budget", "plan-hcl.json")
NOW = "2026-11-13 09:36"
TODAY = "2026-11-13"
# the example config, key for key: a Rs 10,000 account, Rs 200 a trade, Rs 500 a day, ICICIDirect
EXAMPLE_CFG = {
    "budget": 10000, "cash_buffer_pct": 10, "max_position_pct": 75, "max_order_inr": 7500, "min_order_inr": 100,
    "max_loss_per_trade_inr": 200, "max_daily_loss_inr": 500, "max_trades_per_day": 3, "max_orders_per_day": 10,
    "min_reward_risk": 1.0, "require_stop": True,
    "no_entries_before": "09:30", "no_entries_after": "15:00", "flat_by": "15:15",
    "band_warn_pct": 1, "broker": "icicidirect", "costs": "icicidirect_prime_4999", "paper": True, "blocked": [],
    "allow_options": False, "allow_margin": False, "allow_short": False,
}


def cfg(**over):
    with open(CFG) as fh:
        c = json.load(fh)
    c.update(over)
    return c


def plan(**over):
    with open(PLAN) as fh:
        p = json.load(fh)
    p.update(over)
    return p


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = size.main(argv)
    return code, out.getvalue(), err.getvalue()


def prices_doc(price, quote_time="2026-11-13T04:08:00Z", source="fyers"):
    return {"as_of": quote_time, "source": source, "prices": {"HCLTECH.NS": price},
            "detail": {"HCLTECH.NS": {"prev_close": 1380.8, "time": quote_time, "source": source}}}


class TheExample(unittest.TestCase):
    """Rs 10,000, 10% buffer, Rs 200 max loss, risk 7.20 -> 5 shares, bound by the 75% position cap."""

    def test_config_example(self):
        with open(CFG) as fh:
            self.assertEqual(json.load(fh), EXAMPLE_CFG)

    def test_hcltech_is_5_shares_bound_by_the_position_cap(self):
        s = size.size_trade(plan(), cfg(), today=TODAY)
        self.assertEqual(s["qty"], 5)
        self.assertEqual(s["bound_by"], "position cap")
        self.assertEqual(s["risk_per_share"], 7.2)
        self.assertEqual(s["cost"], 6923.0)                      # 5 x 1384.60
        self.assertEqual(s["gross_loss"], 36.0)                  # 5 x 7.20
        self.assertEqual((s["costs_at_stop"], s["costs_at_target"]), (4.08, 4.12))
        self.assertEqual(s["max_loss"], 40.08)                   # 36.00 + 4.08
        self.assertEqual(s["net_gain"], 67.88)                   # 5 x 14.40 - 4.12
        self.assertEqual((s["reward_risk"], s["net_reward_risk"]), (2.0, 1.69))   # 67.88 / 40.08
        self.assertEqual(s["cash_buffer"], 1000)
        self.assertEqual([(l["name"], l["shares"]) for l in s["limits"]],
                         [("max loss", 24), ("position cap", 5), ("max order", 5), ("cash", 6)])
        self.assertEqual([l["name"] for l in s["limits"] if l["binds"]], ["position cap"])
        self.assertIsNone(s["refusal"])

    def test_the_bracket_order(self):
        o = size.bracket_order(size.size_trade(plan(), cfg(), today=TODAY))
        why = o.pop("why")
        self.assertEqual(o, {
            "symbol": "HCLTECH.NS", "side": "buy", "qty": "5", "type": "market", "time_in_force": "day",
            "order_class": "bracket", "take_profit_limit_price": "1399.00", "stop_loss_stop_price": "1377.40",
            "plan": {"entry": 1384.6, "stop": 1377.4, "target": 1399.0, "risk_per_share": 7.2,
                     "max_loss": 40.08, "gross_loss": 36.0, "costs_at_stop": 4.08, "costs_at_target": 4.12,
                     "net_gain": 67.88, "net_reward_risk": 1.69, "setup": "orb", "entry_time": "9:35 AM",
                     "flat_by": "15:15"}})
        self.assertEqual(why, "opening-range breakout on HCLTECH.NS: 5 shares, bound by your position cap "
                              "(5 x 7.20 = Rs 36 at the stop, Rs 40.08 with costs)")

    def test_the_fixture_orders_file_is_what_it_writes(self):
        with open(os.path.join(FIX, "trader-risk", "orders-hcl.json")) as fh:
            fixture = json.load(fh)["orders"][0]
        self.assertEqual(size.bracket_order(size.size_trade(plan(), cfg(), today=TODAY)), fixture)

    def test_a_limit_order(self):
        o = size.bracket_order(size.size_trade(plan(), cfg(), limit=1384.60, today=TODAY))
        self.assertEqual((o["type"], o["limit_price"], o["qty"]), ("limit", "1384.60", "5"))
        s = size.size_trade(plan(), cfg(), limit=1384.00, today=TODAY)
        self.assertEqual((s["risk_per_share"], s["qty"], s["gross_loss"], s["max_loss"]), (6.6, 5, 33.0, 37.08))
        self.assertEqual(size.bracket_order(s)["limit_price"], "1384.00")

    def test_cli_writes_one_bracket_order(self):
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "trader", "orders.json")
            code, text, _ = run(["--plan", PLAN, "--config", CFG, "--portfolio", os.path.join(d, "none"),
                                 "--now", NOW, "--write", out])
            self.assertEqual(code, 0)
            self.assertIn("Size: 5 shares of HCLTECH.NS = Rs 6,923 at 1384.60. At the stop: 5 x 7.20 = Rs 36.", text)
            self.assertIn("Costs for the round trip, about Rs 4.12 (ICICIDirect Prime 4999 intraday: 0.01 % an "
                          "order): brokerage Rs 1.39, STT Rs 1.75, exchange and SEBI Rs 0.44, stamp duty Rs 0.21, "
                          "GST Rs 0.33.", text)
            self.assertIn("After costs: max loss Rs 40.08 at the stop, Rs 67.88 made at the target, reward:risk "
                          "1.69 (2.00 before costs).", text)
            self.assertIn("75% of Rs 10,000 = Rs 7,500 / 1384.60", text)
            self.assertIn("<- binds", text)
            self.assertIn("Flat by 15:15 IST", text)
            self.assertIn("not financial advice", text)
            with open(out) as fh:
                doc = json.load(fh)
            self.assertEqual(doc["status"], "proposed")
            self.assertIs(doc["paper"], True)
            self.assertEqual(doc["created_at"], "2026-11-13T04:06:00Z")
            self.assertEqual(len(doc["orders"]), 1)
            self.assertEqual(doc["orders"][0]["plan"]["max_loss"], 40.08)

    def test_cli_json_and_limit(self):
        code, text, _ = run(["--plan", PLAN, "--config", CFG, "--portfolio", "/nonexistent", "--now", NOW,
                             "--limit", "--json"])
        self.assertEqual(code, 0)
        out = json.loads(text)
        self.assertEqual(out["sizing"]["qty"], 5)
        self.assertEqual(out["orders"][0]["limit_price"], "1384.60")


class HandCheckedCosts(unittest.TestCase):
    """The round trip's charges, worked out here from the published rates."""

    @staticmethod
    def by_hand(qty, buy_px, sell_px, pct, cap):
        buy, sell = qty * buy_px, qty * sell_px

        def brokerage(v):
            return min(cap, v * pct / 100) if cap is not None else v * pct / 100
        brk = brokerage(buy) + brokerage(sell)
        stt = sell * 0.025 / 100                    # on the sell side
        txn = (buy + sell) * 0.00307 / 100          # NSE transaction charge
        sebi = (buy + sell) * 10 / 1e7              # Rs 10 a crore
        stamp = buy * 0.003 / 100                   # on the buy side
        gst = (brk + txn + sebi) * 18 / 100
        return round(brk + stt + txn + sebi + stamp + gst, 2)

    def test_dhan(self):
        m = size.cost_model({})                     # dhan is the default
        self.assertEqual(m["label"], "Dhan intraday: Rs 20 or 0.03 % an order, whichever is lower")
        # 5 shares: 0.03 % of about Rs 6,900 is about Rs 2.08 an order, under the Rs 20 cap
        self.assertEqual(size.round_trip_costs(5, 1384.60, 1399.00, m),
                         {"brokerage": 4.18, "stt": 1.75, "transaction": 0.43, "sebi": 0.01, "stamp": 0.21,
                          "gst": 0.83, "total": 7.4})
        self.assertEqual(size.round_trip_costs(5, 1384.60, 1399.00, m)["total"], self.by_hand(5, 1384.60, 1399.00, 0.03, 20))
        self.assertEqual(size.round_trip_costs(5, 1384.60, 1377.40, m)["total"], self.by_hand(5, 1384.60, 1377.40, 0.03, 20))
        self.assertEqual(self.by_hand(5, 1384.60, 1377.40, 0.03, 20), 7.33)
        # 54 shares: 0.03 % of Rs 74,768 is Rs 22.43, so the Rs 20 cap applies to both orders
        big = size.round_trip_costs(54, 1384.60, 1391.80, m)
        self.assertEqual((big["brokerage"], big["total"]), (40.0, 73.84))
        self.assertEqual(big["total"], self.by_hand(54, 1384.60, 1391.80, 0.03, 20))

    def test_other_presets(self):
        icici = size.cost_model({"costs": "icicidirect_prime_4999"})
        self.assertEqual(size.round_trip_costs(5, 1384.60, 1399.00, icici)["total"], 4.12)
        self.assertEqual(self.by_hand(5, 1384.60, 1399.00, 0.01, None), 4.12)
        zero = size.cost_model({"costs": "zero"})
        self.assertEqual(size.round_trip_costs(5, 1384.60, 1377.40, zero)["total"], self.by_hand(5, 1384.60, 1377.40, 0, None))
        custom = size.cost_model({"costs": {"brokerage_pct": 0.05, "brokerage_cap": None}})
        self.assertEqual(size.round_trip_costs(5, 1384.60, 1399.00, custom)["total"], self.by_hand(5, 1384.60, 1399.00, 0.05, None))
        for off in (False, None, "none"):
            self.assertIsNone(size.cost_model({"costs": off}))
        self.assertEqual(size.round_trip_costs(5, 1384.60, 1399.00, None)["total"], 0.0)
        with self.assertRaises(ValueError):
            size.cost_model({"costs": "kite"})

    def test_costs_change_the_sizing(self):
        s = size.size_trade(plan(), cfg(costs="dhan"), today=TODAY)
        self.assertEqual((s["max_loss"], s["net_reward_risk"]), (43.33, 1.49))    # 36.00 + 7.33; 64.60 / 43.33
        s = size.size_trade(plan(), cfg(costs=False), today=TODAY)
        self.assertEqual((s["max_loss"], s["net_gain"], s["net_reward_risk"], s["costs"]), (36.0, 72.0, 2.0, None))
        with self.assertRaises(size.SizeError) as e:
            size.size_trade(plan(), cfg(costs="kite"), today=TODAY)
        self.assertIn("unknown costs preset 'kite'", str(e.exception))

    def test_costs_come_out_of_the_max_loss(self):
        # Rs 30 a trade: 4 shares risk 28.80, but with costs 4 shares lose more than 30, so 3
        s = size.size_trade(plan(), cfg(max_loss_per_trade_inr=30), today=TODAY)
        self.assertEqual((s["qty"], s["bound_by"], s["gross_loss"], s["max_loss"]), (3, "max loss", 21.6, 24.05))
        s = size.size_trade(plan(), cfg(max_loss_per_trade_inr=30, costs=False), today=TODAY)
        self.assertEqual((s["qty"], s["max_loss"]), (4, 28.8))

    def test_a_1r_target_does_not_clear_costs(self):
        # the same trade with a 1R target (1391.80): 36.00 - 4.10 made against 40.08 lost
        s = size.size_trade(plan(target=1391.8), cfg(), today=TODAY)
        self.assertEqual((s["reward_risk"], s["net_gain"], s["net_reward_risk"]), (1.0, 31.9, 0.8))
        self.assertIn("reward:risk 0.80 after costs (Rs 31.90 made at the target, Rs 40.08 lost at the stop; "
                      "1.00 before costs)", s["refusal"])
        self.assertIn("(a farther target)", s["refusal"])
        self.assertIsNone(size.bracket_order(s))
        self.assertIsNone(size.size_trade(plan(target=1391.8), cfg(costs=False), today=TODAY)["refusal"])


class Money(unittest.TestCase):
    def test_indian_digit_grouping(self):
        self.assertEqual(size.money(100000), "Rs 1,00,000")
        self.assertEqual(size.money(74768.4), "Rs 74,768.40")
        self.assertEqual(size.money(12345678), "Rs 1,23,45,678")
        self.assertEqual(size.money(40.08), "Rs 40.08")
        self.assertEqual(size.money(-46.88), "-Rs 46.88")

    def test_dollar_keys_are_refused(self):
        with tempfile.TemporaryDirectory() as d:
            c = os.path.join(d, "config.json")
            with open(c, "w") as fh:
                json.dump({"budget": 5000, "max_order_usd": 4000, "max_loss_per_trade_usd": 50}, fh)
            code, _, err = run(["--plan", PLAN, "--config", c, "--now", NOW])
            self.assertEqual(code, 1)
            self.assertIn("upstream dollar keys (max_order_usd, max_loss_per_trade_usd)", err)
            self.assertIn("max_order_inr, max_loss_per_trade_inr", err)

    def test_weights_mode_is_gone(self):
        self.assertFalse(hasattr(size, "parse_weights"))
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as cm:
            size.main(["--plan", PLAN, "--config", CFG, "--now", NOW, "--weights", "TCS=50"])
        self.assertEqual(cm.exception.code, 2)    # argparse: no such flag


class PlanRules(unittest.TestCase):
    def test_zero_shares_is_a_plain_refusal(self):
        s = size.size_trade(plan(stop=380.0), cfg(), today=TODAY)
        self.assertEqual(s["qty"], 0)
        self.assertIn("one share risks Rs 1,004.60 (entry 1384.60 minus stop 380.00) plus Rs 0.41 costs, more than "
                      "your Rs 200 max loss per trade", s["refusal"])
        self.assertIsNone(size.bracket_order(s))
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "plan.json")
            with open(p, "w") as fh:
                json.dump(plan(stop=380.0), fh)
            out = os.path.join(d, "orders.json")
            code, text, _ = run(["--plan", p, "--config", CFG, "--portfolio", os.path.join(d, "none"),
                                 "--now", NOW, "--write", out])
            self.assertEqual(code, 1)
            self.assertIn("No order:", text)
            self.assertFalse(os.path.exists(out))

    def test_each_limit_can_bind(self):
        s = size.size_trade(plan(), cfg(max_order_inr=5000), today=TODAY)
        self.assertEqual((s["qty"], s["bound_by"]), (3, "max order"))
        s = size.size_trade(plan(), cfg(max_position_pct=20), today=TODAY)
        self.assertEqual((s["qty"], s["bound_by"]), (1, "position cap"))
        s = size.size_trade(plan(), cfg(), cash=4000, today=TODAY)
        self.assertEqual((s["qty"], s["bound_by"], s["cash_available"]), (2, "cash", 3000))
        s = size.size_trade(plan(), cfg(max_loss_per_trade_inr=30), today=TODAY)
        self.assertEqual((s["qty"], s["bound_by"]), (3, "max loss"))

    def test_a_fresh_higher_price_means_a_bigger_risk(self):
        s = size.size_trade(plan(), cfg(), price=1386.0, today=TODAY)
        self.assertEqual((s["entry"], s["entry_from"], s["risk_per_share"]), (1386.0, "price", 8.6))
        self.assertEqual((s["qty"], s["max_loss"], s["reward_risk"], s["net_reward_risk"]), (5, 47.08, 1.51, 1.29))
        self.assertIsNone(s["refusal"])
        # at 1392 half the move is gone: 7.00 to the target against 14.60 to the stop
        s = size.size_trade(plan(), cfg(), price=1392.0, today=TODAY)
        self.assertIn("reward:risk 0.40 after costs (Rs 30.87 made at the target, Rs 77.08 lost at the stop; "
                      "0.48 before costs) (target 1399.00, entry 1392.00, stop 1377.40) is under your minimum 1",
                      s["refusal"])
        self.assertIsNone(size.bracket_order(s))
        self.assertIsNone(size.size_trade(plan(), cfg(min_reward_risk=0), price=1392.0, today=TODAY)["refusal"])
        lower = size.size_trade(plan(), cfg(), price=1383.00, today=TODAY)
        self.assertEqual((lower["entry"], lower["qty"]), (1384.6, 5))

    def test_a_yahoo_price_is_used_but_called_delayed(self):
        # a fresh Yahoo price still counts (it can only raise the entry, so the risk), with a warning
        with tempfile.TemporaryDirectory() as d:
            pp = os.path.join(d, "prices.json")
            with open(pp, "w") as fh:
                json.dump(prices_doc(1392.0, source="yahoo"), fh)
            code, text, _ = run(["--plan", PLAN, "--config", CFG, "--portfolio", os.path.join(d, "none"),
                                 "--prices", pp, "--json", "--now", "2026-11-13 09:40"])
            out = json.loads(text)
            self.assertEqual(out["sizing"]["entry"], 1392.0)
            self.assertTrue(any("Yahoo's, which runs behind" in n for n in out["notes"]), out["notes"])

    def test_prices_file_is_used_only_when_fresh(self):
        with tempfile.TemporaryDirectory() as d:
            pp = os.path.join(d, "prices.json")
            with open(pp, "w") as fh:
                json.dump(prices_doc(1392.0), fh)
            base = ["--plan", PLAN, "--config", CFG, "--portfolio", os.path.join(d, "none"), "--prices", pp, "--json"]
            code, text, _ = run(base + ["--now", "2026-11-13 09:40"])
            out = json.loads(text)
            self.assertEqual((code, out["sizing"]["entry"], out["orders"]), (1, 1392.0, []))
            self.assertIn("above the plan's entry", out["notes"][0])
            self.assertIn("IST", out["notes"][0])
            code, text, _ = run(base + ["--now", "2026-11-13 10:00"])
            out = json.loads(text)
            self.assertEqual((code, out["sizing"]["entry"], out["sizing"]["qty"]), (0, 1384.6, 5))
            self.assertIn("not used", out["notes"][0])

    def test_the_portfolio_cash_caps_the_size(self):
        with tempfile.TemporaryDirectory() as d:
            pf = os.path.join(d, "portfolio.json")
            with open(pf, "w") as fh:
                json.dump({"cash": 4000, "positions": []}, fh)
            out = json.loads(run(["--plan", PLAN, "--config", CFG, "--portfolio", pf, "--now", NOW, "--json"])[1])
            self.assertEqual((out["sizing"]["qty"], out["sizing"]["bound_by"]), (2, "cash"))

    def test_bad_plans(self):
        for p, word in ((plan(stop=1385.0), "not below the entry"),
                        (plan(target=1380.0), "already happened"),
                        (plan(target=None), "positive target"),
                        (plan(side="sell"), "long (buy) day trades only"),
                        (plan(symbol=""), "no symbol")):
            with self.assertRaises(size.SizeError) as e:
                size.size_trade(p, cfg(), today=TODAY)
            self.assertIn(word, str(e.exception))
        with self.assertRaises(size.SizeError) as e:
            size.size_trade(plan(), cfg(), price=1400.00, today=TODAY)
        self.assertIn("already happened", str(e.exception))
        with self.assertRaises(size.SizeError) as e:
            size.size_trade(plan(), cfg(blocked=["hcltech"]), today=TODAY)
        self.assertIn("blocked list", str(e.exception))
        with self.assertRaises(size.SizeError) as e:
            size.size_trade(plan(), cfg(), today="2026-11-16")
        self.assertIn("today is 2026-11-16 in India", str(e.exception))

    def test_a_bare_symbol_gets_the_ns(self):
        s = size.size_trade(plan(symbol="hcltech"), cfg(), today=TODAY)
        self.assertEqual(s["symbol"], "HCLTECH.NS")

    def test_under_the_minimum_order(self):
        cheap = plan(symbol="ABC", entry=40.0, stop=30.0, target=60.0)
        s = size.size_trade(cheap, cfg(max_loss_per_trade_inr=11), today=TODAY)
        self.assertEqual(s["qty"], 1)
        self.assertIn("1 share of ABC.NS is Rs 40, under your Rs 100 minimum order", s["refusal"])
        self.assertIsNone(size.bracket_order(s))
        # Rs 10 a trade: one share risks exactly 10, and the 2 paise of costs tip it over
        s = size.size_trade(cheap, cfg(max_loss_per_trade_inr=10), today=TODAY)
        self.assertEqual(s["qty"], 0)
        self.assertIn("plus Rs 0.02 costs", s["refusal"])

    def test_missing_plan_and_bad_clock(self):
        code, _, err = run(["--plan", "/nonexistent/plan.json", "--config", CFG, "--now", NOW])
        self.assertEqual(code, 1)
        self.assertIn("no plan", err)
        code, _, err = run(["--plan", PLAN, "--config", CFG, "--now", "tomorrow"])
        self.assertEqual(code, 1)
        self.assertNotIn("Traceback", err)


if __name__ == "__main__":
    unittest.main()
