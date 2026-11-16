"""trader-scanner tests. Fixtures in tests/fixtures/trader-scanner/, all real:

daily-spark-nifty50-2026-11-14.json  Yahoo spark answers (3mo, 1d) for the Nifty 50, three
                                     requests of up to 20 merged into one answer, fetched
                                     Sat Nov 14 2026: closes through Fri Nov 13.
wall5m-2026-11-13.json.gz            the Nifty 50's v8 5-minute charts for Fri Nov 13 2026,
                                     one bundle {"SYMBOL.NS": <v8 json>}, cut from 60-day
                                     answers fetched Nov 14.
spark-5m-2026-11-14.json             a real 20-symbol spark answer (1d, 5m) fetched Nov 14:
                                     Nov 13's bars, without the 15:15 and 15:20 bars (Yahoo's
                                     NSE gap).
ind_nifty50list.csv                  niftyindices.com's Nifty 50 list, as shipped in
                                     trader-scanner/universes/.

The daily setups and the opening-range breakouts are checked against a second, minimal
implementation of the same rules written here (IndependentChecks), not only pinned.
"""

import datetime
import gzip
import io
import json
import math
import os
import shutil
import tempfile
import unittest
import urllib.error
from contextlib import redirect_stdout, redirect_stderr

from _load import load, FIX, ROOT

scan = load("trader-scanner", "scan")

SDIR = os.path.join(FIX, "trader-scanner")
WALL = os.path.join(SDIR, "wall5m-2026-11-13.json.gz")
DAILY = os.path.join(SDIR, "daily-spark-nifty50-2026-11-14.json")
SPARK5 = os.path.join(SDIR, "spark-5m-2026-11-14.json")
SHIPPED = os.path.join(ROOT, "trader-scanner", "universes")
DT = datetime.datetime
D = datetime.date
DAY = D(2026, 11, 13)
ORB_0935 = ["BAJFINANCE.NS", "BHARTIARTL.NS", "BSE.NS", "COALINDIA.NS", "DRREDDY.NS", "EICHERMOT.NS", "HCLTECH.NS",
            "HINDUNILVR.NS", "INDIGO.NS", "INFY.NS", "JSWSTEEL.NS", "TATASTEEL.NS", "TECHM.NS"]


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = scan.main(argv)
    return code, out.getvalue(), err.getvalue()


def ts(ist_text):
    """India wall-clock text -> unix seconds."""
    utc = scan.ist_to_utc(DT.strptime(ist_text, "%Y-%m-%d %H:%M:%S" if ist_text.count(":") == 2
                                      else "%Y-%m-%d %H:%M"))
    return int((utc - DT(1970, 1, 1)).total_seconds())


def bars_series(day, closes, highs=None, lows=None, start="09:15"):
    """A v8-like series of 5-min bars from `start` on `day` (YYYY-MM-DD)."""
    t0 = DT.strptime(day + " " + start, "%Y-%m-%d %H:%M")
    t = [ts((t0 + datetime.timedelta(minutes=5 * i)).strftime("%Y-%m-%d %H:%M")) for i in range(len(closes))]
    return {"t": t, "c": list(closes), "h": list(highs or [c + 0.1 if c is not None else None for c in closes]),
            "l": list(lows or [c - 0.1 if c is not None else None for c in closes]), "o": None,
            "v": [1000] * len(closes), "meta": {}}


