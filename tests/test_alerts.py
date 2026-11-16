"""trader-alerts tests. Fixtures in tests/fixtures/trader-alerts/: real Yahoo answers to
range=1d&interval=1d, fetched Sat Nov 14 2026, so each holds Friday Nov 13's close:
HCLTECH.NS 1378.00 (prev 1380.80), ITC.NS 285.00, RELIANCE.NS 1339.70, SBIN.NS 1080.00,
M&M.NS 3333.00 (prev 3399.00), and ZZZZ.NS, Yahoo's own 404 "No data found" body."""

import datetime
import gzip
import io
import json
import os
import shutil
import tempfile
import unittest
import urllib.error
from contextlib import redirect_stdout, redirect_stderr

from _load import load, ROOT, FIX

alerts = load("trader-alerts", "alerts")

QDIR = os.path.join(FIX, "trader-alerts")
PLAN = os.path.join(FIX, "trader-budget", "plan-hcl.json")
DT = datetime.datetime

# NSE circular NSE/CMTR/71775 (Dec 12 2025): the 2026 weekday trading holidays
NSE_2026 = ["2026-01-26", "2026-03-03", "2026-03-26", "2026-03-31", "2026-04-03", "2026-04-14", "2026-05-01",
            "2026-05-28", "2026-06-26", "2026-09-14", "2026-10-02", "2026-10-20", "2026-11-10", "2026-11-24",
            "2026-12-25"]


def ist(text):
    return alerts.parse_now(text)


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = alerts.main(argv)
    return code, out.getvalue(), err.getvalue()


def plan_rules():
    with open(PLAN) as fh:
        return alerts.rules_from_plan(json.load(fh))


class Calendar(unittest.TestCase):
    def test_holidays_match_the_nse_circular(self):
        self.assertEqual(sorted(alerts.NSE_HOLIDAYS), NSE_2026)
        for d in alerts.NSE_HOLIDAYS:
            self.assertLess(datetime.date.fromisoformat(d).weekday(), 5, d)
        self.assertEqual(alerts.EARLY_CLOSE, {})
        self.assertEqual((alerts.OPEN, alerts.CLOSE), (datetime.time(9, 15), datetime.time(15, 30)))

    def test_no_daylight_saving(self):
        for d in (DT(2026, 3, 8, 12), DT(2026, 11, 1, 12), DT(2026, 7, 1, 12), DT(2027, 1, 1, 12)):
            self.assertEqual(alerts.to_ist(d) - d, datetime.timedelta(hours=5, minutes=30))

    def test_parse_now(self):
        self.assertEqual(ist("2026-11-13T09:15"), DT(2026, 11, 13, 3, 45))
        self.assertEqual(ist("2026-07-01 09:15"), DT(2026, 7, 1, 3, 45))
        self.assertEqual(ist("2026-11-13T09:58:04Z"), DT(2026, 11, 13, 9, 58, 4))
        self.assertEqual(ist("2026-11-13T15:28:04+05:30"), DT(2026, 11, 13, 9, 58, 4))
        with self.assertRaises(alerts.AlertError):
            ist("tomorrow")

    def test_market_status(self):
        st = alerts.market_status(ist("2026-11-13T10:00"))
        self.assertTrue(st["open"])
        self.assertEqual((st["opens"], st["closes"]), ("09:15", "15:30"))
        self.assertFalse(alerts.market_status(ist("2026-11-13T09:14"))["open"])
        self.assertEqual(alerts.market_status(ist("2026-11-13T09:14"))["next_open"], "2026-11-13 09:15")
        after = alerts.market_status(ist("2026-11-13T15:30"))
        self.assertFalse(after["open"])
        self.assertEqual(after["next_open"], "2026-11-16 09:15")            # Friday -> Monday
        diwali = alerts.market_status(ist("2026-11-10T11:00"))
        self.assertFalse(diwali["open"])
        self.assertIn("Diwali-Balipratipada", diwali["reason"])
        self.assertEqual(diwali["next_open"], "2026-11-11 09:15")
        xmas = alerts.market_status(ist("2026-12-25T10:00"))
        self.assertFalse(xmas["open"])
        self.assertEqual(xmas["next_open"], "2026-12-28 09:15")
        self.assertTrue(alerts.market_status(ist("2026-12-24T15:00"))["open"])   # no early close
        self.assertTrue(alerts.market_status(ist("2026-11-26T10:00"))["open"])   # US Thanksgiving
        self.assertEqual(alerts.market_status(ist("2026-11-14T10:00"))["reason"], "weekend")
        self.assertFalse(alerts.market_status(ist("2026-11-08T18:30"))["open"])  # Muhurat trading Sunday
        self.assertFalse(alerts.market_status(ist("2027-03-01T10:00"))["calendar_known"])


