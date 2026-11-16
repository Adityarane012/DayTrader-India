"""trader-exit tests. Bars for the ATR stop reuse tests/fixtures/trader-entry/
(HCLTECH.NS's real Nov 13 2026 five-minute bars, see test_entry.py)."""

import io
import json
import os
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from decimal import Decimal

from _load import load, FIX, ROOT

exitp = load("trader-exit", "exit")
entry = load("trader-entry", "entry")

HCL = os.path.join(FIX, "trader-entry", "HCLTECH-2026-11-13-5m.json")

# trader/plan.json for the worked example, exactly as the contract writes it
HCL_PLAN = {"created_by": "trader-exit", "symbol": "HCLTECH.NS", "side": "buy", "date": "2026-11-13", "setup": "orb",
            "entry": 1384.6, "entry_time": "9:35 AM", "entry_bar": 3, "interval": "5m",
            "opening_range": {"high": 1381.0, "low": 1373.8, "minutes": 15},
            "stop": 1377.4, "stop_rule": "or_mid", "stop_label": "opening-range midpoint",
            "target": 1391.8, "target_r": 1.0, "target_label": "1R (one times the risk)",
            "risk_per_share": 7.2, "reward_risk": 1.0, "flat_by": "15:15"}
HCL_ENTRY = {"created_by": "trader-entry", "symbol": "HCLTECH.NS", "setup": "orb", "side": "buy", "date": "2026-11-13",
             "status": "triggered", "time": "9:35 AM", "bar_start": "09:30", "bar_index": 3, "price": 1384.6,
             "level": 1381.0, "interval": "5m", "opening_range": {"high": 1381.0, "low": 1373.8, "minutes": 15},
             "source": "yahoo", "checked_at": "2026-11-13T04:05:00Z"}


