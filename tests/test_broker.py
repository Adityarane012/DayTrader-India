"""trader-broker tests: tickets you place yourself, your yes, the log. The order is the
worked example's bracket (tests/fixtures/trader-risk/orders-hcl.json)."""

import io
import json
import os
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr

from _load import load, ROOT, FIX

ticket = load("trader-broker", "ticket")
check = load("trader-risk", "check")

CFG_PATH = os.path.join(ROOT, "trader-budget", "config.example.json")
ORDERS_PATH = os.path.join(FIX, "trader-risk", "orders-hcl.json")
PLAN_PATH = os.path.join(FIX, "trader-budget", "plan-hcl.json")
NOW = "2026-11-13 09:36"
TODAY = "2026-11-13"
ITC = {"symbol": "ITC.NS", "side": "buy", "qty": "10", "type": "market", "time_in_force": "day"}
BATCH = ["ITC.NS", "TCS.NS", "INFY.NS", "RELIANCE.NS", "SBIN.NS"]
HCL_FIELDS = {"symbol": "HCLTECH.NS", "side": "buy", "qty": "5", "type": "market", "time_in_force": "day",
              "order_class": "bracket", "take_profit_limit_price": "1399.00", "stop_loss_stop_price": "1377.40"}
HCL_PLAIN = ("BUY 5 HCLTECH.NS, market, good for today / stop-loss 1377.40 / take-profit 1399.00 / max loss about "
             "Rs 40.08 with Rs 4.08 costs if the stop fills at 1377.40 (it can fill worse in a fast market)")


def hcl(**over):
    with open(ORDERS_PATH) as fh:
        o = json.load(fh)["orders"][0]
    o.update(over)
    return o


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = ticket.main(argv)
    return code, out.getvalue(), err.getvalue()


class ExplicitYes(unittest.TestCase):
    def yes(self, reply, order=ITC, batch=BATCH):
        return ticket.parse_yes(reply, order, batch)[0]

    def test_plain_yes_counts(self):
        for r in ("yes", "Yes.", "YES", "y", "yes place it", "Yes, buy it", "yes ITC", "yes ITC.NS",
                  "yes 10 ITC", "yes 10"):
            self.assertTrue(self.yes(r), r)

    def test_anything_else_does_not(self):
        for r in ("", "sure", "ok", "okay", "go", "do it", "yeah", "haan", "yep", "absolutely", "send it",
                  "yes to all", "yes, all of them", "yes to the rest", "yes both",
                  "yes TCS", "yes RELIANCE.NS", "yes 11", "yes but make it 20", "yes?", "no", "not yes",
                  "yes, wait", "yes if it is under 280"):
            self.assertFalse(self.yes(r), r)

    def test_amount_must_match_this_order(self):
        sell = {"symbol": "ITC.NS", "side": "sell", "qty": "30", "type": "market", "time_in_force": "day"}
        self.assertTrue(self.yes("yes sell 30 ITC", sell))
        self.assertFalse(self.yes("yes sell 40", sell))

    def test_a_bracket_yes(self):
        o = hcl()
        for r in ("yes", "yes 5 HCLTECH", "yes 1377.40", "yes max loss 40.08", "yes target 1399.00"):
            self.assertTrue(self.yes(r, o, ["HCLTECH.NS"]), r)
        for r in ("yes 6", "yes 60 HCLTECH", "yes but stop at 1376", "yes, stop 1377.40", "yes RELIANCE",
                  "sure"):
            self.assertFalse(self.yes(r, o, ["HCLTECH.NS", "RELIANCE.NS"]), r)

    def test_a_symbol_outside_the_batch_is_not_caught(self):
        # as upstream: only the batch's other symbols are known, so "yes INFY" on a one-order batch
        # passes the name check; the amount check and the ticket on screen are the guard there
        self.assertTrue(self.yes("yes INFY", hcl(), ["HCLTECH.NS"]))
        self.assertFalse(self.yes("yes INFY 60", hcl(), ["HCLTECH.NS"]))