class Universe(unittest.TestCase):
    def test_the_shipped_lists(self):
        counts = {}
        for name, (fname, _) in scan.INDEXES.items():
            with open(os.path.join(SHIPPED, fname), encoding="utf-8") as fh:
                counts[name] = len(scan.parse_index_csv(fh.read(), name))
        self.assertEqual(counts, {"nifty50": 50, "banknifty": 14, "niftynext50": 50, "nifty200": 200})

    def test_the_nifty_50(self):
        kept, per, notes = scan.build_universe(["nifty50"])
        self.assertEqual((len(kept), notes), (50, []))
        syms = dict(kept)
        self.assertEqual(syms["RELIANCE.NS"], "Reliance Industries Ltd.")
        self.assertIn("M&M.NS", syms)
        self.assertIn("BAJAJ-AUTO.NS", syms)                     # the dash stays (upstream made it a dot)
        self.assertEqual(per, [("nifty50", 50, "shipped list of 2026-11-14")])
        # the video's own Nifty 50 list is the same 50
        video = ("ADANIENT ADANIPORTS APOLLOHOSP ASIANPAINT AXISBANK BAJAJ-AUTO BAJAJFINSV BAJFINANCE BEL BHARTIARTL "
                 "BSE CIPLA COALINDIA DRREDDY EICHERMOT ETERNAL GRASIM HCLTECH HDFCBANK HDFCLIFE HINDALCO HINDUNILVR "
                 "ICICIBANK INDIGO INFY ITC JIOFIN JSWSTEEL KOTAKBANK LT M&M MARUTI MAXHEALTH NESTLEIND NTPC ONGC "
                 "POWERGRID RELIANCE SBILIFE SBIN SHRIRAMFIN SUNPHARMA TATACONSUM TATASTEEL TCS TECHM TITAN TMPV "
                 "TRENT ULTRACEMCO").split()
        self.assertEqual(sorted(syms), sorted(s + ".NS" for s in video))

    def test_several_indexes_each_stock_once(self):
        kept, per, _ = scan.build_universe(["nifty50", "banknifty"])
        self.assertEqual([(n, c) for n, c, _ in per], [("nifty50", 50), ("banknifty", 14)])
        self.assertEqual(len(kept), 59)                          # 5 banks are in both
        self.assertEqual(len(set(s for s, _ in kept)), 59)
        kept200, _, _ = scan.build_universe(["nifty50", "niftynext50", "nifty200"])
        self.assertEqual(len(kept200), 200)                      # the 200 holds the 50 and the Next 50

    def test_refresh_falls_back_to_the_shipped_list(self):
        saved = scan.http_get

        def refused(url, timeout=20):
            raise urllib.error.HTTPError(url, 403, "Forbidden", {}, io.BytesIO(b""))
        scan.http_get = refused
        try:
            kept, per, notes = scan.build_universe(["banknifty"], refresh=True)
        finally:
            scan.http_get = saved
        self.assertEqual(len(kept), 14)
        self.assertEqual(notes, ["niftyindices.com did not give the Nifty Bank list (HTTP 403): using the "
                                 "shipped list of 2026-11-14"])

    def test_offline_folder_and_bad_files(self):
        kept, per, _ = scan.build_universe(["nifty50"], offline=SDIR)
        self.assertEqual(len(kept), 50)
        self.assertIn(os.path.join(SDIR, "ind_nifty50list.csv"), per[0][2])
        with self.assertRaises(scan.ScanError):
            scan.parse_index_csv("<html>maintenance</html>")
        with self.assertRaises(scan.ScanError) as cm:
            scan.build_universe(["sensex"])
        self.assertIn("unknown index", str(cm.exception))
        rows = scan.parse_index_csv("Company Name,Industry,Symbol,Series,ISIN Code\nA Ltd.,X,AAA,EQ,IN1\n"
                                    "B Ltd.,X,BBB,BE,IN2\n")
        self.assertEqual(rows, [("AAA.NS", "A Ltd.")])          # series EQ only


class Time(unittest.TestCase):
    def test_ist_and_the_clock(self):
        self.assertEqual(scan.ts_to_ist(1794541500), DT(2026, 11, 13, 9, 15))   # the first NSE bar of Nov 13
        self.assertEqual(scan.parse_now("2026-11-13 09:35"), DT(2026, 11, 13, 4, 5))
        self.assertEqual(scan.parse_now("2026-07-01 09:35"), DT(2026, 7, 1, 4, 5))   # no DST
        self.assertEqual(scan.parse_now("2026-11-13T04:05:00Z"), DT(2026, 11, 13, 4, 5))
        self.assertEqual(scan.clock_label(DT(2026, 11, 13, 9, 35)), "9:35 AM")
        self.assertEqual(scan.clock_label(datetime.time(15, 0)), "3:00 PM")
        self.assertEqual(scan.session(DAY), (datetime.time(9, 15), datetime.time(15, 30)))
        self.assertIsNone(scan.session(D(2026, 11, 10)))                           # Diwali-Balipratipada
        with self.assertRaises(scan.ScanError):
            scan.parse_now("tomorrow")
        with self.assertRaises(scan.ScanError):
            scan.parse_hhmm("25:00")


