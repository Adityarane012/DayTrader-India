"""trader-timemachine tests. Fixture in tests/fixtures/trader-timemachine/:

HCLTECH-60d5m.json.gz  Yahoo v8 chart for HCLTECH.NS, range=60d interval=5m, fetched Sat
                       Nov 14 2026 (real data, Aug 18 to Nov 13 2026). Like all of Yahoo's
                       NSE bars it has gaps: the 15:15, 15:20 and 15:25 bars are usually
                       empty, and Oct 15 lacks 11:45 and 11:50.

The Monte Carlo numbers are regression pins: this code's output on the fixture, kept
so any change to the draws shows. The history replay is checked against an
independent re-count of the same rule (IndependentHistory below).
"""

import copy
import datetime
import gzip
import hashlib
import io
import json
import math
import os
import random
import shutil
import tempfile
import unittest
import urllib.error
from contextlib import redirect_stdout, redirect_stderr

from _load import load, FIX

tm = load("trader-timemachine", "timemachine")

DIR = os.path.join(FIX, "trader-timemachine")
HCL = os.path.join(DIR, "HCLTECH-60d5m.json.gz")
with gzip.open(HCL, "rt", encoding="utf-8") as _fh:
    TEXT = _fh.read()
NOW = "2026-11-13 10:50"
NOW_UTC = tm.parse_now(NOW)

# the worked example's plan, as trader-exit writes it
PLAN = {"created_by": "trader-exit", "symbol": "HCLTECH.NS", "side": "buy", "date": "2026-11-13", "setup": "orb",
        "entry": 1384.6, "entry_time": "9:35 AM", "entry_bar": 3, "interval": "5m",
        "opening_range": {"high": 1381.0, "low": 1373.8, "minutes": 15},
        "stop": 1377.4, "stop_rule": "or_mid", "stop_label": "opening-range midpoint",
        "target": 1391.8, "target_r": 1.0, "target_label": "1R (one times the risk)",
        "risk_per_share": 7.2, "reward_risk": 1.0, "flat_by": "15:15"}

# regression pins (seed 19, 10,000 replays, to the 15:15 flat-by)
SIM_BANDS = "92de1d86e89142af"
SIM_PATHS = "1b1e752a115de01c"
SIM_TRADES = "5c6ff6363e641f09"
SIM_HIST = {"lo": 1341.21, "hi": 1420.91,
            "bins": [118, 125, 165, 198, 317, 412, 490, 638, 643, 718, 783, 790, 711, 743, 667, 522, 484, 383,
                     300, 222, 192, 108, 72, 50]}


def sha(x):
    return hashlib.sha256(json.dumps(x).encode("utf-8")).hexdigest()[:16]


def plan(**kw):
    raw = dict(PLAN)
    raw.update(kw)
    return tm.normalize_plan(raw)


def machine(p=None, text=TEXT, now=NOW_UTC, **kw):
    return tm.time_machine(text, p or plan(), now, **kw)


def edited(fn):
    """The fixture's chart JSON, changed by fn(result), back as text."""
    doc = json.loads(TEXT)
    fn(doc["chart"]["result"][0])
    return json.dumps(doc)


def keep_bars(result, keep):
    """Keep only the bars where keep(ts) is true."""
    q = result["indicators"]["quote"][0]
    idx = [i for i, ts in enumerate(result["timestamp"]) if keep(ts)]
    result["timestamp"] = [result["timestamp"][i] for i in idx]
    for k in q:
        q[k] = [q[k][i] for i in idx]


def ist(ts):
    return tm.to_ist(tm.utc_of(ts))


def pool_dates():
    days = tm.split_sessions(tm.parse_bars(tm.chart_result(TEXT, "HCLTECH.NS"), NOW_UTC)[1])
    return [d for d, _ in tm.full_sessions(days, "2026-11-13", 72)[0]]


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = tm.main(argv)
    return code, out.getvalue(), err.getvalue()


