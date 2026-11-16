"""trader-exit price-band tests: the sec_list.csv parser and the band warning.

The fixture tests/fixtures/trader-exit/sec_list_sample.csv is a HAND-MADE
sample (written 2026-11-16), not a download of NSE's file: ALPHA, BRAVO (20 %)
and DELTA (10 %) are made-up symbols, RELIANCE and ETERNAL stand for stocks with
no band, the names and every other row are invented, and the malformed
rows are there on purpose. Whether NSE's real sec_list.csv has exactly these
columns is unverified. The same file is the shared fixture for the separate
screener MCP's tests; docs/sec_list_format.md is the contract both follow.
The previous closes below are made up too."""

import calendar
import datetime
import os
import shutil
import tempfile
import unittest
from decimal import Decimal

from _load import load, FIX
from test_exit import run

exitp = load("trader-exit", "exit")

SAMPLE = os.path.join(FIX, "trader-exit", "sec_list_sample.csv")
NO_CONFIG = os.path.join(FIX, "trader-exit", "no-such-config.json")


def records():
    with open(SAMPLE, encoding="utf-8-sig") as fh:
        return exitp.parse_sec_list(fh.read())


def by_line(recs):
    return {r["line"]: r for r in recs}


class Parser(unittest.TestCase):
    def setUp(self):
        self.recs = records()
        self.skipped = []
        with open(SAMPLE, "rb") as fh:       # raw bytes: the BOM is still there
            exitp.parse_sec_list(fh.read().decode("utf-8"), self.skipped)

    def get(self, symbol, series="EQ"):
        return [r for r in self.recs if r["symbol"] == symbol and r["series"] == series]

    def test_percent_bands(self):
        for sym, pct in (("ALPHA", 20.0), ("BRAVO", 20.0), ("DELTA", 10.0), ("SAMPLE5", 5.0), ("SAMPLE2", 2.0)):
            (r,) = self.get(sym)
            self.assertEqual((r["band"], r["band_pct"], r["reason"]), ("percent", pct, None), sym)
        self.assertEqual(self.get("ALPHA")[0]["name"], "ALPHA SAMPLE NAME")

    def test_no_band_and_blank_mean_no_band(self):
        for sym in ("RELIANCE", "ETERNAL"):
            (r,) = self.get(sym)
            self.assertEqual((r["band"], r["band_pct"], r["reason"]), ("none", None, None), sym)

    def test_bom_header_and_blank_lines_are_skipped(self):
        self.assertEqual(self.recs[0]["symbol"], "ALPHA")
        self.assertEqual(self.recs[0]["line"], 2)
        self.assertNotIn("SYMBOL", [r["symbol"] for r in self.recs])       # the repeated header

    def test_padding_case_and_percent_sign(self):
        (r,) = self.get("PADDED")
        self.assertEqual((r["series"], r["name"], r["band"], r["band_pct"]), ("EQ", "PADDED CO", "percent", 20.0))

    def test_malformed_bands_are_unknown_with_a_reason_and_no_crash(self):
        (bad,) = self.get("BADBAND")
        self.assertEqual((bad["band"], bad["band_pct"]), ("unknown", None))
        self.assertIn("'abc'", bad["reason"])
        (zero,) = self.get("ZEROBAND")
        self.assertEqual((zero["band"], zero["band_pct"]), ("unknown", None))
        (short,) = self.get("SHORTROW")
        self.assertEqual((short["band"], short["reason"]), ("unknown", "row has no Band column"))

    def test_a_row_with_no_symbol_is_skipped_and_noted(self):
        self.assertEqual(self.skipped, ["line 15: no symbol"])
        self.assertFalse([r for r in self.recs if r["symbol"] == ""])

    def test_duplicates_are_kept_and_the_last_eq_row_wins(self):
        dupes = self.get("DUPE")
        self.assertEqual([r["band_pct"] for r in dupes], [5.0, 10.0])
        self.assertEqual(exitp.band_for(self.recs, "DUPE")["band_pct"], 10.0)

    def test_only_the_eq_series_counts(self):
        self.assertEqual(len(self.get("BEONLY", "BE")), 1)
        self.assertIsNone(exitp.band_for(self.recs, "BEONLY"))
        self.assertIsNone(exitp.band_for(self.recs, "NOSUCH"))
        self.assertEqual(exitp.band_for(self.recs, "ALPHA.NS")["band_pct"], 20.0)

    def test_columns_are_found_by_name_not_position(self):
        recs = exitp.parse_sec_list("Band,Remarks,Symbol,Series\n5,x,abc,EQ\n")
        self.assertEqual((recs[0]["symbol"], recs[0]["series"], recs[0]["band_pct"]), ("ABC", "EQ", 5.0))

    def test_empty_input(self):
        self.assertEqual(exitp.parse_sec_list(""), [])
        self.assertEqual(exitp.parse_sec_list(None), [])