class Spark(unittest.TestCase):
    def test_a_real_daily_spark_answer(self):
        data, errors = scan.load_offline(DAILY)
        self.assertEqual((len(data), errors), (50, {}))
        t = data["HCLTECH.NS"]
        self.assertEqual(len(t["t"]), 63)
        self.assertIsNone(t["h"])                                # spark is closes only
        self.assertEqual(t["c"][-1], 1378.0)
        self.assertEqual(t["meta"]["regularMarketVolume"], 2089627)
        self.assertIn("M&M.NS", data)
        self.assertIn("BAJAJ-AUTO.NS", data)
        # read before the close on Friday: Friday's bar is still in progress
        self.assertEqual(scan.daily_closes(t, scan.parse_now("2026-11-13 15:29"))[-1], (D(2026, 11, 12), 1380.8))
        self.assertEqual(scan.daily_closes(t, scan.parse_now("2026-11-13 15:30"))[-1], (D(2026, 11, 13), 1378.0))

    def test_a_real_5_minute_spark_answer(self):
        with open(SPARK5, encoding="utf-8") as fh:
            data = scan.parse_spark(fh.read())
        self.assertEqual(len(data), 20)
        t = data["HCLTECH.NS"]
        self.assertEqual(len(t["t"]), 73)
        self.assertEqual(scan.ts_to_ist(t["t"][0]), DT(2026, 11, 13, 9, 15))
        times = [scan.ts_to_ist(x) for x in t["t"]]
        self.assertNotIn(DT(2026, 11, 13, 15, 15), times)        # Yahoo's NSE gap
        self.assertNotIn(DT(2026, 11, 13, 15, 20), times)
        bars = scan.session_bars(t, DAY, DT(2026, 11, 13, 15, 0))
        self.assertTrue(scan.usable(bars, DAY, DT(2026, 11, 13, 15, 0), 3))   # to the 15:00 cutoff: whole

    def test_spark_errors(self):
        too_many = '{"spark":{"result":null,"error":{"code":"Bad Request",' \
                   '"description":"Number of symbols needs to be less than or equal to 20"}}}'
        with self.assertRaises(scan.ScanError) as cm:
            scan.parse_spark(too_many)
        self.assertIn("less than or equal to 20", str(cm.exception))
        self.assertEqual(scan.parse_spark('{"spark":{"result":[],"error":null}}'), {})
        with self.assertRaises(scan.ScanError):
            scan.parse_spark('{"chart":{}}')

    def test_urls(self):
        self.assertEqual(scan.spark_path(["M&M", "reliance.ns", "BAJAJ-AUTO"], "3mo", "1d"),
                         "/v7/finance/spark?symbols=M%26M.NS,RELIANCE.NS,BAJAJ-AUTO.NS&range=3mo&interval=1d")
        self.assertEqual(scan.chart_path("HCLTECH", "1d", "5m"), "/v8/finance/chart/HCLTECH.NS?range=1d&interval=5m")
        self.assertEqual(scan.nse_symbol("500325.bo"), "500325.BO")