class TheExample(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.doc = machine()

    def test_the_odds(self):
        m = self.doc["mc"]
        self.assertEqual((m["replays"], m["seed"], m["window"], m["until"]), (10000, 19, 2, "15:15"))
        self.assertEqual(m["pool_sessions"], 58)
        self.assertEqual(m["bars_left"], 68)
        self.assertEqual((m["pool_from"], m["pool_to"]), ("2026-08-18", "2026-11-12"))
        self.assertEqual(m["p_target"], 0.5048)
        self.assertEqual(m["p_stop"], 0.4932)
        self.assertEqual(m["p_neither"], 0.002)
        self.assertEqual(m["p_green"], 0.5055)
        self.assertEqual(m["median_close"], 1379.19)
        self.assertEqual(m["p5_close"], 1352.1)
        self.assertEqual(m["p95_close"], 1407.91)
        self.assertEqual(m["avg_R"], 0.011)
        self.assertEqual(m["r_at_target"], 1.0)

    def test_regression_pins(self):
        m = self.doc["mc"]
        self.assertEqual(sha(m["bands"]), SIM_BANDS)
        self.assertEqual(len(m["sample_paths"]), 160)
        self.assertEqual(sha(m["sample_paths"]), SIM_PATHS)
        self.assertEqual(m["hist"], SIM_HIST)
        self.assertEqual(m["bands"][-1], [1351.4, 1367.97, 1380.09, 1391.46, 1409.05])

    def test_the_history_replay(self):
        h = self.doc["history"]
        self.assertEqual((h["sessions"], h["triggered"]), (58, 32))
        self.assertEqual((h["target"], h["stop"], h["close"], h["green"]), (9, 13, 10, 11))
        self.assertEqual(h["avg_R"], -0.216)
        self.assertEqual(h["rule"], {"setup": "orb", "or_minutes": 15, "stop_rule": "or_mid", "target_r": 1.0})
        slim = [{"date": t["date"], "entry": t["entry"], "outcome": t["outcome"], "R": t["R"]} for t in h["trades"]]
        self.assertEqual(sha(slim), SIM_TRADES)
        first = h["trades"][0]
        self.assertEqual((first["date"], first["time"], first["entry"], first["stop"], first["target"], first["outcome"]),
                         ("2026-08-19", "1:25 PM", 1321.9, 1316.2, 1327.6, "close"))   # on the Rs 0.10 tick

    def test_the_verdict_says_coin_flip(self):
        self.assertEqual(self.doc["verdict"], "Close to a coin flip: target first 50.5 % vs stop first 49.3 %.")
        gap, share, even = tm.lean(self.doc["mc"])
        self.assertEqual((round(share, 3), even), (0.506, 0.5))
        self.assertEqual(self.doc["verdict_notes"], [])

    def test_bands_start_at_the_entry(self):
        m = self.doc["mc"]
        self.assertEqual(m["bands"][0], [1384.6] * 5)
        self.assertEqual(len(m["bands"]), 69)
        self.assertEqual((m["band_times"][0], m["band_times"][-1], len(m["band_times"])), ("09:35", "15:15", 69))
        self.assertTrue(all(p[0] == 1384.6 and len(p) == 69 for p in m["sample_paths"]))

    def test_the_plan_is_carried_through(self):
        p = self.doc["plan"]
        self.assertEqual((p["symbol"], p["entry"], p["stop"], p["target"], p["entry_bar"], p["entry_time"]),
                         ("HCLTECH.NS", 1384.6, 1377.4, 1391.8, 3, "9:35 AM"))
        self.assertEqual((p["risk_per_share"], p["target_r"], p["flat_by"]), (7.2, 1.0, "15:15"))
        self.assertEqual(self.doc["warnings"], [])
        self.assertEqual(self.doc["data"]["last_bar"], "2026-11-13 10:45 IST")

    def test_the_text_report(self):
        text = "\n".join(tm.report(self.doc))
        for line in ("HCLTECH.NS buy, Friday 2026-11-13: entry 1384.60 at 9:35 AM (bar 3), stop 1377.40, target 1391.80",
                     "10,000 replays", "9:35 AM to 3:15 PM (68 five-minute bars)", "seed 19", "58 full sessions",
                     "target first   50.5 %", "stop first     49.3 %", "neither        0.2 %    still open at 3:15 PM",
                     "green          50.5 %", "median 1379.19, 90 % of replays between 1352.10 and 1407.91",
                     "Average R: +0.011", "fired 32 times: 9 target, 13 stop, 10 neither. Average R -0.216",
                     "Close to a coin flip: target first 50.5 % vs stop first 49.3 %.",
                     "Left out 1 short session(s) (gaps in the data): 2026-10-15.", "not a prediction", "--seed 19"):
            self.assertIn(line, text)
        for word in ("profit", "P&L", "guarantee", "real time", "tick by tick", "dollar", "$"):
            self.assertNotIn(word, text)


class IndependentHistory(unittest.TestCase):
    """The history numbers, counted again without the time machine's own code: the
    fixture's raw bars, the 15-minute range, the first close above it, a stop at the
    midpoint rounded down to the tick, a 1R target, stop checked first, out at 15:15."""

    def test_the_same_counts_from_scratch(self):
        self.assertEqual(self.count(1), {"sessions": 58, "fired": 32, "target": 9, "stop": 13, "neither": 10})
        # the worked example's own plan: the 2R target is reached on 2 of the 32 days
        self.assertEqual(self.count(2), {"sessions": 58, "fired": 32, "target": 2, "stop": 16, "neither": 14})

    def count(self, target_r):
        res = json.loads(TEXT)["chart"]["result"][0]
        q = res["indicators"]["quote"][0]
        days = {}
        for i, ts in enumerate(res["timestamp"]):
            if None in (q["open"][i], q["high"][i], q["low"][i], q["close"][i]):
                continue
            lt = datetime.datetime(1970, 1, 1) + datetime.timedelta(seconds=ts, hours=5, minutes=30)
            slot = (lt.hour * 60 + lt.minute - (9 * 60 + 15)) // 5
            if 0 <= slot < 75:
                days.setdefault(lt.date().isoformat(), {})[slot] = (q["high"][i], q["low"][i], q["close"][i])
        last = 71                                   # the 15:10 bar, the last one before the 15:15 flat-by
        count = {"sessions": 0, "fired": 0, "target": 0, "stop": 0, "neither": 0}
        for day in sorted(days):
            s = days[day]
            if day >= "2026-11-13" or not all(i in s for i in range(last + 1)):
                continue
            count["sessions"] += 1
            oh, ol = max(s[i][0] for i in range(3)), min(s[i][1] for i in range(3))
            k = next((i for i in range(3, last + 1) if s[i][2] > oh), None)
            if k is None:
                continue
            e = round(s[k][2], 2)
            tick = 0.10                              # HCLTECH traded 1,300 to 1,450 all along
            self.assertTrue(1000 < e <= 5000)
            stop = math.floor(round((oh + ol) / 2 / tick, 6)) * tick
            if e - stop <= 0:
                continue
            count["fired"] += 1
            target = math.floor(round((e + target_r * (e - stop)) / tick, 6)) * tick
            out = "neither"
            for i in range(k + 1, last + 1):
                if s[i][1] <= stop:
                    out = "stop"
                    break
                if s[i][0] >= target:
                    out = "target"
                    break
            count[out] += 1
        return count


class TheWorkedExampleAt2R(unittest.TestCase):
    """The README's trade: the same entry and stop with trader-exit's default 2R target, 1399.00
    (a 1R target does not clear costs on a Rs 10,000 account). The plan is the fixture
    trader-exit wrote, tests/fixtures/trader-budget/plan-hcl.json."""

    @classmethod
    def setUpClass(cls):
        with open(os.path.join(FIX, "trader-budget", "plan-hcl.json")) as fh:
            cls.doc = machine(tm.normalize_plan(json.load(fh)))

    def test_the_odds(self):
        m = self.doc["mc"]
        self.assertEqual((m["r_at_target"], m["until"], m["pool_sessions"]), (2.0, "15:15", 58))
        self.assertEqual((m["p_target"], m["p_stop"], m["p_neither"], m["p_green"], m["avg_R"]),
                         (0.2696, 0.6783, 0.0521, 0.3063, -0.118))
        self.assertEqual(self.doc["verdict"], "Close to break-even: at 2R the target has to come first in 33 % of "
                                              "the replays that hit one side; it did in 28 % (target first 27.0 % "
                                              "vs stop first 67.8 %).")

    def test_the_history_matches_the_independent_count(self):
        h = self.doc["history"]
        self.assertEqual((h["sessions"], h["triggered"], h["target"], h["stop"], h["close"]), (58, 32, 2, 16, 14))
        self.assertEqual(h["avg_R"], -0.375)
        self.assertEqual(h["rule"], {"setup": "orb", "or_minutes": 15, "stop_rule": "or_mid", "target_r": 2.0})


class Seeds(unittest.TestCase):
    def test_same_seed_same_numbers(self):
        a = machine(replays=2000, seed=5)["mc"]
        b = machine(replays=2000, seed=5)["mc"]
        self.assertEqual(a, b)

    def test_another_seed_gives_other_numbers(self):
        m = machine(seed=7)["mc"]
        self.assertEqual((m["p_target"], m["p_stop"]), (0.5137, 0.4845))
        self.assertAlmostEqual(m["p_target"] + m["p_stop"] + m["p_neither"], 1.0, places=6)
        self.assertNotEqual(sha(m["bands"]), SIM_BANDS)

    def test_the_draws_are_stable_across_pythons(self):
        # random.Random(seed), randint and choice are stable since Python 3.2; this pins the first
        # draws so a failure points at the RNG
        r = random.Random(19)
        self.assertEqual([r.randint(-2, 2) for _ in range(8)], [-2, 2, -2, 2, -1, 1, 0, 2])
        self.assertEqual(r.choice(range(59)), 18)

    def test_window_and_replays(self):
        a = machine(replays=500, window=0)["mc"]
        self.assertEqual((a["replays"], a["window"]), (500, 0))
        self.assertNotEqual(a["bands"], machine(replays=500)["mc"]["bands"])
        with self.assertRaises(tm.TMError):
            machine(replays=0)
        with self.assertRaises(tm.TMError):
            machine(window=11)


class Bars(unittest.TestCase):
    def setUp(self):
        self.result = tm.chart_result(TEXT, "HCLTECH.NS")

    def test_empty_bars_and_bars_after_now_are_dropped(self):
        meta, bars, dropped = tm.parse_bars(self.result, NOW_UTC)
        self.assertEqual(dropped, {"no_price": 112, "off_grid": 0, "not_complete": 54, "outside_hours": 0})
        last = bars[-1]
        self.assertEqual((last["date"], last["start"], last["slot"]), ("2026-11-13", "10:45", 18))
        entry = [b for b in bars if b["date"] == "2026-11-13" and b["slot"] == 3][0]
        self.assertEqual((entry["start"], entry["c"]), ("09:30", 1384.5999755859375))

    def test_yahoo_leaves_out_the_last_nse_bars(self):
        days = tm.split_sessions(tm.parse_bars(self.result, NOW_UTC)[1])
        full_75 = [d for d, s in days.items() if len(s) == 75]
        self.assertEqual(full_75, [])                  # not one session has all 75 bars
        missing = {}
        for d, s in days.items():
            if d < "2026-11-13":
                for i in range(75):
                    if i not in s:
                        missing[i] = missing.get(i, 0) + 1
        self.assertEqual(sorted(missing), [30, 31, 72, 73, 74])    # 11:45/11:50 once, 15:15 to 15:25 often
        self.assertEqual(missing[30], 1)

    def test_now_pins_the_clock(self):
        bars = tm.parse_bars(self.result, tm.parse_now("2026-11-13 09:32"))[1]
        today = [b for b in bars if b["date"] == "2026-11-13"]
        self.assertEqual(len(today), 3)
        with self.assertRaises(tm.TMError) as cm:
            machine(now=tm.parse_now("2026-11-13 09:32"))
        self.assertIn("not in the data", str(cm.exception))
        self.assertIn("09:25 bar", str(cm.exception))
        self.assertEqual(machine(now=tm.parse_now("2026-11-13 09:35"), replays=200)["mc"]["pool_sessions"], 58)

    def test_no_daylight_saving(self):
        stamps = [1793331900,   # 2026-10-30 03:45Z = 9:15 IST
                  1793591100,   # 2026-11-02 03:45Z = 9:15 IST (the US clocks changed on Nov 1; India's did not)
                  1793587500,   # 2026-11-02 02:45Z = 8:15 IST, before the open
                  1793611800]   # 2026-11-02 09:30Z = 15:00 IST
        res = {"meta": {"symbol": "X.NS"}, "timestamp": stamps,
               "indicators": {"quote": [{"open": [1] * 4, "high": [1] * 4, "low": [1] * 4, "close": [1] * 4,
                                         "volume": [0] * 4}]}}
        meta, bars, dropped = tm.parse_bars(res, tm.parse_now("2026-11-03T00:00Z"))
        self.assertEqual([(b["date"], b["start"], b["slot"]) for b in bars],
                         [("2026-10-30", "09:15", 0), ("2026-11-02", "09:15", 0), ("2026-11-02", "15:00", 69)])
        self.assertEqual(dropped["outside_hours"], 1)

    def test_a_session_with_a_gap_is_left_out(self):
        doc = machine(replays=300)
        self.assertEqual(doc["data"]["short_sessions_left_out"], [{"date": "2026-10-15", "bars": 70}])
        self.assertNotIn("2026-10-15", [t["date"] for t in doc["history"]["trades"]])

    def test_today_is_not_in_the_pool(self):
        doc = machine(replays=200)
        self.assertEqual(doc["mc"]["pool_to"], "2026-11-12")
        self.assertNotIn("2026-11-13", [t["date"] for t in doc["history"]["trades"]])

    def test_a_missing_price_is_dropped(self):
        def hole(res):
            res["indicators"]["quote"][0]["close"][5] = None
        doc = machine(text=edited(hole), replays=200)
        self.assertEqual(doc["data"]["dropped"]["no_price"], 113)
        self.assertEqual(doc["mc"]["pool_sessions"], 57)   # 2026-08-18 now has a gap at 9:40

    def test_empty_and_broken_data(self):
        empty = json.dumps({"chart": {"result": [{"meta": {"symbol": "HCLTECH.NS"}, "timestamp": [],
                                                  "indicators": {"quote": [{}]}}], "error": None}})
        with self.assertRaises(tm.TMError) as cm:
            machine(text=empty)
        self.assertIn("no complete 5-minute bars", str(cm.exception))
        gone = json.dumps({"chart": {"result": None, "error": {"code": "Not Found",
                                                               "description": "No data found, symbol may be delisted"}}})
        with self.assertRaises(tm.TMError) as cm:
            machine(text=gone)
        self.assertIn("No data found", str(cm.exception))
        with self.assertRaises(tm.TMError):
            machine(text="<html>rate limited</html>")

    def test_fewer_than_20_sessions_is_refused(self):
        dates = pool_dates()
        nineteen, twenty = dates[-19], dates[-20]

        def trim(res):
            keep_bars(res, lambda ts: ist(ts).date().isoformat() >= nineteen)
        with self.assertRaises(tm.TMError) as cm:
            machine(text=edited(trim))
        self.assertIn("only 19 full session(s)", str(cm.exception))
        self.assertIn("at least 20", str(cm.exception))

        def keep20(res):
            keep_bars(res, lambda ts: ist(ts).date().isoformat() >= twenty)
        self.assertEqual(machine(text=edited(keep20), replays=200)["mc"]["pool_sessions"], 20)

    def test_a_replay_to_the_close_finds_too_few_sessions_and_says_why(self):
        with self.assertRaises(tm.TMError) as cm:
            machine(until="15:30", replays=10)
        msg = str(cm.exception)
        self.assertIn("only 0 session(s) of HCLTECH.NS before 2026-11-13 have every bar to 3:30 PM", msg)
        self.assertIn("15:15 to 15:25", msg)
        self.assertIn("--until 15:15", msg)

    def test_the_data_must_be_the_plans_symbol(self):
        with self.assertRaises(tm.TMError) as cm:
            machine(plan(symbol="INFY"))
        self.assertIn("data is for HCLTECH.NS but the plan is for INFY.NS", str(cm.exception))


class Plans(unittest.TestCase):
    def test_an_entry_not_in_the_data_is_refused(self):
        with self.assertRaises(tm.TMError) as cm:
            machine(plan(date="2026-11-16"))
        self.assertIn("not in the data", str(cm.exception))
        self.assertIn("no bars for that day", str(cm.exception))
        with self.assertRaises(tm.TMError) as cm:      # the 10:50 bar has not closed in this clock yet
            machine(plan(entry_time="10:55 AM", entry_bar=None))
        self.assertIn("not in the data", str(cm.exception))

    def test_plan_checks(self):
        cases = [
            (dict(entry_time="9:37 AM", entry_bar=None), "5-minute grid"),
            (dict(entry_time="3:30 PM", entry_bar=None), "between 9:20 AM and 3:25 PM"),
            (dict(entry_bar=4), "disagrees with itself"),
            (dict(entry_time=None, entry_bar=None), "entry_time"),
            (dict(interval="1m"), "7 days of 1-min bars"),
            (dict(stop=1385.0), "stop < entry < target"),
            (dict(side="short"), "buy or sell"),
            (dict(symbol=""), "NSE symbol"),
            (dict(symbol="RELIANCE NS"), "NSE symbol"),
            (dict(entry="abc"), "number for entry"),
            (dict(date="Nov 13"), "date like"),
            (dict(opening_range={"minutes": 7}), "multiple of 5"),
        ]
        for change, words in cases:
            with self.assertRaises(tm.TMError, msg=change) as cm:
                plan(**change)
            self.assertIn(words, str(cm.exception), change)

    def test_nse_symbols(self):
        self.assertEqual(plan(symbol="hcltech")["symbol"], "HCLTECH.NS")
        self.assertEqual(plan(symbol="M&M")["symbol"], "M&M.NS")
        self.assertEqual(plan(symbol="BAJAJ-AUTO.NS")["symbol"], "BAJAJ-AUTO.NS")
        self.assertEqual(plan(symbol="500325.BO")["symbol"], "500325.BO")

    def test_entry_bar_or_entry_time_alone(self):
        self.assertEqual(plan(entry_time=None)["entry_time"], "9:35 AM")
        self.assertEqual(plan(entry_bar=None)["entry_bar"], 3)
        self.assertEqual(plan(entry_time="9:35", entry_bar=None)["entry_bar"], 3)
        self.assertEqual(plan(entry_time="9:35am", entry_bar=None)["entry_bar"], 3)

    def test_until_defaults_to_the_plans_flat_by(self):
        self.assertEqual(machine(replays=300)["mc"]["until"], "15:15")
        self.assertEqual(machine(plan(flat_by="15:00"), replays=300)["mc"]["until"], "15:00")
        self.assertEqual(machine(plan(flat_by=None), replays=300)["mc"]["until"], "15:15")   # the pack's default

    def test_until_cuts_the_replay(self):
        doc = machine(until="15:00", replays=500)
        m = doc["mc"]
        self.assertEqual((m["until"], m["bars_left"], m["band_times"][-1]), ("15:00", 65, "15:00"))
        self.assertIn("still open at 3:00 PM", "\n".join(tm.report(doc)))
        self.assertEqual(machine(until="3:00 PM", replays=500)["mc"], m)
        for bad, words in (("9:35 AM", "nothing to replay"), ("15:35", "no later than 3:30 PM"),
                           ("15:07", "5-minute grid"), ("noon", "India time")):
            with self.assertRaises(tm.TMError) as cm:
                machine(until=bad, replays=10)
            self.assertIn(words, str(cm.exception), bad)

    def test_an_entry_outside_its_bar_is_flagged(self):
        doc = machine(plan(entry=1395.0, stop=1390.0, target=1400.0), replays=200)
        self.assertIn("outside that bar's range", doc["warnings"][0])

    def test_stop_rounds_away_from_the_entry(self):
        self.assertEqual(tm.cents_away(1377.425, True), 1377.4)      # the Rs 0.10 tick above 1,000
        self.assertEqual(tm.cents_away(1377.425, False), 1377.5)
        self.assertEqual(tm.cents_away(285.123, True), 285.1)        # Rs 0.05 from 250 to 1,000
        self.assertEqual(tm.cents_away(187.449, True), 187.44)       # Rs 0.01 below 250
        self.assertEqual(tm.target_tick(1391.87, True, 1384.6), 1391.8)
        self.assertEqual([tm.tick_paise(x) for x in (249.99, 250, 1000, 1000.05, 5000, 5000.5, 10000, 10001,
                                                     20000, 20005)], [1, 5, 5, 10, 10, 50, 50, 100, 100, 500])
        self.assertEqual(tm.cents_away(1373.800048828125, True), 1373.8)
        self.assertEqual(tm.cents_away(1373.7999999999997, True), 1373.8)

    def test_the_stop_rule_is_worked_out_when_not_given(self):
        rule = machine(plan(stop_rule=None), replays=100)["history"]["rule"]
        self.assertEqual(rule["stop_rule"], "or_mid")
        rule = machine(plan(stop_rule=None, stop=1373.8, target=1395.4), replays=100)["history"]["rule"]
        self.assertEqual((rule["stop_rule"], rule["target_r"]), ("or_low", 1.0))
        rule = machine(plan(stop_rule="atr", stop=1376.76, target=1400.28), replays=100)["history"]["rule"]
        self.assertEqual((rule["stop_rule"], rule["stop_pct"], rule["target_r"]), ("pct", 0.5662, 2.0))

    def test_a_setup_other_than_orb_skips_the_history(self):
        doc = machine(plan(setup="flag"), replays=200)
        self.assertIsNone(doc["history"]["rule"])
        self.assertIn("orb", doc["history"]["note"])
        self.assertEqual(doc["mc"]["pool_sessions"], 58)
        self.assertIn("History: skipped", "\n".join(tm.report(doc)))

    def test_a_sell_plan_mirrors_the_rules(self):
        doc = machine(plan(side="sell", stop=1391.8, target=1377.4, stop_rule="or_high"), replays=2000)
        m = doc["mc"]
        self.assertAlmostEqual(m["p_target"] + m["p_stop"] + m["p_neither"], 1.0, places=6)
        self.assertEqual(m["r_at_target"], 1.0)
        self.assertEqual(doc["history"]["rule"]["stop_rule"], "or_high")
        for t in doc["history"]["trades"]:
            self.assertTrue(t["target"] < t["entry"] < t["stop"], t)
        self.assertIn("below the entry", "\n".join(tm.report(doc)))

    def test_the_verdict_thresholds_at_1r(self):
        # 1R: the target's share of the replays that hit one side against 50 %
        self.assertTrue(tm.verdict({"p_target": 0.30, "p_stop": 0.26}).startswith("Close to a coin flip"))
        self.assertTrue(tm.verdict({"p_target": 0.40, "p_stop": 0.30}).startswith("Leans toward the target"))
        self.assertTrue(tm.verdict({"p_target": 0.20, "p_stop": 0.30}).startswith("Leans toward the stop"))
        self.assertTrue(tm.verdict({"p_target": 0.60, "p_stop": 0.30}).startswith("Strongly toward the target"))
        self.assertEqual(tm.verdict({"p_target": 0.10, "p_stop": 0.60, "r_at_target": 1.0}),
                         "Strongly toward the stop: target first 10.0 % vs stop first 60.0 %.")
        self.assertEqual(tm.verdict({"p_target": 0.0, "p_stop": 0.0, "until": "15:15"}),
                         "No replay reached the target or the stop by 3:15 PM: the price at 3:15 PM decides every one.")

    def test_a_2r_target_is_judged_against_its_break_even(self):
        mc = {"p_target": 0.241, "p_stop": 0.505, "p_neither": 0.254, "r_at_target": 2.0, "avg_R": 0.095}
        self.assertEqual(tm.verdict(mc), "Close to break-even: at 2R the target has to come first in 33 % of the "
                                         "replays that hit one side; it did in 32 % (target first 24.1 % vs stop "
                                         "first 50.5 %).")
        self.assertEqual(tm.verdict_notes(mc), [])
        lean = dict(mc, p_target=0.15, p_stop=0.55)
        self.assertTrue(tm.verdict(lean).startswith("Leans toward the stop: at 2R the target has to come first in "
                                                    "33 % of the replays that hit one side; it did in 21 %"))
        self.assertEqual(tm.verdict_notes(lean), ["Average R is +0.095 all the same: the replays that hit neither "
                                                  "pull it the other way."])
        self.assertTrue(tm.verdict(dict(mc, p_target=0.30, p_stop=0.40)).startswith("Leans toward the target"))
        self.assertTrue(tm.verdict(dict(mc, p_target=0.40, p_stop=0.40)).startswith("Strongly toward the target"))
        self.assertIn("at 1.5R the target has to come first in 40 %", tm.verdict(dict(mc, r_at_target=1.5)))

    def test_2r_on_the_fixture_near_break_even(self):
        # stop 1380.00, 2R target 1393.80: 34.6 % vs 65.2 % looks lopsided, but 2R only needs a third
        doc = machine(plan(stop=1380.0, target=1393.8, stop_rule="pct"))
        m = doc["mc"]
        self.assertEqual((m["r_at_target"], m["p_target"], m["p_stop"], m["avg_R"]), (2.0, 0.3465, 0.6525, 0.041))
        self.assertEqual(doc["verdict"], "Close to break-even: at 2R the target has to come first in 33 % of the "
                                         "replays that hit one side; it did in 35 % (target first 34.6 % vs stop "
                                         "first 65.2 %).")
        self.assertEqual(doc["verdict_notes"], [])

    def test_2r_to_10am_a_lean_with_both_notes(self):
        # the example's entry and stop, a 2R target 1399.00, replays cut at 10:00 AM
        doc = machine(plan(target=1399.0), until="10:00")
        m = doc["mc"]
        self.assertEqual((m["r_at_target"], m["p_target"], m["p_stop"], m["p_neither"], m["avg_R"]),
                         (2.0, 0.0967, 0.3146, 0.5887, 0.079))
        self.assertEqual(doc["verdict"], "Leans toward the stop: at 2R the target has to come first in 33 % of "
                                         "the replays that hit one side; it did in 24 % (target first 9.7 % vs stop "
                                         "first 31.5 %).")
        self.assertEqual(doc["verdict_notes"], [
            "58.9 % of the replays hit neither by 10:00 AM; the price at 10:00 AM decides those.",
            "Average R is +0.079 all the same: the replays that hit neither pull it the other way."])
        text = "\n".join(tm.report(doc))
        self.assertIn(doc["verdict"] + "\n" + doc["verdict_notes"][0] + "\n" + doc["verdict_notes"][1], text)


class Network(unittest.TestCase):
    def setUp(self):
        self.calls, self.sleeps = [], []
        self._get, self._sleep = tm._get, tm._sleep
        tm._sleep = self.sleeps.append

    def tearDown(self):
        tm._get, tm._sleep = self._get, self._sleep

    def answer(self, codes):
        codes = list(codes)

        def fake(url, timeout=20):
            self.calls.append(url.split(".finance")[0].split("//")[1])
            code = codes.pop(0)
            if code != 200:
                raise urllib.error.HTTPError(url, code, "x", {}, io.BytesIO(b""))
            return TEXT
        tm._get = fake

    def test_url_and_user_agent(self):
        self.assertEqual(tm.chart_url("hcltech"),
                         "https://query2.finance.yahoo.com/v8/finance/chart/HCLTECH.NS?range=60d&interval=5m")
        self.assertIn("/chart/M%26M.NS?", tm.chart_url("m&m", "query1"))
        self.assertIn("/chart/RELIANCE.NS?", tm.chart_url("RELIANCE.NS"))
        self.assertTrue(tm.UA.startswith("Mozilla/5.0 (compatible; "))

    def test_429_waits_retries_then_falls_back_to_query1(self):
        self.answer([429, 429, 200])
        self.assertEqual(tm.fetch_chart("HCLTECH.NS"), TEXT)
        self.assertEqual(self.calls, ["query2", "query2", "query1"])
        self.assertEqual(self.sleeps, [tm.BACKOFF, tm.PAUSE])

    def test_one_429_then_ok(self):
        self.answer([429, 200])
        self.assertEqual(tm.fetch_chart("HCLTECH.NS"), TEXT)
        self.assertEqual(self.calls, ["query2", "query2"])

    def test_5xx_falls_back(self):
        self.answer([503, 200])
        self.assertEqual(tm.fetch_chart("HCLTECH.NS"), TEXT)
        self.assertEqual(self.calls, ["query2", "query1"])

    def test_rate_limited_everywhere_is_one_plain_line(self):
        self.answer([429, 429, 429, 429])
        with self.assertRaises(tm.TMError) as cm:
            tm.fetch_chart("HCLTECH.NS")
        self.assertIn("rate limiting", str(cm.exception))

    def test_404(self):
        self.answer([404])
        with self.assertRaises(tm.TMError) as cm:
            tm.fetch_chart("ZZZZ")
        self.assertIn("check the ticker", str(cm.exception))

    def test_run_over_the_network_path(self):
        self.answer([200])
        d = tempfile.mkdtemp()
        try:
            p = os.path.join(d, "plan.json")
            with open(p, "w") as fh:
                json.dump(PLAN, fh)
            code, text, _ = run(["run", "--plan", p, "--now", NOW, "--replays", "300"])
            self.assertEqual(code, 0)
            self.assertEqual(self.calls, ["query2"])
        finally:
            shutil.rmtree(d)


class Cli(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.plan = os.path.join(self.d, "trader", "plan.json")
        os.makedirs(os.path.dirname(self.plan))
        with open(self.plan, "w") as fh:
            json.dump(PLAN, fh, indent=2)
        self.out = os.path.join(self.d, "trader", "timemachine.json")

    def tearDown(self):
        shutil.rmtree(self.d)

    def test_run_with_the_plan_end_to_end(self):
        code, text, err = run(["run", "--plan", self.plan, "--offline", HCL, "--now", NOW, "--write", self.out])
        self.assertEqual(code, 0, err)
        self.assertIn("target first   50.5 %", text)
        self.assertIn("Close to a coin flip: target first 50.5 % vs stop first 49.3 %.", text)
        self.assertIn("Wrote %s." % self.out, text)
        self.assertIn("/trader-budget", text)
        with open(self.out) as fh:
            doc = json.load(fh)
        self.assertEqual(sorted(k for k in ("plan", "mc", "history") if k in doc), ["history", "mc", "plan"])
        self.assertEqual(doc["created_by"], "trader-timemachine")
        self.assertEqual(doc["source"], "offline")
        self.assertEqual((doc["mc"]["p_target"], doc["mc"]["avg_R"]), (0.5048, 0.011))
        self.assertEqual(sha(doc["mc"]["sample_paths"]), SIM_PATHS)
        self.assertEqual((doc["history"]["triggered"], doc["history"]["avg_R"]), (32, -0.216))
        self.assertEqual(doc["plan"]["from"], self.plan)

    def test_json_output(self):
        code, text, _ = run(["run", "--plan", self.plan, "--offline", HCL, "--now", NOW, "--json"])
        self.assertEqual(code, 0)
        doc = json.loads(text)
        self.assertEqual(doc["mc"]["p_stop"], 0.4932)
        self.assertNotIn("sample_paths", doc["mc"])
        self.assertEqual(doc["verdict"][:20], "Close to a coin flip")
        self.assertFalse(os.path.exists(self.out))

    def test_the_plan_as_flags_matches_the_file(self):
        code, text, err = run(["run", "--symbol", "hcltech", "--date", "2026-11-13", "--entry", "1384.60",
                               "--stop", "1377.40", "--target", "1391.80", "--entry-time", "9:35 AM",
                               "--offline", HCL, "--now", NOW, "--json"])
        self.assertEqual(code, 0, err)
        doc = json.loads(text)
        self.assertEqual((doc["mc"]["p_target"], doc["mc"]["p_green"]), (0.5048, 0.5055))
        self.assertEqual(doc["plan"]["stop_rule"], "or_mid")
        self.assertEqual((doc["history"]["target"], doc["history"]["stop"], doc["history"]["avg_R"]), (9, 13, -0.216))
        code, _, err = run(["run", "--symbol", "HCLTECH", "--entry", "1384.60", "--offline", HCL])
        self.assertEqual(code, 1)
        self.assertIn("--stop", err)

    def test_offline_folder_and_default_paths(self):
        shutil.copy(HCL, os.path.join(self.d, "HCLTECH.NS-60d5m.json.gz"))
        cwd = os.getcwd()
        os.chdir(self.d)
        try:
            code, text, err = run(["run", "--offline", ".", "--now", NOW, "--replays", "500", "--write"])
            self.assertEqual(code, 0, err)
            self.assertTrue(os.path.exists(os.path.join("trader", "timemachine.json")))
            code, text, err = run(["chart", "--from"])
            self.assertEqual(code, 0, err)
            self.assertIn("* median", text)
            with open(os.path.join("trader", "timemachine.json")) as fh:
                self.assertEqual(json.load(fh)["mc"]["replays"], 500)
        finally:
            os.chdir(cwd)

    def test_errors_are_one_plain_line(self):
        for argv in (["run", "--plan", os.path.join(self.d, "nope.json")],
                     ["run", "--plan", self.plan, "--offline", os.path.join(self.d, "missing.json.gz")],
                     ["run", "--plan", self.plan, "--offline", HCL, "--until", "9:00"],
                     ["run", "--plan", self.plan, "--offline", HCL, "--now", NOW, "--until", "15:30"],
                     ["chart", "--from", os.path.join(self.d, "nope.json")]):
            code, text, err = run(argv)
            self.assertEqual(code, 1, argv)
            self.assertEqual(len(err.strip().splitlines()), 1, err)
            self.assertTrue(err.startswith("timemachine.py: "), err)
            self.assertNotIn("Traceback", err)
        self.assertEqual(run([])[0], 1)

    def test_chart(self):
        run(["run", "--plan", self.plan, "--offline", HCL, "--now", NOW, "--write", self.out])
        code, text, _ = run(["chart", "--from", self.out])
        self.assertEqual(code, 0)
        lines = text.splitlines()
        self.assertIn("2,000 replay paths from the 9:35 AM entry (seed 19)", lines[0])
        self.assertTrue(any(l.lstrip().startswith("1391.80 |") and l.endswith("  target") for l in lines))
        self.assertTrue(any(l.lstrip().startswith("1377.40 |") and l.endswith("  stop") for l in lines))
        self.assertTrue(any(l.lstrip().startswith("1384.60 |*") and l.endswith("  entry") for l in lines))
        self.assertIn("9:35", text)
        self.assertIn("3:15", text)
        self.assertEqual(lines[-1], "Close to a coin flip: target first 50.5 % vs stop first 49.3 %.")
        code, again, _ = run(["chart", "--plan", self.plan, "--offline", HCL, "--now", NOW])
        self.assertEqual(again, text)


if __name__ == "__main__":
    unittest.main()