class Limits(unittest.TestCase):
    def test_limits_from_the_previous_close(self):
        self.assertEqual(exitp.band_limits(200, 20, Decimal("0.01")), (Decimal("160.00"), Decimal("240.00")))
        self.assertEqual(exitp.band_limits(500, 10, Decimal("0.05")), (Decimal("450.00"), Decimal("550.00")))

    def test_rounding_stays_inside_the_band(self):
        # 333.33 x 1.2 = 399.996 -> down to 399.95; x 0.8 = 266.664 -> up to 266.70
        self.assertEqual(exitp.band_limits(333.33, 20, Decimal("0.05")), (Decimal("266.70"), Decimal("399.95")))


class Warning(unittest.TestCase):
    def setUp(self):
        self.recs = records()

    def warn(self, sym, prev, stop, target, tick="0.05", pct=1):
        return exitp.band_warnings(sym, prev, exitp.band_for(self.recs, sym), stop, target, Decimal(tick), pct)

    def test_alpha_target_near_the_upper_limit(self):
        w = self.warn("ALPHA.NS", 200, 190, 238, tick="0.01")
        self.assertEqual(w, ["ALPHA has a 20% price band today: Rs 160.00 to Rs 240.00 from the previous close of "
                             "Rs 200.00. The target Rs 238.00 is within 1% of the upper limit Rs 240.00 (Rs 2.00 away): "
                             "at the limit trading can stop and the order may not fill."])

    def test_bravo_stop_near_the_lower_limit(self):
        w = self.warn("BRAVO", 100, 80.5, 110, tick="0.01")
        self.assertEqual(w, ["BRAVO has a 20% price band today: Rs 80.00 to Rs 120.00 from the previous close of "
                             "Rs 100.00. The stop Rs 80.50 is within 1% of the lower limit Rs 80.00 (Rs 0.50 away): "
                             "at the limit trading can stop and a stop order may not fill."])

    def test_delta_target_beyond_the_limit_and_a_threshold_from_the_config(self):
        w = self.warn("DELTA", 500, 480, 560)
        self.assertEqual(len(w), 1)
        self.assertIn("DELTA has a 10% price band today: Rs 450.00 to Rs 550.00", w[0])
        self.assertIn("The target Rs 560.00 is above the upper limit Rs 550.00: it cannot be reached today.", w[0])
        self.assertEqual(self.warn("DELTA", 500, 480, 540), [])                  # 10 away, 1% = 5
        self.assertIn("within 3%", self.warn("DELTA", 500, 480, 540, pct=3)[0])   # 3% = 15

    def test_both_exits_near_the_limits(self):
        w = self.warn("DELTA", 500, 452, 548)
        self.assertEqual(len(w), 2)
        self.assertIn("The stop Rs 452.00 is within 1% of the lower limit", w[0])
        self.assertTrue(w[1].startswith("The target Rs 548.00 is within 1% of the upper limit"))

    def test_no_band_stock(self):
        self.assertEqual(self.warn("RELIANCE", 1300, 1280, 1340), ["RELIANCE has no price band: no band check."])

    def test_band_unknown_cases(self):
        self.assertEqual(self.warn("NOSUCH", 100, 90, 110),
                         ["Band unknown for NOSUCH: it is not in the security list (EQ series), so no band check."])
        w = self.warn("BADBAND", 100, 90, 110)
        self.assertEqual(len(w), 1)
        self.assertTrue(w[0].startswith("Band unknown for BADBAND: the security list is unclear ("))
        self.assertEqual(self.warn("ALPHA", None, 90, 110),
                         ["Band unknown for ALPHA: no previous close (pass --prev-close), so no band check."])