class Network(unittest.TestCase):
    """429s and 5xx without the network."""

    def setUp(self):
        self.calls, self.sleeps = [], []
        self._get, self._sleep = scan.http_get, scan.SLEEP
        scan.SLEEP = self.sleeps.append
        with open(SPARK5, encoding="utf-8") as fh:
            self.body = fh.read()

    def tearDown(self):
        scan.http_get, scan.SLEEP = self._get, self._sleep

    def answers(self, codes):
        codes = list(codes)

        def fake(url, timeout=20):
            self.calls.append(url.split("/v")[0])
            code = codes.pop(0) if codes else 200
            if code != 200:
                raise urllib.error.HTTPError(url, code, "x", {}, io.BytesIO(b""))
            return self.body
        scan.http_get = fake

    def test_429_falls_back_then_waits_once(self):
        self.answers([429, 429, 200])
        text = scan.yahoo_get("/v7/finance/spark?symbols=HCLTECH.NS&range=3mo&interval=1d")
        self.assertEqual(text, self.body)
        self.assertEqual(self.calls, ["https://query2.finance.yahoo.com", "https://query1.finance.yahoo.com",
                                      "https://query2.finance.yahoo.com"])
        self.assertEqual(self.sleeps, [scan.BACKOFF])

    def test_5xx_goes_to_query1_without_waiting(self):
        self.answers([503, 200])
        scan.yahoo_get("/v8/finance/chart/HCLTECH.NS?range=1d&interval=5m")
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(self.sleeps, [])

    def test_429_for_good_is_reported_as_partial(self):
        with open(SPARK5, encoding="utf-8") as fh:
            first20 = sorted(scan.parse_spark(fh.read()))
        self.answers([200] + [429] * 10)
        syms = first20 + ["X%02d.NS" % i for i in range(20)]
        data, failed = scan.fetch_spark(syms, "1d", "5m", 0.3)
        self.assertEqual(len(data), 20)
        self.assertEqual(len(failed), 20)
        self.assertIn("HTTP 429", failed["X00.NS"])
        self.assertEqual(self.sleeps, [0.3, scan.BACKOFF])       # a pause between batches, one backoff

    def test_a_404_is_final(self):
        self.answers([404])
        with self.assertRaises(scan.ScanError):
            scan.yahoo_get("/v8/finance/chart/NOPE.NS?range=1d&interval=5m")
        self.assertEqual(len(self.calls), 1)


def _rsi(c, n=14):
    """Wilder's RSI, written again from the textbook for the check."""
    gains = [max(0.0, b - a) for a, b in zip(c, c[1:])]
    losses = [max(0.0, a - b) for a, b in zip(c, c[1:])]
    ag, al = sum(gains[:n]) / n, sum(losses[:n]) / n
    for g, l in zip(gains[n:], losses[n:]):
        ag, al = (ag * (n - 1) + g) / n, (al * (n - 1) + l) / n
    return 100.0 if al == 0 else 100 - 100 / (1 + ag / al)


class IndependentChecks(unittest.TestCase):
    """The scanner's answers on real data against the rules written out again here."""

    def test_daily_setups(self):
        data, _ = scan.load_offline(DAILY)
        want = {}
        for sym, s in data.items():
            c = [float(x) for x in s["c"] if x is not None]          # Nov 13's bar is complete on Monday
            tags = []
            if c[-1] > max(c[-21:-1]):
                tags.append("breakout_20d")
            if c[-6] / c[-16] - 1 > 0.10 and (max(c[-5:]) - min(c[-5:])) / c[-1] < 0.05:
                tags.append("bull_flag")
            if c[-2] < sum(c[-21:-1]) / 20 and c[-1] > sum(c[-20:]) / 20:
                tags.append("reclaim_ma20")
            if _rsi(c) < 30:
                tags.append("oversold")
            if _rsi(c[:-1]) < 30 and c[-1] > c[-2]:
                tags.append("oversold_bounce")
            if tags:
                want[sym] = tags
        hits, counts, last = scan.scan_daily(data, sorted(data), scan.parse_now("2026-11-16 08:30"), 0, 0)
        self.assertEqual({h["symbol"]: h["setups"] for h in hits}, want)
        self.assertEqual((len(hits), last), (14, D(2026, 11, 13)))

    def test_opening_range_breakouts(self):
        data, _ = scan.load_offline(WALL)
        for cut, n in (("09:35", 13), ("10:00", 29), ("15:00", 34)):
            cutoff = DT.combine(DAY, datetime.time(*map(int, cut.split(":"))))
            want = set()
            for sym, s in data.items():
                bars = [(scan.ts_to_ist(t), h, l, c) for t, h, l, c in zip(s["t"], s["h"], s["l"], s["c"])
                        if c is not None and scan.ts_to_ist(t) + datetime.timedelta(minutes=5) <= cutoff]
                oh = max(b[1] for b in bars[:3])
                if any(b[3] > oh for b in bars[3:]):
                    want.add(sym)
            day, cutoff2 = scan.orb_window(scan.parse_now("2026-11-13 " + cut), None, 15, datetime.time(15, 0))
            hits, counts, _ = scan.scan_orb(data, sorted(data), day, cutoff2, 15, 0, 0)
            self.assertEqual({h["symbol"] for h in hits}, want, cut)
            self.assertEqual(len(hits), n, cut)
            if cut == "09:35":
                self.assertEqual(sorted(want), ORB_0935)