class TicketShape(unittest.TestCase):
    def test_order_fields_leave_out_why_and_plan(self):
        self.assertEqual(ticket.order_fields(dict(ITC, why="from a list")), ITC)
        self.assertEqual(ticket.order_fields({"symbol": "ITC.NS", "side": "buy", "qty": 3, "type": "limit",
                                              "limit_price": 284.5, "time_in_force": "day"}),
                         {"symbol": "ITC.NS", "side": "buy", "qty": "3", "type": "limit", "limit_price": "284.5",
                          "time_in_force": "day"})
        self.assertEqual(ticket.order_fields(hcl()), HCL_FIELDS)
        self.assertEqual(ticket.fingerprint(hcl()), ticket.fingerprint(HCL_FIELDS))

    def test_plain_english(self):
        self.assertEqual(ticket.plain(ITC), "BUY 10 shares of ITC.NS, market order, good for today")
        self.assertEqual(ticket.plain({"symbol": "ITC.NS", "side": "sell", "qty": "1", "type": "limit",
                                       "limit_price": "295", "time_in_force": "ioc"}),
                         "SELL 1 share of ITC.NS, limit order at Rs 295, immediate or cancel")
        self.assertEqual(ticket.plain(hcl()), HCL_PLAIN)
        lim = hcl(type="limit", limit_price="1384.00")
        self.assertEqual(ticket.plain(lim).split(" / ")[0], "BUY 5 HCLTECH.NS, limit 1384.00, good for today")
        self.assertEqual(ticket.max_loss(dict(HCL_FIELDS)), (None, 1377.4))

    def test_the_max_loss_is_trader_risks_number_with_costs(self):
        self.assertEqual(ticket.max_loss(hcl()), (40.08, 1377.4))            # what trader-budget wrote
        # an order edited after sizing: the plan's number is stale, trader-risk's verdict is not
        lim = hcl(type="limit", limit_price="1384.00")
        rv = check.check([lim], {"budget": 10000, "costs": "icicidirect_prime_4999"},
                         now=check.parse_now(NOW))["results"][0]
        self.assertEqual((rv["max_loss"], rv["costs_at_stop"]), (37.08, 4.08))
        self.assertEqual(ticket.max_loss(lim, rv), (37.08, 1377.4))
        self.assertIn("max loss about Rs 37.08 with Rs 4.08 costs", ticket.plain(lim, rv))
        # an old order without costs in its plan, and no verdict: entry minus stop
        old = dict(HCL_FIELDS, plan={"entry": 1384.6, "stop": 1377.4})
        self.assertEqual(ticket.max_loss(old), (36.0, 1377.4))

    def test_how_to_place_it_in_dhan(self):
        steps = ticket.how_to_place(hcl(), {"broker": "dhan"})
        self.assertEqual(steps[0], "In Dhan: Buy 5 HCLTECH (NSE), product Intraday, Market.")
        self.assertIn("Super Order with target 1399.00 and stop loss 1377.40", " ".join(steps))
        self.assertIn("the other is canceled", " ".join(steps))

    def test_other_brokers_are_warned_that_two_exits_are_not_linked(self):
        steps = " ".join(ticket.how_to_place(hcl(), {"broker": "icicidirect"}))
        self.assertIn("In ICICIDirect: Buy 5 HCLTECH (NSE), product Intraday, Market.", steps)
        self.assertIn("NOT linked", steps)
        self.assertIn("leaves you short", steps)
        self.assertIn("In your broker:", " ".join(ticket.how_to_place(ITC, {"broker": None})))

    def test_no_alpaca_left(self):
        with open(os.path.join(ROOT, "trader-broker", "ticket.py"), encoding="utf-8") as fh:
            src = fh.read().lower()
        for word in ("alpaca", "place_stock_order", "ibkr", "allow once"):
            self.assertNotIn(word, src)
        self.assertFalse(os.path.exists(os.path.join(ROOT, "trader-broker", "claude_desktop_config.example.json")))