class Quotes(unittest.TestCase):
    def test_yahoo_fixtures(self):
        with open(os.path.join(QDIR, "yahoo-HCLTECH.NS.json")) as fh:
            q = alerts.parse_yahoo(fh.read(), "HCLTECH.NS")
        self.assertEqual((q["symbol"], q["price"], q["prev_close"], q["currency"]), ("HCLTECH.NS", 1378.0, 1380.8, "INR"))
        self.assertEqual((q["high"], q["low"]), (1396.7, 1368.5))
        self.assertEqual(q["time"], "2026-11-13T09:58:04Z")                 # 15:28:04 IST
        with open(os.path.join(QDIR, "yahoo-M&M.NS.json")) as fh:
            q = alerts.parse_yahoo(fh.read(), "M&M")
        self.assertEqual((q["symbol"], q["price"], q["prev_close"]), ("M&M.NS", 3333.0, 3399.0))

    def test_urls_and_user_agent(self):
        self.assertTrue(alerts.UA.startswith("Mozilla/5.0 (compatible; "))
        self.assertEqual(alerts.yahoo_url("hcltech"),
                         "https://query2.finance.yahoo.com/v8/finance/chart/HCLTECH.NS?range=1d&interval=1d")
        self.assertIn("/chart/M%26M.NS?", alerts.yahoo_url("m&m"))
        self.assertIn("/chart/RELIANCE.NS?", alerts.yahoo_url("RELIANCE.NS"))
        self.assertIn("//query1.finance.yahoo.com/", alerts.yahoo_url("ITC", alerts.YAHOO_HOSTS[1]))
        self.assertFalse(hasattr(alerts, "stooq_url"))                       # US-only source, removed

    def test_offline_quotes_and_errors(self):
        q, errors = alerts.get_quotes(["HCLTECH", "ITC.NS", "ZZZZ", "NOPE"], "yahoo", QDIR)
        self.assertEqual(sorted(q), ["HCLTECH.NS", "ITC.NS"])
        self.assertEqual(q["ITC.NS"]["price"], 285.0)
        self.assertEqual(len(errors), 2)
        self.assertIn("No data found", errors[0])
        self.assertIn("no offline quote file", errors[1])

    def test_offline_gz(self):
        d = tempfile.mkdtemp()
        try:
            with open(os.path.join(QDIR, "yahoo-HCLTECH.NS.json"), "rb") as src:
                with gzip.open(os.path.join(d, "yahoo-HCLTECH.NS.json.gz"), "wb") as dst:
                    dst.write(src.read())
            q, errors = alerts.get_quotes(["HCLTECH"], "yahoo", d)
            self.assertEqual((q["HCLTECH.NS"]["price"], errors), (1378.0, []))
        finally:
            shutil.rmtree(d)


class FakeNet(object):
    """Stands in for urllib: answers each request with the next status code."""

    def __init__(self, codes, body=None):
        self.codes, self.calls, self.sleeps = list(codes), [], []
        with open(os.path.join(QDIR, "yahoo-HCLTECH.NS.json")) as fh:
            self.body = body or fh.read()

    def urlopen(self, req, timeout=None):
        self.calls.append((req.full_url.split("/")[2], req.get_header("User-agent")))
        code = self.codes.pop(0)
        if code != 200:
            fp = io.BytesIO(b'{"chart":{"result":null,"error":{"code":"Not Found",'
                            b'"description":"No data found, symbol may be delisted"}}}' if code == 404 else b"")
            raise urllib.error.HTTPError(req.full_url, code, "x", {}, fp)
        return io.BytesIO(self.body.encode("utf-8"))