class Cli(unittest.TestCase):
    ARGS = ["plan", "--symbol", "ALPHA", "--entry", "220", "--setup", "level", "--stop", "price:190",
            "--target", "price:238", "--date", "2026-11-16", "--now", "2026-11-16 09:40",
            "--config", NO_CONFIG]

    def setUp(self):
        # the once-a-day band notes are written under trader/state in the working folder: use a scratch one
        self.cwd = os.getcwd()
        self.d = tempfile.mkdtemp(prefix="dti-band-cwd-")
        os.chdir(self.d)

    def tearDown(self):
        os.chdir(self.cwd)
        shutil.rmtree(self.d, ignore_errors=True)

    def test_the_plan_prints_the_band_note_and_still_succeeds(self):
        code, out, _ = run(exitp, self.ARGS + ["--band-file", SAMPLE, "--prev-close", "200"])
        self.assertEqual(code, 0)
        self.assertIn("Note: ALPHA has a 20% price band today: Rs 160.00 to Rs 240.00", out)
        self.assertIn("The target Rs 238.00 is within 1% of the upper limit Rs 240.00", out)
        self.assertIn("Nothing was placed.", out)

    def test_no_band_file_says_band_unknown_once(self):
        code, out, _ = run(exitp, self.ARGS + ["--band-file", os.path.join(FIX, "trader-exit", "missing.csv")])
        self.assertEqual(code, 0)
        self.assertEqual(out.count("Band unknown"), 1)
        self.assertIn("no security list at", out)

    def test_no_previous_close_says_band_unknown_once(self):
        code, out, _ = run(exitp, self.ARGS + ["--band-file", SAMPLE])
        self.assertEqual(code, 0)
        self.assertEqual(out.count("Band unknown"), 1)
        self.assertIn("no previous close", out)

    def test_config_threshold_is_read_and_a_config_without_it_still_works(self):
        import json
        import shutil
        import tempfile
        d = tempfile.mkdtemp(prefix="dti-band-")
        try:
            cfg = os.path.join(d, "config.json")
            args = [x for x in self.ARGS[:-1]] + [cfg, "--band-file", SAMPLE, "--prev-close", "200",
                                                  "--target", "price:230"]
            with open(cfg, "w", encoding="utf-8") as fh:
                json.dump({"flat_by": "15:15"}, fh)                      # no band_warn_pct: default 1
            _, out, _ = run(exitp, args)
            self.assertNotIn("The target", out)                           # 10 away, 1% = 2
            with open(cfg, "w", encoding="utf-8") as fh:
                json.dump({"band_warn_pct": 5}, fh)                       # 5% = 10
            _, out, _ = run(exitp, args)
            self.assertIn("The target Rs 230.00 is within 5% of the upper limit Rs 240.00", out)
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_prev_close_can_come_from_entry_json(self):
        import json
        import shutil
        import tempfile
        d = tempfile.mkdtemp(prefix="dti-band-")
        try:
            ent = os.path.join(d, "entry.json")
            with open(ent, "w", encoding="utf-8") as fh:
                json.dump({"symbol": "ALPHA.NS", "status": "triggered", "price": 220, "setup": "level",
                           "date": "2026-11-16", "prev_close": 200}, fh)
            args = ["plan", "--from", ent, "--stop", "price:190", "--target", "price:238", "--now",
                    "2026-11-16 09:40", "--config", NO_CONFIG, "--band-file", SAMPLE]
            _, out, _ = run(exitp, args)
            self.assertIn("within 1% of the upper limit Rs 240.00", out)
        finally:
            shutil.rmtree(d, ignore_errors=True)


def save_list(path, ist_text, content=None):
    """A copy of the sample list (or `content`) at `path`, saved at an India time like '2026-11-16 08:00'."""
    if content is None:
        shutil.copyfile(SAMPLE, path)
    else:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content)
    utc = datetime.datetime.strptime(ist_text, "%Y-%m-%d %H:%M") - datetime.timedelta(hours=5, minutes=30)
    ts = calendar.timegm(utc.timetuple())
    os.utime(path, (ts, ts))