class Flow(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.orders = os.path.join(self.d, "orders.json")
        shutil.copy(ORDERS_PATH, self.orders)
        self.cfg = os.path.join(self.d, "config.json")
        shutil.copy(CFG_PATH, self.cfg)
        self.risk = os.path.join(self.d, "state", "risk.json")
        self.state = os.path.join(self.d, "state", "broker.json")
        self.pf = os.path.join(self.d, "portfolio.json")
        self.none = os.path.join(self.d, "none")

    def tearDown(self):
        shutil.rmtree(self.d)

    def live(self, broker=None):
        with open(self.cfg) as fh:
            c = json.load(fh)
        c.update(paper=False)
        if broker:
            c["broker"] = broker
        with open(self.cfg, "w") as fh:
            json.dump(c, fh)

    def args(self, *extra, **kw):
        return list(extra) + ["--orders", self.orders, "--config", self.cfg, "--risk", self.risk,
                              "--state", self.state, "--now", kw.get("now", NOW)]

    def run_risk(self, now=NOW):
        with redirect_stdout(io.StringIO()):
            return check.main(["--orders", self.orders, "--config", self.cfg, "--portfolio", self.pf,
                               "--prices", self.none, "--state", self.state, "--now", now, "--out", self.risk])

    def state_doc(self):
        with open(self.state) as fh:
            return json.load(fh)

    def test_nothing_is_ready_before_the_risk_check(self):
        code, text, _ = run(self.args("show"))
        self.assertEqual(code, 1)
        self.assertIn("NOT READY", text)
        self.assertNotIn("Reply \"yes\"", text)
        code, _, err = run(self.args("approve", "--index", "1", "--reply", "yes"))
        self.assertEqual(code, 1)
        self.assertIn("not ready", err)

    def test_a_paper_ticket_says_practice(self):
        self.assertEqual(self.run_risk(), 0)
        code, text, _ = run(self.args("show", "--index", "1"))
        self.assertEqual(code, 0)
        self.assertIn("ORDER 1 of 1, PAPER (practice: write it down, do not place it), ICICIDirect", text)
        self.assertIn("This is practice", text)
        self.assertNotIn("Super Order", text)
        code, text, _ = run(self.args("approve", "--index", "1", "--reply", "yes"))
        self.assertIn("Paper: write it down, do not place it", text)

    def test_the_example_config_is_an_icicidirect_ticket(self):
        self.live()
        self.assertEqual(self.run_risk(), 0)
        code, text, _ = run(self.args("show", "--index", "1"))
        self.assertIn("ORDER 1 of 1, LIVE: real money, you place it, ICICIDirect", text)
        self.assertIn("In ICICIDirect: Buy 5 HCLTECH (NSE), product Intraday, Market.", text)
        self.assertIn("NOT linked", text)                       # two separate exits can leave you short
        self.assertNotIn("Super Order", text)

    def test_the_full_live_flow_you_place_yourself(self):
        self.live("dhan")
        self.assertEqual(self.run_risk(), 0)
        code, text, _ = run(self.args("show", "--index", "1"))
        self.assertEqual(code, 0)
        self.assertIn("ORDER 1 of 1, LIVE: real money, you place it, Dhan", text)
        for part in HCL_PLAIN.split(" / "):
            self.assertIn("  " + part + "\n", text)
        self.assertIn("READY: trader-risk PASS", text)
        self.assertIn("In Dhan: Buy 5 HCLTECH (NSE), product Intraday, Market.", text)
        self.assertIn("Super Order", text)
        self.assertIn("Nothing is sent from here", text)

        code, text, _ = run(self.args("approve", "--index", "1", "--reply", "sure"))
        self.assertEqual(code, 1)
        self.assertIn("Not recorded", text)
        self.assertFalse(os.path.exists(self.state))

        code, text, _ = run(self.args("approve", "--index", "1", "--reply", "yes"))
        self.assertEqual(code, 0)
        self.assertIn("Place it yourself now. Nothing was sent from here.", text)
        self.assertIn("ticket.py result --index 1 --status placed --broker-id ID", text)
        code, _, err = run(self.args("approve", "--index", "1", "--reply", "yes"))
        self.assertEqual(code, 1)
        self.assertIn("APPROVED", err)

        code, text, _ = run(self.args("result", "--index", "1", "--status", "placed", "--broker-id",
                                      "112611270001", "--filled-qty", "5", "--filled-price", "1384.70",
                                      "--portfolio", self.pf, now="2026-11-13 09:37"))
        self.assertEqual(code, 0)
        st = self.state_doc()
        self.assertEqual([r["status"] for r in st["orders"]], ["approved", "placed", "filled"])
        appr, plc = st["orders"][0], st["orders"][1]
        self.assertEqual((appr["reply"], appr["kind"], appr["max_loss"], appr["date"], appr["broker"]),
                         ("yes", "entry", 40.08, TODAY, "dhan"))
        self.assertEqual(appr["at"], "2026-11-13T09:36:00+05:30")
        self.assertEqual((plc["broker_order_id"], plc["max_loss"], plc["kind"]), ("112611270001", 40.08, "entry"))
        with open(self.pf) as fh:
            pf = json.load(fh)
        self.assertEqual(pf["cash"], 3076.5)               # 10,000 - 5 x 1384.70
        self.assertEqual(pf["positions"][0]["shares"], 5)

        code, text, _ = run(self.args("show", "--index", "1"))
        self.assertIn("DONE: placed", text)
        code, text, _ = run(["log", "--state", self.state, "--now", NOW])
        self.assertIn("1 placed today", text)
        self.assertIn("max loss Rs 40.08", text)

        # trader-risk now counts it: a second HCLTECH buy today is a duplicate, and Rs 40.08 is used
        res = check.check([hcl()], {"budget": 10000}, state=st, now=check.parse_now("2026-11-13 09:50"))
        self.assertIn("already placed today", " ".join(res["results"][0]["reasons"]))
        self.assertEqual((res["today"]["entries_placed"], res["today"]["loss_at_risk"]), (1, 40.08))

    def test_flatten_by_15_15(self):
        self.live()
        self.run_risk()
        run(self.args("approve", "--index", "1", "--reply", "yes"))
        run(self.args("result", "--index", "1", "--status", "placed", "--broker-id", "abc",
                      "--filled-qty", "5", "--filled-price", "1384.70", "--portfolio", self.pf))
        late = "2026-11-13 15:15"
        code, text, _ = run(["flatten", "--symbol", "HCLTECH", "--orders", self.orders, "--portfolio", self.pf,
                             "--plan", PLAN_PATH, "--config", self.cfg, "--now", late])
        self.assertEqual(code, 0)
        self.assertIn("SELL 5 shares of HCLTECH.NS, market order, good for today (flat by 15:15 IST)", text)
        self.assertIn("replaced 1 earlier proposal", text)
        self.assertIn("cancel the open stop-loss and target first", text)
        self.assertIn("square off open intraday positions themselves from about 15:20", text)
        with open(self.orders) as fh:
            doc = json.load(fh)
        self.assertEqual(ticket.order_fields(doc["orders"][0]),
                         {"symbol": "HCLTECH.NS", "side": "sell", "qty": "5", "type": "market",
                          "time_in_force": "day"})
        self.assertEqual(self.run_risk(now=late), 0)       # after the 15:00 entry cutoff: an exit still passes
        with open(self.risk) as fh:
            self.assertEqual(json.load(fh)["results"][0]["kind"], "exit")
        code, text, _ = run(self.args("show", now=late))
        self.assertEqual(code, 0)
        self.assertIn("READY", text)
        self.assertEqual(run(self.args("approve", "--index", "1", "--reply", "yes sell 5 HCLTECH", now=late))[0], 0)
        code, _, _ = run(self.args("result", "--index", "1", "--status", "placed", "--filled-qty", "5",
                                   "--filled-price", "1399.00", "--portfolio", self.pf, now="2026-11-13 15:16"))
        self.assertEqual(code, 0)
        with open(self.pf) as fh:
            pf = json.load(fh)
        self.assertEqual((pf["cash"], pf["positions"]), (10071.5, []))    # 3,076.50 + 5 x 1399.00
        code, _, err = run(["flatten", "--symbol", "HCLTECH", "--orders", self.orders, "--portfolio", self.pf,
                            "--now", late])
        self.assertEqual(code, 1)
        self.assertIn("nothing to flatten", err)

    def test_flatten_with_the_broker_qty(self):
        code, text, _ = run(["flatten", "--symbol", "hcltech", "--qty", "5", "--orders", self.orders,
                             "--portfolio", self.none, "--plan", self.none, "--config", self.cfg, "--now", NOW])
        self.assertEqual(code, 0)
        self.assertNotIn("Check it against your broker's positions", text)
        self.assertIn("flat by 15:15 IST", text)
        self.assertEqual(run(["flatten", "--symbol", "HCLTECH", "--qty", "0", "--orders", self.orders])[0], 1)

    def test_an_edited_order_is_not_ready(self):
        self.run_risk()
        with open(self.orders) as fh:
            doc = json.load(fh)
        doc["orders"][0]["qty"] = "6"
        with open(self.orders, "w") as fh:
            json.dump(doc, fh)
        code, text, _ = run(self.args("show", "--index", "1"))
        self.assertEqual(code, 1)
        self.assertIn("was not in the last risk check", text)

    def test_yesterdays_check_does_not_count(self):
        self.run_risk(now="2026-11-12 09:36")
        code, text, _ = run(self.args("show", "--index", "1"))
        self.assertIn("not today", text)

    def test_blocked_orders_are_never_ready(self):
        self.assertEqual(self.run_risk(now="2026-11-13 09:25"), 1)
        code, text, _ = run(self.args("show", "--index", "1", now="2026-11-13 09:25"))
        self.assertIn("BLOCKED by trader-risk: window: no new entries before 09:30 IST", text)
        code, _, _ = run(self.args("approve", "--index", "1", "--reply", "yes", now="2026-11-13 09:25"))
        self.assertEqual(code, 1)

    def test_result_needs_an_approval_and_decline_is_logged(self):
        self.run_risk()
        code, _, err = run(self.args("result", "--index", "1", "--status", "placed"))
        self.assertEqual(code, 1)
        self.assertIn("no yes recorded", err)
        code, text, _ = run(self.args("decline", "--index", "1", "--reply", "no thanks"))
        self.assertEqual(code, 0)
        self.assertIn("Do not place it", text)
        code, text, _ = run(self.args("show", "--index", "1"))
        self.assertIn("DONE: declined", text)

    def test_a_skipped_order_is_logged_and_not_counted(self):
        self.run_risk()
        run(self.args("approve", "--index", "1", "--reply", "yes"))
        code, _, _ = run(self.args("result", "--index", "1", "--status", "skipped", "--note", "moved too fast"))
        self.assertEqual(code, 0)
        st = self.state_doc()
        self.assertEqual(st["orders"][-1]["status"], "skipped")
        res = check.check([hcl()], {"budget": 10000}, state=st, now=check.parse_now("2026-11-13 09:50"))
        self.assertEqual(res["today"]["entries_placed"], 0)

    def test_fill_sell_relieves_the_oldest_lot(self):
        pf = {"cash": 0, "positions": [{"ticker": "ITC.NS", "shares": 30, "lots": [
            {"id": "ITC.NS-1", "date": "2025-01-02", "shares": 20, "cost": 8000.0},
            {"id": "ITC.NS-2", "date": "2026-01-02", "shares": 10, "cost": 4100.0}]}]}
        with open(self.pf, "w") as fh:
            json.dump(pf, fh)
        code, text, _ = run(["fill", "--symbol", "ITC", "--side", "sell", "--qty", "25", "--price", "285",
                             "--date", TODAY, "--portfolio", self.pf, "--config", self.cfg, "--state", self.state])
        self.assertEqual(code, 0)
        self.assertIn("Cash now Rs 7,125", text)
        with open(self.pf) as fh:
            pf = json.load(fh)
        self.assertEqual(pf["cash"], 7125.0)
        lots = pf["positions"][0]["lots"]
        self.assertEqual([l["id"] for l in lots], ["ITC.NS-2"])
        self.assertEqual(lots[0]["shares"], 5)
        self.assertEqual(lots[0]["cost"], 2050.0)
        self.assertEqual(self.state_doc()["orders"][-1]["status"], "filled")
        code, _, err = run(["fill", "--symbol", "ITC.NS", "--side", "sell", "--qty", "50", "--price", "285",
                            "--portfolio", self.pf, "--config", self.cfg, "--state", self.state])
        self.assertEqual(code, 1)
        self.assertNotIn("Traceback", err)


if __name__ == "__main__":
    unittest.main()