class Network(unittest.TestCase):
    def setUp(self):
        self.saved = (alerts._urlopen, alerts._sleep)

    def tearDown(self):
        alerts._urlopen, alerts._sleep = self.saved

    def net(self, codes):
        f = FakeNet(codes)
        alerts._urlopen = f.urlopen
        alerts._sleep = f.sleeps.append
        return f

    def hosts(self, f):
        return [h.split(".")[0] for h, _ in f.calls]

    def test_query2_first_with_the_user_agent(self):
        f = self.net([200])
        q, errors = alerts.get_quotes(["HCLTECH"], "yahoo")
        self.assertEqual((q["HCLTECH.NS"]["price"], errors), (1378.0, []))
        self.assertEqual(f.calls, [("query2.finance.yahoo.com", alerts.UA)])

    def test_one_retry_with_a_pause_on_429(self):
        f = self.net([429, 200])
        self.assertEqual(alerts.get_quotes(["HCLTECH"], "yahoo")[0]["HCLTECH.NS"]["price"], 1378.0)
        self.assertEqual(self.hosts(f), ["query2", "query2"])
        self.assertEqual(f.sleeps, [alerts.BACKOFF])

    def test_falls_back_to_query1_on_429_and_5xx(self):
        f = self.net([429, 429, 200])
        self.assertIn("HCLTECH.NS", alerts.get_quotes(["HCLTECH"], "yahoo")[0])
        self.assertEqual(self.hosts(f), ["query2", "query2", "query1"])
        f = self.net([503, 200])
        self.assertIn("HCLTECH.NS", alerts.get_quotes(["HCLTECH"], "yahoo")[0])
        self.assertEqual(self.hosts(f), ["query2", "query1"])
        f = self.net([500, 502])
        q, errors = alerts.get_quotes(["HCLTECH"], "yahoo")
        self.assertEqual(q, {})
        self.assertIn("query1.finance.yahoo.com/v8/finance/chart/HCLTECH.NS answered HTTP 502", errors[0])

    def test_a_404_is_yahoos_answer_and_a_403_is_not_retried(self):
        f = self.net([404])
        q, errors = alerts.get_quotes(["NOPE"], "yahoo")
        self.assertIn("No data found", errors[0])
        self.assertEqual(self.hosts(f), ["query2"])
        f = self.net([403])
        q, errors = alerts.get_quotes(["HCLTECH"], "yahoo")
        self.assertIn("HTTP 403", errors[0])
        self.assertEqual(self.hosts(f), ["query2"])

    def test_a_pause_between_symbols(self):
        f = self.net([200, 200])
        alerts.get_quotes(["HCLTECH", "ITC"], "yahoo")
        self.assertEqual(f.sleeps, [alerts.PAUSE])