def run(mod, argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = mod.main(argv)
    return code, out.getvalue(), err.getvalue()


def c(entry_px, stop, target="2R", oh=1381.00, ol=1373.80, atr=None, n=None, tick=None):
    sr, sp = exitp.parse_stop(stop)
    tr, tp = exitp.parse_target(target)
    return exitp.compute(entry_px, sr, sp, tr, tp, oh, ol, atr, n, tick)


class Math(unittest.TestCase):
    def test_the_example_or_mid_1r(self):
        p = c(1384.60, "or-mid", "1R")
        self.assertEqual(p["stop"], Decimal("1377.40"))          # (1381.00 + 1373.80) / 2
        self.assertEqual(p["risk"], Decimal("7.20"))
        self.assertEqual(p["target"], Decimal("1391.80"))
        self.assertEqual(p["reward_risk"], Decimal("1.00"))
        self.assertEqual(p["target_label"], "1R (one times the risk)")

    def test_the_default_2r(self):
        p = c(1384.60, "or-mid")
        self.assertEqual(p["target"], Decimal("1399.00"))
        self.assertEqual(p["target_label"], "2R (two times the risk)")

    def test_a_midpoint_off_the_tick_rounds_down(self):
        p = c(1384.60, "or-mid", oh=1381.05, ol=1373.80)            # 1377.425, tick 0.10 above 1,000
        self.assertEqual(p["stop"], Decimal("1377.40"))
        self.assertIn("rounded down to the Rs 0.10 tick", p["stop_detail"])

    def test_the_nse_tick_schedule(self):
        # circular NSE/CMTR/67133: below 250, 250 to 1,000, above 1,000 to 5,000, ...
        for price, tick in ((249.99, "0.01"), (250, "0.05"), (1000, "0.05"), (1000.05, "0.10"), (5000, "0.10"),
                            (5000.5, "0.50"), (10000, "0.50"), (10001, "1.00"), (20000, "1.00"), (20005, "5.00")):
            self.assertEqual(exitp.tick_for(price), Decimal(tick), price)
        self.assertEqual(exitp.floor_tick("1377.425", Decimal("0.10")), Decimal("1377.40"))
        self.assertEqual(exitp.floor_tick("7582.49", Decimal("0.50")), Decimal("7582.00"))

    def test_both_exits_land_on_the_tick(self):
        # ITC near 285 (tick 0.05): 1 % under is 282.15 exactly; 1.5R of 2.85 is 4.275 -> 289.275 -> 289.25
        p = c(285.00, "pct:1", "1.5R", None, None)
        self.assertEqual((p["stop"], p["risk"], p["target"], p["tick"]),
                         (Decimal("282.15"), Decimal("2.85"), Decimal("289.25"), Decimal("0.05")))
        self.assertEqual(p["notes"], ["Target Rs 289.25 is Rs 289.275 rounded down to the Rs 0.05 tick."])
        self.assertEqual(p["reward_risk"], Decimal("1.49"))
        # MARUTI near 12,854 (tick 1.00)
        p = c(12854, "pct:0.5", "1R", None, None)                   # 12789.73 -> 12789
        self.assertEqual((p["stop"], p["target"]), (Decimal("12789.00"), Decimal("12919.00")))
        # the override, for a stock whose monthly tick is the next band's
        p = c(1384.60, "price:1377.45", "1R", None, None, tick="0.05")
        self.assertEqual((p["stop"], p["target"]), (Decimal("1377.45"), Decimal("1391.75")))
        with self.assertRaises(exitp.PlanError):
            c(1384.60, "or-mid", tick="0.03")

    def test_raw_yahoo_floats_give_the_same_paise(self):
        p = c(1384.5999755859375, "or-mid", "1R", 1381.0, 1373.800048828125)
        self.assertEqual((p["entry"], p["stop"], p["target"]), (Decimal("1384.60"), Decimal("1377.40"), Decimal("1391.80")))

    def test_other_stops(self):
        p = c(1384.60, "or-low")
        self.assertEqual((p["stop"], p["risk"], p["target"]), (Decimal("1373.80"), Decimal("10.80"), Decimal("1406.20")))
        p = c(1384.60, "price:1377.409")
        self.assertEqual(p["stop"], Decimal("1377.40"))             # rounds away from the entry
        p = c(1384.60, "pct:1")
        self.assertEqual((p["stop"], p["risk"], p["target"]), (Decimal("1370.70"), Decimal("13.90"), Decimal("1412.40")))   # 1370.754 -> the 0.10 tick
        p = c(1384.60, "atr:1.5", atr=5.225006103515625, n=4)
        self.assertEqual(p["stop"], Decimal("1376.70"))             # 1384.60 - 7.8375 = 1376.7625 -> 1376.70
        self.assertEqual(p["stop_label"], "1.5 x ATR(4) under the entry")

    def test_target_rounds_down_and_price_targets(self):
        p = c(100, "price:99.01", "1.5R", None, None)
        self.assertEqual(p["target"], Decimal("101.48"))            # 100 + 1.485, down to the 0.01 tick
        self.assertEqual(p["target_label"], "1.5R (1.5 times the risk)")
        p = c(1384.60, "or-mid", "price:1394")
        self.assertEqual(p["reward_risk"], Decimal("1.31"))
        self.assertEqual(p["target_label"], "your price (1.31R)")
        self.assertEqual(p["target_r"], Decimal("1.31"))

    def test_rupee_prices_are_read(self):
        self.assertEqual(c(1384.60, "price:Rs 1377.40")["stop"], Decimal("1377.40"))
        self.assertEqual(c(1384.60, "price:rs.1,377.40")["stop"], Decimal("1377.40"))
        self.assertEqual(exitp.D("Rs 1,00,000"), Decimal("100000"))
        self.assertEqual(exitp.D("₹1,384.60"), Decimal("1384.60"))

    def test_indian_digit_grouping(self):
        self.assertEqual(exitp.money(1384.6), "Rs 1,384.60")
        self.assertEqual(exitp.money(100000), "Rs 1,00,000.00")
        self.assertEqual(exitp.money(12345678.9), "Rs 1,23,45,678.90")
        self.assertEqual(exitp.money(999), "Rs 999.00")
        self.assertEqual(exitp.money(-46.88), "-Rs 46.88")

    def test_refusals_say_why(self):
        cases = [("price:1384.60", "2R", "at or above the entry"),
                 ("price:1385", "2R", "at or above the entry"),
                 ("or-mid", "price:1384", "at or below the entry"),
                 ("price:1384.00", "2R", "too tight to survive the spread"),
                 ("pct:0.04", "2R", "too tight to survive the spread")]
        for stop, target, why in cases:
            with self.assertRaises(exitp.PlanError) as cm:
                c(1384.60, stop, target)
            self.assertIn(why, str(cm.exception), stop)
        # 0.05% of 1384.60 is 0.69: a Rs 0.70 risk is allowed, Rs 0.60 is not
        self.assertEqual(c(1384.60, "price:1383.90")["risk"], Decimal("0.70"))
        with self.assertRaises(exitp.PlanError):
            c(1384.60, "price:1384.00")
        with self.assertRaises(exitp.PlanError):
            c(1377.00, "or-mid")                                    # the midpoint is above this entry
        for bad in ("mid-ish", "pct:100", "price:0", "atr:-1"):
            with self.assertRaises(exitp.PlanError):
                exitp.parse_stop(bad)
        for bad in ("0R", "R", "lots", "price:x"):
            with self.assertRaises(exitp.PlanError):
                exitp.parse_target(bad)
        with self.assertRaises(exitp.PlanError):
            c(1384.60, "or-mid", oh=None, ol=None)
        with self.assertRaises(exitp.PlanError):
            c(1384.60, "or-mid", oh=1373.80, ol=1381.00)

    def test_atr_on_the_session_bars(self):
        ch = exitp.load_chart("HCLTECH", "5m", None, HCL)
        day = exitp.datetime.date(2026, 11, 13)
        bars = exitp.session_bars(ch, day, "5m", upto_slot=3)
        self.assertEqual(len(bars), 4)                              # 9:15 ... the 9:30 entry bar
        # by hand: the true range of each bar, the first one without the overnight gap
        trs, prev = [], None
        for b in bars:
            r = b["h"] - b["l"]
            if prev is not None:
                r = max(r, abs(b["h"] - prev), abs(b["l"] - prev))
            trs.append(r)
            prev = b["c"]
        self.assertAlmostEqual(trs[0], 1381.00 - 1375.00, places=4)
        atr, n = exitp.atr_of(bars)
        self.assertEqual(n, 4)
        self.assertAlmostEqual(atr, sum(trs) / 4, places=9)
        self.assertAlmostEqual(atr, 5.2250, places=4)               # (6.00 + 4.60 + 3.50 + 6.80) / 4
        # later in the day it uses the last 14 bars; the file's in-progress 10:45 bar and tick never count
        all_bars = exitp.session_bars(ch, day, "5m")
        self.assertEqual(len(all_bars), 18)
        self.assertEqual(exitp.atr_of(all_bars)[1], 14)

    def test_symbols(self):
        self.assertEqual(exitp.yahoo_symbol("hcltech"), "HCLTECH.NS")
        self.assertEqual(exitp.url_symbol("M&M"), "M%26M.NS")
        self.assertEqual(exitp.url_symbol("RELIANCE.NS"), "RELIANCE.NS")


class Cli(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.cwd = os.getcwd()
        os.chdir(self.d)
        os.mkdir("trader")

    def tearDown(self):
        os.chdir(self.cwd)
        shutil.rmtree(self.d)

    def write(self, path, doc):
        with open(path, "w") as fh:
            json.dump(doc, fh)

    def plan(self, *args):
        return run(exitp, ["plan", "--now", "2026-11-13 09:36"] + list(args))

    def read_plan(self):
        with open(os.path.join("trader", "plan.json")) as fh:
            return json.load(fh)

    def test_entry_to_plan_end_to_end(self):
        code, _, _ = run(entry, ["check", "HCLTECH", "--offline", HCL, "--now", "2026-11-13 09:35", "--write"])
        self.assertEqual(code, 0)
        code, text, err = self.plan("--stop", "or-mid", "--target", "1R", "--write")
        self.assertEqual(code, 0, err)
        p = self.read_plan()
        for k, v in HCL_PLAN.items():
            self.assertEqual(p[k], v, k)
        self.assertIn("Stop          Rs 1,377.40  opening-range midpoint", text)
        self.assertIn("Target        Rs 1,391.80  1R (one times the risk)", text)
        self.assertIn("Risk a share  Rs 7.20 (0.52% of the entry)", text)
        self.assertIn("Reward:risk   1.0", text)
        self.assertIn("Flat by       15:15 IST", text)
        self.assertIn("not a guarantee", text)
        self.assertIn("/trader-timemachine", text)
        self.assertNotIn("pro" + "fit", text.lower())   # never on screen
        code, text, _ = self.plan("--write")                       # the defaults: or-mid, 2R
        self.assertEqual(self.read_plan()["target"], 1399.0)
        self.assertEqual(self.read_plan()["target_r"], 2.0)
        code, text, _ = run(exitp, ["show", "--now", "2026-11-13 09:40"])
        self.assertEqual(code, 0)
        self.assertIn("Rs 1,399.00", text)
        self.assertNotIn("not today", text)
        code, text, _ = run(exitp, ["show", "--now", "2026-11-16 09:40"])
        self.assertIn("not today", text)

    def test_manual_flags_and_json(self):
        code, text, _ = self.plan("--symbol", "hcltech", "--entry", "1384.60", "--or-high", "1381.00",
                                  "--or-low", "1373.80", "--time", "9:35", "--entry-bar", "3",
                                  "--date", "2026-11-13", "--target", "1R", "--json")
        self.assertEqual(code, 0)
        p = json.loads(text)
        for k, v in HCL_PLAN.items():
            self.assertEqual(p[k], v, k)
        # no trader/sec_list.csv here: the only note is "band unknown", once
        self.assertEqual(len(p["warnings"]), 1)
        self.assertTrue(p["warnings"][0].startswith("Band unknown for HCLTECH"))

    def test_atr_stop_reads_bars(self):
        self.write(os.path.join("trader", "entry.json"), HCL_ENTRY)
        code, text, err = self.plan("--stop", "atr:1.5", "--offline", HCL, "--json")
        self.assertEqual(code, 0, err)
        p = json.loads(text)
        self.assertEqual((p["stop"], p["risk_per_share"], p["target"]), (1376.7, 7.9, 1400.4))
        self.assertEqual(p["tick"], 0.1)
        self.assertEqual((p["stop_rule"], p["atr_bars"]), ("atr", 4))
        self.assertAlmostEqual(p["atr"], 5.225, places=4)
        code, _, err = self.plan("--stop", "atr:1.5", "--offline", HCL, "--entry-bar", "1")
        self.assertEqual(code, 1)
        self.assertIn("at least 3 closed", err)

    def test_refusals_from_the_cli(self):
        self.write(os.path.join("trader", "entry.json"), dict(HCL_ENTRY, status="waiting", time=None, price=None,
                                                              bar_index=None, bar_start=None))
        code, _, err = self.plan()
        self.assertEqual(code, 1)
        self.assertIn("HCLTECH.NS is waiting, not triggered", err)
        code, text, _ = self.plan("--entry", "1381.05", "--json")    # plan ahead at the level
        self.assertEqual(code, 0)
        p = json.loads(text)
        self.assertEqual((p["entry"], p["stop"], p["entry_time"]), (1381.05, 1377.4, None))

        self.write(os.path.join("trader", "entry.json"), dict(HCL_ENTRY, setup="level", level=1381.0))
        code, _, err = self.plan()
        self.assertIn("level setup has no opening-range stop", err)
        self.assertEqual(self.plan("--stop", "pct:1")[0], 0)

        code, _, err = self.plan("--side", "sell")
        self.assertIn("This pack plans longs only", err)
        self.write(os.path.join("trader", "entry.json"), dict(HCL_ENTRY, side="sell"))
        code, _, err = self.plan()
        self.assertIn("longs only", err)
        code, _, err = self.plan("--stop", "price:1384.50")
        self.assertIn("longs only", err)
        os.remove(os.path.join("trader", "entry.json"))
        code, _, err = self.plan()
        self.assertIn("no entry", err)
        code, _, err = self.plan("--symbol", "HCLTECH")
        self.assertIn("needs --entry", err)
        code, _, err = self.plan("--symbol", "HCLTECH", "--from", "x.json", "--entry", "1")
        self.assertIn("not both", err)
        code, _, err = self.plan("--symbol", "HCLTECH", "--entry", "1384.60", "--or-high", "1381.00")
        self.assertIn("both --or-high and --or-low", err)
        self.assertNotIn("Traceback", err)

    def test_flat_by_config_and_late_entries(self):
        self.write(os.path.join("trader", "entry.json"), HCL_ENTRY)
        self.write(os.path.join("trader", "config.json"), {"flat_by": "15:10", "min_reward_risk": 1.5})
        code, text, _ = self.plan("--target", "1R", "--json")
        p = json.loads(text)
        self.assertEqual(p["flat_by"], "15:10")
        self.assertTrue(any("under your min_reward_risk 1.5" in w for w in p["warnings"]))
        self.write(os.path.join("trader", "config.json"), {"flat_by": "15:30"})
        code, _, err = self.plan()
        self.assertEqual(code, 1)
        self.assertIn("flat_by 15:30 in the config is at or after the 3:30 PM close", err)
        os.remove(os.path.join("trader", "config.json"))

        # Christmas Eve is a full NSE day: flat by 15:15 as usual, no early close
        self.write(os.path.join("trader", "entry.json"), dict(HCL_ENTRY, date="2026-12-24"))
        code, text, _ = run(exitp, ["plan", "--now", "2026-12-24 09:36"])
        self.assertEqual(code, 0)
        self.assertIn("Flat by       15:15 IST", text)
        self.assertNotIn("early close", text)

        self.write(os.path.join("trader", "entry.json"), HCL_ENTRY)
        code, _, err = self.plan("--flat-by", "15:45")
        self.assertIn("after the 3:30 PM close", err)
        self.write(os.path.join("trader", "entry.json"), dict(HCL_ENTRY, time="3:16 PM"))
        code, _, err = self.plan()
        self.assertEqual(code, 1)
        self.assertIn("no time left to hold it", err)

    def test_show_without_a_plan(self):
        code, text, _ = run(exitp, ["show"])
        self.assertEqual(code, 1)
        self.assertIn("No plan", text)


class SkillDoc(unittest.TestCase):
    def test_skill_md(self):
        with open(os.path.join(ROOT, "trader-exit", "SKILL.md"), encoding="utf-8") as fh:
            text = fh.read()
        with open(os.path.join(ROOT, "trader-risk", "SKILL.md"), encoding="utf-8") as fh:
            risk = fh.read()
        self.assertTrue(text.startswith("---\nname: trader-exit\n"))
        self.assertGreater(len(text.splitlines()), 60)
        self.assertEqual(text[text.index("## Safety"):], risk[risk.index("## Safety"):])
        low = " ".join(text.lower().split())
        for must in ("before the entry", "a stop is a plan, not a guarantee", "day trading loses most people money",
                     "/trader-timemachine", "/trader-budget", "longs only", "rs 1,377.40", "rs 1,391.80",
                     "rs 7.20", "1,399.00", "too tight to survive the spread", "15:15", "auto square-off"):
            self.assertIn(must, low)
        for never in (chr(0x2014), "tick " + "by tick", "real " + "time", "pro" + "fit", "new york", "nyse"):
            self.assertNotIn(never, low)


if __name__ == "__main__":
    unittest.main()