class Daily(unittest.TestCase):
    def setUp(self):
        self.data, self.errors = scan.load_offline(DAILY)
        self.syms = sorted(self.data)

    def test_setups_before_monday_open(self):
        hits, counts, last = scan.scan_daily(self.data, self.syms, scan.parse_now("2026-11-16 08:30"), 0, 0)
        self.assertEqual(counts, {"requested": 50, "fetched": 50, "illiquid": 0, "short": 0, "scanned": 50,
                                  "hits": 14})
        baj = [h for h in hits if h["symbol"] == "BAJFINANCE.NS"][0]
        self.assertEqual(baj, {"symbol": "BAJFINANCE.NS", "setups": ["breakout_20d", "bull_flag"], "price": 1117.0,
                               "close_date": "2026-11-13", "rsi": 72.0, "volume": 11898219})
        self.assertEqual(hits[0]["symbol"], "RELIANCE.NS")       # most rupees traded first

    def test_the_in_progress_bar_is_dropped(self):
        during = scan.scan_daily(self.data, self.syms, scan.parse_now("2026-11-13 12:00"), 0, 0)
        self.assertEqual(during[2], D(2026, 11, 12))
        after = scan.scan_daily(self.data, self.syms, scan.parse_now("2026-11-13 15:30"), 0, 0)
        self.assertEqual(after[2], D(2026, 11, 13))

    def test_liquidity_filter_in_rupees(self):
        hits, counts, _ = scan.scan_daily(self.data, self.syms, scan.parse_now("2026-11-16 08:30"), 20, 100000)
        self.assertEqual(counts["illiquid"], 0)                  # every Nifty 50 stock clears the defaults
        hits, counts, _ = scan.scan_daily(self.data, self.syms, scan.parse_now("2026-11-16 08:30"), 5000, 0)
        self.assertEqual(counts["scanned"], sum(1 for s in self.data.values()
                                                if s["meta"]["regularMarketPrice"] >= 5000))

    def test_short_and_empty_charts(self):
        s = {"t": [ts("2026-11-%02d 09:15" % d) for d in range(2, 12)], "c": [10.0] * 10,
             "meta": {"regularMarketPrice": 100, "regularMarketVolume": 5000000}}
        hits, counts, last = scan.scan_daily({"X.NS": s, "E.NS": {"t": [], "c": [], "meta": {}}},
                                             ["X.NS", "E.NS", "GONE.NS"], scan.parse_now("2026-11-16 08:30"),
                                             20, 100000)
        self.assertEqual(hits, [])
        self.assertEqual((counts["fetched"], counts["short"], counts["illiquid"], counts["scanned"]), (2, 1, 1, 0))
        self.assertIsNone(last)

    def test_rsi_math(self):
        self.assertIsNone(scan.rsi([1.0] * 10))
        self.assertEqual(scan.rsi([float(x) for x in range(1, 40)]), 100.0)
        closes = [44.34, 44.09, 44.15, 43.61, 44.33, 44.83, 45.10, 45.42, 45.84, 46.08, 45.89, 46.03, 45.61,
                  46.28, 46.28]
        self.assertAlmostEqual(scan.rsi(closes), 70.46, places=1)  # Wilder's textbook example