class Rules(unittest.TestCase):
    def setUp(self):
        self.q, _ = alerts.get_quotes(["HCLTECH", "ITC", "SBIN", "M&M"], "yahoo", QDIR)
        self.open = alerts.market_status(ist("2026-11-13T10:00"))
        self.now = ist("2026-11-13T10:00")

    def at(self, text, rules, state=None, quotes=None):
        now = ist(text)
        return alerts.evaluate(rules, self.q if quotes is None else quotes, alerts.market_status(now),
                               state or {}, now)

    def test_a_target_rings_once(self):
        rules = [{"id": "itc-280", "symbol": "ITC", "type": "above", "price": 280}]
        rings, st = alerts.evaluate(rules, self.q, self.open, {}, self.now)
        self.assertEqual(len(rings), 1)
        self.assertIn("ITC.NS is Rs 285.00: at or above your alert level Rs 280", rings[0]["message"])
        rings, st = alerts.evaluate(rules, self.q, self.open, st, self.now)
        self.assertEqual(rings, [])

    def test_stop_and_rearm(self):
        rules = [{"id": "sbin-stop", "symbol": "SBIN.NS", "type": "stop", "price": 1085, "rearm": True}]
        rings, st = alerts.evaluate(rules, self.q, self.open, {}, self.now)
        self.assertIn("your stop Rs 1085", rings[0]["message"])
        self.q["SBIN.NS"]["price"] = 1090.0
        rings, st = alerts.evaluate(rules, self.q, self.open, st, self.now)
        self.assertEqual(rings, [])
        self.assertNotIn("sbin-stop", st["rung"])
        self.q["SBIN.NS"]["price"] = 1080.0
        rings, st = alerts.evaluate(rules, self.q, self.open, st, self.now)
        self.assertEqual(len(rings), 1)

    def test_pct_move_from_previous_close(self):
        big = [{"id": "mm-3", "symbol": "M&M", "type": "pct_move", "pct": 3}]
        self.assertEqual(alerts.evaluate(big, self.q, self.open, {}, self.now)[0], [])
        small = [{"id": "mm-1", "symbol": "M&M", "type": "pct_move", "pct": 1.5, "direction": "down"}]
        rings, st = alerts.evaluate(small, self.q, self.open, {}, self.now)
        self.assertIn("M&M.NS moved -1.94% to Rs 3333.00 (from Rs 3399.00)", rings[0]["message"])
        self.assertEqual(alerts.evaluate(small, self.q, self.open, st, self.now)[0], [])
        up = [{"id": "mm-up", "symbol": "M&M", "type": "pct_move", "pct": 1, "direction": "up"}]
        self.assertEqual(alerts.evaluate(up, self.q, self.open, {}, self.now)[0], [])

    def test_opening_bell_once_per_trading_day(self):
        rules = [{"id": "bell", "type": "opening_bell"}]
        closed = alerts.market_status(ist("2026-11-13T09:00"))
        self.assertEqual(alerts.evaluate(rules, {}, closed, {}, ist("2026-11-13T09:00"))[0], [])
        rings, st = alerts.evaluate(rules, {}, self.open, {}, self.now)
        self.assertIn("Opening bell: the NSE is open (2026-11-13 10:00 IST)", rings[0]["message"])
        self.assertEqual(alerts.evaluate(rules, {}, self.open, st, ist("2026-11-13T11:00"))[0], [])
        nxt = alerts.market_status(ist("2026-11-16T09:16"))
        self.assertEqual(len(alerts.evaluate(rules, {}, nxt, st, ist("2026-11-16T09:16"))[0]), 1)

    def test_the_plan_gives_a_stop_a_target_and_a_flat_by(self):
        rules = plan_rules()
        self.assertEqual([(r["id"], r["type"]) for r in rules],
                         [("hcltech.ns-plan-stop", "stop"), ("hcltech.ns-plan-target", "target"),
                          ("hcltech.ns-flat-by", "time")])
        self.assertEqual((rules[0]["price"], rules[1]["price"]), (1377.4, 1399.0))
        self.assertEqual((rules[2]["at"], rules[2]["label"]), ("15:15", "flat by 15:15, before the auto square-off"))
        self.assertNotIn("before_close", rules[2])
        self.assertTrue(all(r["date"] == "2026-11-13" for r in rules))
        rings, st = self.at("2026-11-13 10:00", rules)           # 1378.00: between the stop and the target
        self.assertEqual(rings, [])
        q = json.loads(json.dumps(self.q))
        q["HCLTECH.NS"]["price"] = 1377.0
        rings, st = self.at("2026-11-13 11:30", rules, st, q)
        self.assertEqual([r["id"] for r in rings], ["hcltech.ns-plan-stop"])
        self.assertIn("HCLTECH.NS is Rs 1377.00: at or below your stop Rs 1377.40 (plan stop: opening-range "
                      "midpoint)", rings[0]["message"])
        q["HCLTECH.NS"]["price"] = 1399.0
        self.assertEqual([r["id"] for r in self.at("2026-11-13 12:00", rules, st, q)[0]], ["hcltech.ns-plan-target"])

    def test_the_flat_by_rings_once_per_trading_day(self):
        rules = plan_rules()[2:]
        self.assertEqual(self.at("2026-11-13 15:14", rules)[0], [])
        rings, st = self.at("2026-11-13 15:15", rules)
        self.assertEqual(len(rings), 1)
        self.assertIn("Flat by 15:15, before the auto square-off: it is 15:15 IST (set for 15:15), the market "
                      "closes at 15:30", rings[0]["message"])
        self.assertIn("trader-broker flatten --symbol HCLTECH.NS", rings[0]["message"])
        self.assertEqual(self.at("2026-11-13 15:20", rules, st)[0], [])
        rings, _ = self.at("2026-11-13 15:40", rules)
        self.assertIn("the market has closed", rings[0]["message"])
        self.assertEqual(self.at("2026-11-16 15:16", rules, st)[0], [])     # plan rules: their day only

    def test_a_time_alert_on_closed_days(self):
        rule = [{"id": "t", "type": "time", "at": "15:15", "label": "check"}]
        self.assertEqual(self.at("2026-11-14 15:16", rule)[0], [])         # Saturday: no session
        self.assertEqual(self.at("2026-11-10 15:16", rule)[0], [])         # Diwali-Balipratipada
        rings, st = self.at("2026-12-24 15:15", rule)                      # a full day on the NSE
        self.assertEqual(len(rings), 1)
        self.assertEqual(st["rung"]["t"], "2026-12-24T09:45:00Z")

    def test_the_example_rules_are_valid(self):
        with open(os.path.join(ROOT, "trader-alerts", "alerts.example.json")) as fh:
            rules = json.load(fh)["rules"]
        for r in rules:
            alerts.validate(r)
        self.assertEqual([r for r in rules if r["id"].startswith("hcltech.ns-plan") or r["id"] == "hcltech.ns-flat-by"],
                         plan_rules())

    def test_bad_rules(self):
        with self.assertRaises(alerts.AlertError):
            alerts.evaluate([{"id": "x", "type": "moon"}], {}, self.open, {}, self.now)
        with self.assertRaises(alerts.AlertError):
            alerts.evaluate([{"id": "x", "type": "above", "symbol": "ITC"}], {}, self.open, {}, self.now)
        with self.assertRaises(alerts.AlertError):
            alerts.evaluate([{"id": "x", "type": "time", "at": "3pm"}], {}, self.open, {}, self.now)
        with self.assertRaises(alerts.AlertError):
            alerts.rules_from_plan({"symbol": "HCLTECH", "stop": 1377.4})