class Notices(unittest.TestCase):
    """The missing-list and old-list notes show once an India day; a duplicate EQ row is flagged."""
    BASE = ["plan", "--symbol", "ALPHA", "--entry", "220", "--setup", "level", "--stop", "price:190",
            "--target", "price:238", "--prev-close", "200", "--config", NO_CONFIG]

    def setUp(self):
        self.cwd = os.getcwd()
        self.d = tempfile.mkdtemp(prefix="dti-notice-")
        os.chdir(self.d)                      # trader/state lands here, never in the real folder
        self.band = os.path.join(self.d, "sec_list.csv")

    def tearDown(self):
        os.chdir(self.cwd)
        shutil.rmtree(self.d, ignore_errors=True)

    def plan(self, day="2026-11-16", now="09:40", extra=()):
        return run(exitp, self.BASE + ["--date", day, "--now", "%s %s" % (day, now), "--band-file", self.band]
                   + list(extra))[1]

    def test_missing_list_notes_once_a_day_then_again_the_next_day(self):
        first = self.plan()
        self.assertEqual(first.count("Band unknown"), 1)
        self.assertIn("no security list at", first)
        self.assertIn("shows once a day", first)
        second = self.plan(now="10:05")                           # same India day, another plan
        self.assertNotIn("Band unknown", second)
        self.assertNotIn("no security list", second)
        self.assertIn("Nothing was placed.", second)              # the plan itself is unaffected
        nxt = self.plan(day="2026-11-17")                         # a new day: the note comes back
        self.assertEqual(nxt.count("Band unknown"), 1)

    def test_missing_note_is_per_file_path(self):
        self.assertIn("no security list at", self.plan())
        other = os.path.join(self.d, "other.csv")
        out = run(exitp, self.BASE + ["--date", "2026-11-16", "--now", "2026-11-16 09:41", "--band-file", other])[1]
        self.assertIn("no security list at", out)

    def test_old_list_warns_once_and_the_band_check_still_runs(self):
        save_list(self.band, "2026-11-10 08:00")                  # a Tuesday holiday; latest trading day is the 16th
        first = self.plan()
        self.assertIn("was saved on 2026-11-10, before the latest trading day 2026-11-16", first)
        self.assertIn("ALPHA has a 20% price band today", first)  # not blocked by the old-file note
        second = self.plan(now="10:05")
        self.assertNotIn("was saved on", second)
        self.assertIn("ALPHA has a 20% price band today", second)

    def test_a_list_saved_on_the_latest_trading_day_is_fresh(self):
        save_list(self.band, "2026-11-16 03:00")
        self.assertNotIn("was saved on", self.plan())

    def test_weekend_uses_the_friday_session_as_the_latest_day(self):
        save_list(self.band, "2026-11-13 20:00")                  # Friday evening
        out = run(exitp, self.BASE + ["--date", "2026-11-13", "--now", "2026-11-15 10:00",
                                      "--band-file", self.band])[1]   # a Sunday
        self.assertNotIn("was saved on", out)
        save_list(self.band, "2026-11-12 20:00")                  # Thursday: older than Friday
        out = run(exitp, self.BASE + ["--date", "2026-11-13", "--now", "2026-11-15 10:00",
                                      "--band-file", self.band, "--state-dir", os.path.join(self.d, "s2")])[1]
        self.assertIn("was saved on 2026-11-12, before the latest trading day 2026-11-13", out)

    def test_unwritable_state_folder_notifies_every_time_not_never(self):
        blocker = os.path.join(self.d, "blocker")
        with open(blocker, "w", encoding="utf-8") as fh:
            fh.write("a file where the state folder should go")
        args = ["--state-dir", os.path.join(blocker, "state")]
        self.assertIn("no security list at", self.plan(extra=args))
        self.assertIn("no security list at", self.plan(extra=args))

    def test_duplicate_eq_row_is_reported_by_the_parser(self):
        dups = []
        text = ("Symbol,Series,Security Name,Band\nALPHA,EQ,Alpha,20\nBRAVO,EQ,Bravo,20\nALPHA,BE,Alpha,5\n"
                "ALPHA,EQ,Alpha,10\nALPHA,EQ,Alpha,5\n")
        recs = exitp.parse_sec_list(text, duplicates=dups)
        self.assertEqual(len(recs), 5)                            # every row is still kept
        self.assertEqual([s for s, _ in dups], ["ALPHA", "ALPHA"])
        self.assertIn("line 5: ALPHA is in the EQ series again (first at line 2): the last row wins", dups[0][1])
        self.assertIn("line 6:", dups[1][1])
        self.assertEqual(exitp.band_for(recs, "ALPHA")["band_pct"], 5.0)   # the last EQ row still wins
        clean = []
        exitp.parse_sec_list("Symbol,Series,Security Name,Band\nALPHA,EQ,G,20\nALPHA,BE,G,5\n", duplicates=clean)
        self.assertEqual(clean, [])                               # a BE row is not an EQ duplicate

    def test_duplicate_shows_in_the_plan_only_for_that_symbol(self):
        save_list(self.band, "2026-11-16 03:00",
                  "Symbol,Series,Security Name,Band\nALPHA,EQ,Alpha,20\nALPHA,EQ,Alpha,10\nBRAVO,EQ,Bravo,20\n"
                  "BRAVO,EQ,Bravo,20\n")
        out = self.plan()
        self.assertIn("Security list: line 3: ALPHA is in the EQ series again (first at line 2): the last row wins.", out)
        self.assertIn("ALPHA has a 10% price band today", out)     # the last row (10) is the one used
        other = run(exitp, ["plan", "--symbol", "ETERNAL", "--entry", "220", "--setup", "level", "--stop",
                            "price:190", "--target", "price:238", "--prev-close", "200", "--config", NO_CONFIG,
                            "--date", "2026-11-16", "--now", "2026-11-16 09:40", "--band-file", self.band])[1]
        self.assertNotIn("again", other)                          # BRAVO's duplicate is not ETERNAL's business


if __name__ == "__main__":
    unittest.main()