class Orb(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data, cls.errors = scan.load_offline(WALL)
        cls.syms = sorted(cls.data)

    def scan_at(self, now, min_price=0, syms=None, or_minutes=15):
        day, cutoff = scan.orb_window(scan.parse_now(now), None, or_minutes, datetime.time(15, 0))
        return scan.scan_orb(self.data, syms or self.syms, day, cutoff, or_minutes, min_price, 0)

    def test_the_scan_at_0935(self):
        hits, counts, failed = self.scan_at("2026-11-13 09:35")
        self.assertEqual((len(self.syms), counts["scanned"], len(hits)), (50, 50, 13))
        hcl = [h for h in hits if h["symbol"] == "HCLTECH.NS"][0]
        self.assertEqual(hcl, {"symbol": "HCLTECH.NS", "setups": ["orb"], "price": 1384.6, "at": "9:35 AM",
                               "bar_start": "09:30", "bar_index": 3, "or_high": 1381.0, "or_low": 1373.8,
                               "pct_over": 0.26})
        self.assertEqual([h["symbol"] for h in hits], ORB_0935)   # all at 9:35, then by symbol

    def test_price_floor(self):
        hits, counts, _ = self.scan_at("2026-11-13 09:35", min_price=200)
        self.assertNotIn("TATASTEEL.NS", [h["symbol"] for h in hits])      # Rs 187
        self.assertEqual(len(hits), 12)

    def test_in_progress_bar_and_no_breakout_yet(self):
        with self.assertRaises(scan.ScanError) as cm:
            self.scan_at("2026-11-13 09:34", syms=["HCLTECH.NS"])
        self.assertIn("Run orb again after 9:35 AM", str(cm.exception))
        hits, _, _ = self.scan_at("2026-11-13 09:35", syms=["HCLTECH.NS"])
        self.assertEqual(hits[0]["at"], "9:35 AM")

    def test_stage_one_is_a_necessary_condition(self):
        cut = DT(2026, 11, 13, 10, 0)
        for sym, s in self.data.items():
            bars = scan.session_bars(s, DAY, cut)
            if scan.usable(bars, DAY, cut, 3) and scan.orb_hit(bars, 3):
                self.assertTrue(scan.orb_candidate(bars, 3), sym)

    def test_confirm_uses_the_v8_highs(self):
        spark_like = {k: dict(v, h=None, l=None) for k, v in self.data.items()}   # closes only, like spark
        asked = []

        def confirm(sym):
            asked.append(sym)
            return self.data[sym]
        hits, counts, failed = scan.scan_orb(spark_like, self.syms, DAY, DT(2026, 11, 13, 9, 35), 15, 0, 0, confirm)
        self.assertEqual(len(hits), 13)
        self.assertEqual(counts["candidates"], len(asked))
        self.assertLess(len(asked), 50)                            # stage 1 skipped about half

        def broken(sym):
            raise scan.ScanError("Yahoo answered HTTP 429 for /v8/finance/chart/%s" % sym)
        hits, counts, failed = scan.scan_orb(spark_like, ["HCLTECH.NS", "ITC.NS"], DAY, DT(2026, 11, 13, 9, 35),
                                             15, 0, 0, broken)
        self.assertEqual(hits, [])
        self.assertIn("429", failed["HCLTECH.NS"])

    def test_the_stage_two_cap_takes_the_most_traded(self):
        spark_like = {k: dict(v, h=None, l=None) for k, v in self.data.items()}
        asked = []

        def confirm(sym):
            asked.append(sym)
            return self.data[sym]
        hits, counts, _ = scan.scan_orb(spark_like, self.syms, DAY, DT(2026, 11, 13, 10, 0), 15, 0, 0, confirm,
                                        max_confirm=10)
        self.assertEqual((counts["confirmed"], counts["unconfirmed"]), (10, counts["candidates"] - 10))
        hits_all, _, _ = scan.scan_orb(spark_like, self.syms, DAY, DT(2026, 11, 13, 10, 0), 15, 0, 0, confirm,
                                       max_confirm=0)
        self.assertEqual(len(hits_all), 29)
        for h in hits:
            self.assertIn(h, hits_all)

    def test_a_missing_bar_makes_a_chart_unusable(self):
        s = bars_series("2026-11-13", [10, 10.2, 10.1, None, 10.5, 10.6, 10.7, 10.8, 10.9])
        bars = scan.session_bars(s, DAY, DT(2026, 11, 13, 10, 0))
        self.assertFalse(scan.usable(bars, DAY, DT(2026, 11, 13, 10, 0), 3))

    def test_a_30_minute_range(self):
        closes = [100, 101, 100.5, 100.8, 101.2, 100.9, 101.5] + [101.0] * 40
        s = bars_series("2026-11-13", closes, highs=[c + 0.2 for c in closes])
        hits, counts, _ = scan.scan_orb({"X.NS": s}, ["X.NS"], DAY, DT(2026, 11, 13, 12, 0), 30, 0, 0)
        self.assertEqual(counts["scanned"], 1)
        self.assertEqual(hits[0]["at"], "9:50 AM")                # range 9:15 to 9:45 (high 101.4), 9:45 bar 101.5
        self.assertEqual(hits[0]["or_high"], 101.4)

    def test_window_messages(self):
        until = datetime.time(15, 0)

        def msg(now, at=None, until=until):
            with self.assertRaises(scan.ScanError) as cm:
                scan.orb_window(scan.parse_now(now), at, 15, until)
            return str(cm.exception)
        self.assertIn("weekend", msg("2026-11-14 10:15"))
        self.assertIn("NSE holiday: Diwali-Balipratipada", msg("2026-11-10 10:15"))
        self.assertIn("the 15-minute opening range runs 9:15 AM to 9:30 AM", msg("2026-11-13 09:25"))
        self.assertIn("Run orb again after 9:35 AM", msg("2026-11-13 09:32"))
        self.assertIn("expired", msg("2026-11-13 15:05"))
        self.assertIn("expired", msg("2026-11-13 11:30", until=datetime.time(11, 0)))
        self.assertIn("closed at 3:30 PM", msg("2026-11-13 15:45", until=datetime.time(15, 40)))
        self.assertIn("later than now", msg("2026-11-13 09:40", at=datetime.time(10, 15)))
        self.assertIn("after the 3:30 PM close", msg("2026-11-13 17:00", at=datetime.time(15, 45)))
        self.assertEqual(scan.orb_window(scan.parse_now("2026-11-13 16:30"), datetime.time(9, 45), 15, until),
                         (DAY, DT(2026, 11, 13, 9, 45)))
        self.assertEqual(scan.orb_window(scan.parse_now("2026-11-13 09:35"), None, 15, until)[1],
                         DT(2026, 11, 13, 9, 35))
        with self.assertRaises(scan.ScanError):
            scan.orb_window(scan.parse_now("2026-11-13 10:15"), None, 7, until)


class Cli(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.cwd = os.getcwd()
        os.chdir(self.d)

    def tearDown(self):
        os.chdir(self.cwd)
        shutil.rmtree(self.d)

    def test_universe_daily_orb_end_to_end(self):
        code, text, _ = run(["universe"])
        self.assertEqual(code, 0)
        self.assertIn("Nifty 50: 50 stocks (shipped list of 2026-11-14).", text)
        with open(os.path.join("trader", "universe.txt"), encoding="utf-8") as fh:
            lines = fh.read().splitlines()
        self.assertEqual((len(lines), lines[0]), (50, "ADANIENT.NS|Adani Enterprises Ltd."))

        code, text, _ = run(["daily", "--offline", DAILY, "--now", "2026-11-16 08:30", "--universe",
                             os.path.join("trader", "universe.txt")])
        self.assertEqual(code, 0)
        self.assertIn("Daily scan, Mon 2026-11-16 08:30 IST, closes through 2026-11-13", text)
        self.assertIn("Rs 20+ and 100000+ shares", text.replace(",", ""))
        self.assertIn("14 charts matched a setup", text)
        self.assertIn("BAJFINANCE.NS    Rs 1117.00", text)
        with open(os.path.join("trader", "watchlist.json")) as fh:
            wl = json.load(fh)
        self.assertEqual((wl["mode"], wl["as_of"], wl["universe"], len(wl["hits"])), ("daily", "2026-11-13 close",
                                                                                      50, 14))

        code, text, _ = run(["orb", "--offline", WALL, "--now", "2026-11-13 09:35"])
        self.assertEqual(code, 0)
        self.assertIn("Opening-range breakout scan, Fri 2026-11-13 9:35 AM IST: 15-minute range (9:15 AM to "
                      "9:30 AM)", text)
        self.assertIn("13 of 50 charts closed above their opening-range high by 9:35 AM", text)
        self.assertIn("HCLTECH.NS       Rs 1384.60  range 1,373.80 to 1,381.00  +0.26% over", text)
        with open(os.path.join("trader", "watchlist.json")) as fh:
            wl = json.load(fh)
        self.assertEqual((wl["mode"], wl["as_of"], len(wl["hits"])), ("orb", "2026-11-13 09:35 IST", 13))

    def test_universe_refresh_note_and_json(self):
        saved = scan.http_get
        scan.http_get = lambda url, timeout=20: (_ for _ in ()).throw(urllib.error.URLError("offline"))
        try:
            code, text, _ = run(["universe", "--index", "nifty50,banknifty", "--refresh", "--pause", "0",
                                 "--json", "--no-write"])
        finally:
            scan.http_get = saved
        doc = json.loads(text)
        self.assertEqual(doc["count"], 59)
        self.assertEqual(len(doc["notes"]), 2)
        self.assertIn("using the shipped list", doc["notes"][0])
        code, _, err = run(["universe", "--index", "sensex"])
        self.assertEqual(code, 1)
        self.assertIn("unknown index", err)

    def test_plain_messages_and_exit_codes(self):
        code, _, err = run(["daily"])
        self.assertEqual(code, 1)
        self.assertIn("run `scan.py universe` first", err)
        code, _, err = run(["orb", "--offline", WALL])
        self.assertIn("give --at HH:MM", err)
        code, text, err = run(["orb", "--offline", WALL, "--at", "09:32"])
        self.assertEqual(code, 1)
        self.assertIn("Run orb again after 9:35 AM", err)
        code, _, err = run(["orb", "--offline", WALL, "--now", "2026-11-13 15:10"])
        self.assertIn("expired", err)
        os.mkdir("trader")
        with open(os.path.join("trader", "config.json"), "w") as fh:
            json.dump({"no_entries_after": "15:20"}, fh)
        self.assertEqual(run(["orb", "--offline", WALL, "--now", "2026-11-13 15:10", "--no-write"])[0], 0)
        code, _, err = run(["daily", "--offline", DAILY, "--now", "noon"])
        self.assertIn("--now wants", err)
        self.assertNotIn("Traceback", err)

    def test_symbol_lists(self):
        code, text, _ = run(["daily", "--offline", DAILY, "--now", "2026-11-16 08:30", "--symbols",
                             "reliance,BAJFINANCE,m&m", "--json", "--no-write"])
        doc = json.loads(text)
        self.assertEqual(doc["universe"], 3)
        self.assertEqual(sorted(h["symbol"] for h in doc["hits"]), ["BAJFINANCE.NS", "RELIANCE.NS"])
        with open("list.txt", "w") as fh:
            fh.write("# my list\nHCLTECH.NS|HCL Technologies\nINFY\n")
        code, text, _ = run(["orb", "--offline", WALL, "--now", "2026-11-13 09:35", "--watchlist", "list.txt",
                             "--json", "--no-write"])
        self.assertEqual(sorted(h["symbol"] for h in json.loads(text)["hits"]), ["HCLTECH.NS", "INFY.NS"])

    def test_offline_folder_of_v8_files(self):
        with gzip.open(WALL, "rt", encoding="utf-8") as fh:
            bundle = json.load(fh)
        os.mkdir("charts")
        for sym in ("HCLTECH.NS", "M&M.NS", "ITC.NS"):
            with open(os.path.join("charts", sym + ".json"), "w") as fh:
                json.dump(bundle[sym], fh)
        code, text, _ = run(["orb", "--offline", "charts", "--now", "2026-11-13 09:35", "--json", "--no-write"])
        doc = json.loads(text)
        self.assertEqual((doc["universe"], [h["symbol"] for h in doc["hits"]]), (3, ["HCLTECH.NS"]))


if __name__ == "__main__":
    unittest.main()