class Cli(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.rules = os.path.join(self.d, "alerts.json")
        self.state = os.path.join(self.d, "state", "alerts.json")
        self.prices = os.path.join(self.d, "prices.json")

    def tearDown(self):
        shutil.rmtree(self.d)

    def check(self, now):
        return run(["check", "--rules", self.rules, "--state", self.state, "--prices-out", self.prices,
                    "--offline", QDIR, "--now", now])

    def test_the_example_trade_from_the_plan(self):
        code, text, _ = run(["add", "--from-plan", "--plan", PLAN, "--rules", self.rules, "--state", self.state,
                             "--config", os.path.join(self.d, "none")])
        self.assertEqual(code, 0)
        self.assertIn("Added hcltech.ns-flat-by", text)
        self.assertEqual(run(["add", "--rules", self.rules, "--opening-bell"])[0], 0)

        code, text, _ = self.check("2026-11-13 09:16")
        self.assertEqual(code, 0)                                      # the opening bell rings first
        code, text, _ = self.check("2026-11-13 09:17")
        self.assertEqual(code, 1)
        self.assertIn("Nothing hit. 4 rule(s) watched today, HCLTECH.NS Rs 1378.00.", text)
        with open(self.prices) as fh:
            doc = json.load(fh)
        self.assertEqual(doc["prices"], {"HCLTECH.NS": 1378.0})
        self.assertEqual(doc["detail"]["HCLTECH.NS"]["time"], "2026-11-13T09:58:04Z")
        self.assertEqual(doc["detail"]["HCLTECH.NS"]["fetched"], "2026-11-13T03:47:00Z")

        code, text, _ = self.check("2026-11-13 15:15")
        self.assertEqual(code, 0)
        self.assertIn("ALERT Flat by 15:15", text)
        self.assertIn("not an order", text)
        self.assertEqual(self.check("2026-11-13 15:17")[0], 1)
        code, text, _ = self.check("2026-11-16 09:20")
        self.assertIn("ALERT Opening bell", text)
        code, text, _ = self.check("2026-11-16 09:25")
        self.assertIn("Nothing hit. 1 rule(s) watched today.", text)

        # a new plan replaces the plan rules and re-arms them
        code, text, _ = run(["add", "--from-plan", "--plan", PLAN, "--rules", self.rules, "--state", self.state])
        with open(self.rules) as fh:
            ids = [r["id"] for r in json.load(fh)["rules"]]
        self.assertEqual(sorted(ids), ["hcltech.ns-flat-by", "hcltech.ns-plan-stop", "hcltech.ns-plan-target",
                                       "opening-bell"])
        with open(self.state) as fh:
            self.assertNotIn("hcltech.ns-flat-by", json.load(fh)["rung"])

    def test_a_portfolio_evening_and_morning(self):
        for args in (["--opening-bell"], ["--symbol", "ITC", "--above", "290"], ["--symbol", "SBIN", "--stop", "1070"]):
            code, _, _ = run(["add", "--rules", self.rules] + args)
            self.assertEqual(code, 0)
        code, _, err = run(["add", "--rules", self.rules, "--symbol", "ITC", "--above", "290"])
        self.assertEqual(code, 1)
        self.assertIn("already exists", err)

        code, text, _ = self.check("2026-11-13T15:40")
        self.assertEqual(code, 1)
        self.assertIn("Nothing hit", text)
        self.assertIn("NSE closed", text)
        with open(self.prices) as fh:
            doc = json.load(fh)
        self.assertEqual(doc["prices"], {"ITC.NS": 285.0, "SBIN.NS": 1080.0})

        code, text, _ = self.check("2026-11-16T09:16")
        self.assertEqual(code, 0)
        self.assertIn("ALERT Opening bell", text)
        code, text, _ = self.check("2026-11-16T09:30")
        self.assertEqual(code, 1)

        code, text, _ = run(["list", "--rules", self.rules, "--state", self.state])
        self.assertIn("rang", text)
        self.assertEqual(run(["reset", "opening-bell", "--state", self.state])[0], 0)
        self.assertEqual(run(["reset", "opening-bell", "--state", self.state])[0], 1)

    def test_add_time_and_target(self):
        code, text, _ = run(["add", "--rules", self.rules, "--at", "15:15", "--label", "flat by 15:15",
                             "--symbol", "hcltech"])
        self.assertEqual(code, 0)
        code, text, _ = run(["add", "--rules", self.rules, "--symbol", "HCLTECH", "--target", "1391.80",
                             "--date", "2026-11-13"])
        self.assertEqual(code, 0)
        with open(self.rules) as fh:
            rules = json.load(fh)["rules"]
        self.assertEqual(rules[0], {"id": "time-1515", "type": "time", "at": "15:15", "label": "flat by 15:15",
                                    "symbol": "HCLTECH.NS"})
        self.assertEqual(rules[1], {"id": "hcltech.ns-target-1391.80", "symbol": "HCLTECH.NS", "type": "target",
                                    "price": 1391.8, "date": "2026-11-13"})
        self.assertEqual(run(["add", "--rules", self.rules, "--at", "3pm"])[0], 1)
        code, _, err = run(["add", "--rules", self.rules, "--from-plan", "--plan", os.path.join(self.d, "none")])
        self.assertEqual(code, 1)
        self.assertIn("no plan", err)
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):     # the NYSE early-close flag is gone
            alerts.main(["add", "--rules", self.rules, "--at", "15:15", "--before-close"])

    def test_quote_write_merges(self):
        code, text, _ = run(["quote", "HCLTECH", "ITC", "--offline", QDIR, "--write", self.prices,
                             "--now", "2026-11-13T10:00:00Z"])
        self.assertEqual(code, 0)
        self.assertIn("HCLTECH.NS     Rs 1378.00 (-0.20% vs prev close Rs 1380.80)", text)
        self.assertIn("delayed", text)
        run(["quote", "SBIN", "--offline", QDIR, "--write", self.prices])
        with open(self.prices) as fh:
            doc = json.load(fh)
        self.assertEqual(sorted(doc["prices"]), ["HCLTECH.NS", "ITC.NS", "SBIN.NS"])
        self.assertEqual(doc["detail"]["ITC.NS"]["prev_close"], 284.05)
        self.assertEqual(doc["detail"]["ITC.NS"]["fetched"], "2026-11-13T10:00:00Z")

    def test_quote_holdings_from_portfolio_and_plan(self):
        pf = os.path.join(self.d, "portfolio.json")
        with open(pf, "w") as fh:
            json.dump({"cash": 0, "positions": [{"ticker": "ITC", "shares": 1}]}, fh)
        code, text, _ = run(["quote", "--holdings", "--portfolio", pf, "--plan", PLAN, "--offline", QDIR, "--json"])
        self.assertEqual(code, 0)
        self.assertEqual(sorted(json.loads(text)["quotes"]), ["HCLTECH.NS", "ITC.NS"])

    def test_clock_exit_codes(self):
        code, text, _ = run(["clock", "--now", "2026-11-13 10:15"])
        self.assertEqual(code, 0)
        self.assertIn("NSE OPEN", text)
        self.assertIn("Today's session: 09:15 to 15:30 IST.", text)
        code, text, _ = run(["clock", "--now", "2026-12-25T10:00"])
        self.assertEqual(code, 1)
        self.assertIn("Christmas", text)
        self.assertIn("Next open: 2026-12-28 09:15 IST.", text)

    def test_check_without_rules(self):
        code, _, err = run(["check", "--rules", self.rules, "--offline", QDIR])
        self.assertEqual(code, 1)
        self.assertIn("no rules", err)


if __name__ == "__main__":
    unittest.main()
