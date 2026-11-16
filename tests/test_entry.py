"""trader-entry tests. Fixtures in tests/fixtures/trader-entry/:

HCLTECH-2026-11-13-5m.json  HCLTECH.NS's Fri Nov 13 2026 five-minute bars, cut from a
                            real Yahoo range=60d answer (fetched Sat Nov 14 2026). It ends
                            with the 10:45 bar and a live tick at 10:49:45 that repeats that
                            bar's close (added, to give the file the shape of a live range=1d
                            answer). meta trimmed to one day. Yahoo sends 0 volume for the
                            9:15 bar on NSE symbols (the opening auction is not in it).
DEMO-1m-synthetic.json      SYNTHETIC one-minute bars (not market data): a wick above the
                            range high, a close AT the high, a null bar, a live tick. The
                            upstream file, moved from 9:30 New York to 9:15 IST.
"""

import copy
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

from _load import load, FIX, ROOT

entry = load("trader-entry", "entry")

EDIR = os.path.join(FIX, "trader-entry")
HCL = os.path.join(EDIR, "HCLTECH-2026-11-13-5m.json")
DEMO = os.path.join(EDIR, "DEMO-1m-synthetic.json")
OPEN_TS = 1794541500       # 2026-11-13 09:15 IST (03:45 UTC)
DT = datetime.datetime


def ist(text):
    return entry.parse_now(text)


def doc(path=HCL):
    with open(path) as fh:
        return json.load(fh)


def chart(d=None, sym="HCLTECH.NS"):
    return entry.parse_chart(json.dumps(d if d is not None else doc()), sym)


def at(text, d=None, **kw):
    return entry.evaluate(chart(d), ist(text), **kw)


def shift_to(d, day):
    """The same session moved to another date. 9:15 IST is 03:45 UTC on every date: no DST."""
    d = copy.deepcopy(d)
    r = d["chart"]["result"][0]
    new_open = int((DT.combine(day, datetime.time(3, 45)) - DT(1970, 1, 1)).total_seconds())
    delta = new_open - OPEN_TS
    r["timestamp"] = [t + delta for t in r["timestamp"]]
    r["meta"]["regularMarketTime"] += delta
    return d


def no_breakout(d=None):
    """Every bar after the range stays under the 1381.00 high."""
    d = copy.deepcopy(d if d is not None else doc())
    q = d["chart"]["result"][0]["indicators"]["quote"][0]
    for i in range(3, len(q["close"])):
        q["close"][i] = min(q["close"][i], 1380.80)
        q["high"][i] = min(q["high"][i], 1380.90)
        q["open"][i] = min(q["open"][i], 1380.80)
    return d


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = entry.main(argv)
    return code, out.getvalue(), err.getvalue()


class TheExample(unittest.TestCase):
    def test_triggers_at_0935_on_the_0930_bar(self):
        r = at("2026-11-13 09:35")
        self.assertEqual(r["status"], "triggered")
        self.assertEqual(r["opening_range"]["high"], 1381.00)
        self.assertEqual(r["opening_range"]["low"], 1373.80)
        self.assertEqual(r["opening_range"]["bars"], 3)
        t = r["trigger"]
        self.assertEqual(t["time"], "9:35 AM")
        self.assertEqual(t["bar_start"], "09:30")
        self.assertEqual(t["bar_index"], 3)
        self.assertEqual(t["price"], 1384.60)
        self.assertEqual(t["close"], 1384.5999755859375)
        self.assertEqual(t["pct_over"], 0.26)
        self.assertEqual(r["level"], 1381.00)
        self.assertEqual(r["prev_close"], 1380.8)
        self.assertEqual((r["opens"], r["closes"]), ("09:15", "15:30"))

    def test_at_0934_the_0930_bar_is_still_forming(self):
        r = at("2026-11-13 09:34")
        self.assertEqual(r["status"], "waiting")
        self.assertIsNone(r["trigger"])
        self.assertEqual(r["last"]["bar_start"], "09:25")
        self.assertEqual(r["last"]["close"], 1378.60)
        self.assertEqual(r["forming"]["bar_start"], "09:30")
        self.assertIn("Rs 2.40 under the range high Rs 1381.00", r["reason"])
        self.assertEqual(at("2026-11-13 09:34:59")["status"], "waiting")

    def test_before_the_open_and_while_the_range_forms(self):
        r = at("2026-11-13 09:10")
        self.assertEqual((r["status"], r["phase"]), ("waiting", "pre-open"))
        self.assertIn("the NSE opens at 9:15", r["reason"])
        r = at("2026-11-13 09:29")
        self.assertEqual((r["status"], r["phase"]), ("waiting", "forming"))
        self.assertEqual(r["opening_range"]["bars"], 2)
        self.assertFalse(r["opening_range"]["complete"])
        r = at("2026-11-13 09:31")
        self.assertEqual((r["status"], r["phase"]), ("waiting", "open"))
        self.assertEqual(r["opening_range"]["bars"], 3)

    def test_the_live_tick_and_the_in_progress_bar_are_dropped(self):
        c = chart()
        self.assertEqual(c["bars"][-1]["t"], OPEN_TS + 94 * 60 + 45)   # 10:49:45 is in the file
        r = entry.evaluate(c, entry.utc_of(c["data_time"]))           # read as of the file's own time
        self.assertEqual(r["now"], "2026-11-13 10:49:45")
        self.assertEqual(r["_bars"][-1]["slot"], 17)                    # the 10:40 bar
        self.assertEqual(r["forming"]["bar_start"], "10:45")
        self.assertEqual(r["bars_closed"], 18)
        # 10:50: closed by the clock, but Yahoo's last trade (10:49:45) is before its close
        r = at("2026-11-13 10:50")
        self.assertEqual(r["_bars"][-1]["slot"], 17)
        self.assertIn("Yahoo's last trade is 10:49:45", r["lag_note"])
        # a minute later with no newer trade it counts; the 10:49:45 tick never becomes a bar
        r = at("2026-11-13 10:51")
        self.assertEqual(r["_bars"][-1]["slot"], 18)
        self.assertEqual(r["bars_closed"], 19)
        self.assertTrue(all(b["t"] % 300 == 0 for b in r["_bars"]))

    def test_after_the_close_it_stays_triggered_and_says_it_is_late(self):
        r = at("2026-11-13 15:35")
        self.assertEqual((r["status"], r["phase"]), ("triggered", "after-close"))
        self.assertEqual(r["trigger"]["time"], "9:35 AM")
        text = "\n".join(entry.describe(r))
        self.assertIn("minutes ago", text)
        self.assertNotIn("This is the moment", text)
        self.assertIn("IST", text)


class Rules(unittest.TestCase):
    def test_the_opening_bar_has_no_volume_on_yahoo(self):
        c = chart()
        self.assertEqual(c["bars"][0]["v"], 0)             # 9:15: the auction is not in Yahoo's bar
        r = at("2026-11-13 10:49")
        self.assertEqual(r["opening_range"]["avg_volume"], 14773)   # (0 + 26920 + 17400) / 3

    def test_volume_confirmation_moves_the_trigger(self):
        r = at("2026-11-13 10:49", min_volume_x=4)
        t = r["trigger"]
        self.assertEqual((t["time"], t["bar_index"], t["price"]), ("9:40 AM", 4, 1389.70))
        self.assertEqual(t["volume_x"], 6.4)
        r = at("2026-11-13 09:36", min_volume_x=4)
        self.assertEqual(r["status"], "waiting")
        self.assertIn("3.05x the range's volume, under your 4.00x", r["reason"])
        self.assertEqual(at("2026-11-13 09:35", min_volume_x=1)["trigger"]["bar_index"], 3)

    def test_level_setup(self):
        r = at("2026-11-13 10:49", setup="level", level=1393.5)
        self.assertEqual(r["trigger"]["time"], "10:35 AM")
        self.assertEqual(r["trigger"]["bar_index"], 15)
        self.assertEqual(r["trigger"]["price"], 1393.90)
        # a level under the open: the first eligible close is the 9:25 bar's, at 9:30 (no_entries_before)
        r = at("2026-11-13 10:49", setup="level", level=1370)
        self.assertEqual((r["trigger"]["time"], r["trigger"]["bar_index"]), ("9:30 AM", 2))
        with self.assertRaises(entry.EntryError):
            at("2026-11-13 10:30", setup="level")

    def test_no_breakout_waits_then_expires_at_the_cutoff(self):
        d = no_breakout()
        r = at("2026-11-13 10:49", d)
        self.assertEqual(r["status"], "waiting")
        self.assertEqual(at("2026-11-13 14:59", d)["status"], "waiting")
        r = at("2026-11-13 15:00", d)
        self.assertEqual(r["status"], "expired")
        self.assertIn("by 15:00", r["reason"])
        self.assertEqual(at("2026-11-13 15:40", d)["phase"], "after-close")

    def test_the_bar_closing_at_the_cutoff_still_counts_when_yahoo_lags(self):
        d = no_breakout()
        r0 = d["chart"]["result"][0]
        keep = [i for i, t in enumerate(r0["timestamp"]) if t <= OPEN_TS + 14 * 300]   # live: up to the 10:25 bar
        r0["timestamp"] = [r0["timestamp"][i] for i in keep]
        q = r0["indicators"]["quote"][0]
        for k in q:
            q[k] = [q[k][i] for i in keep]
        r0["meta"]["regularMarketTime"] = OPEN_TS + 74 * 60 + 40                       # last trade 10:29:40
        cfg = {"no_entries_before": "09:30", "no_entries_after": "10:30"}
        r = at("2026-11-13 10:30:10", d, cfg=cfg)                           # the 10:25 bar closed by the clock only
        self.assertEqual(r["status"], "waiting")
        self.assertIn("Yahoo's last trade is 10:29:40", r["lag_note"])
        self.assertEqual(at("2026-11-13 10:31", d, cfg=cfg)["status"], "expired")

    def test_config_cutoff(self):
        cfg = {"no_entries_before": "09:30", "no_entries_after": "09:34"}
        r = at("2026-11-13 09:35", cfg=cfg)
        self.assertEqual(r["status"], "expired")
        cfg = {"no_entries_before": "09:45", "no_entries_after": "15:00"}
        r = at("2026-11-13 10:00", cfg=cfg)
        self.assertEqual(r["trigger"]["time"], "9:45 AM")       # the 9:40 bar, first to close at or after 9:45

    def test_default_window_is_0930_to_1500(self):
        r = at("2026-11-13 09:35")
        self.assertEqual((r["no_entries_before"], r["no_entries_after"]), ("09:30", "15:00"))

    def test_bad_inputs(self):
        with self.assertRaises(entry.EntryError):
            at("2026-11-13 09:35", or_minutes=7)
        with self.assertRaises(entry.EntryError):
            at("2026-11-13 09:35", interval="15m")
        with self.assertRaises(entry.EntryError):
            entry.parse_now("tomorrow")
        with self.assertRaises(entry.EntryError):
            entry.parse_hhmm("25:00", "x")
        self.assertEqual(entry.parse_now("2026-11-13 09:35"), DT(2026, 11, 13, 4, 5))
        self.assertEqual(entry.parse_now("2026-11-13T04:05:00Z"), DT(2026, 11, 13, 4, 5))
        self.assertEqual(entry.parse_now("2026-11-13 09:35 IST"), DT(2026, 11, 13, 4, 5))
        self.assertEqual(entry.parse_now("2026-11-13T09:35:00+05:30"), DT(2026, 11, 13, 4, 5))

    def test_or_minutes_30(self):
        r = at("2026-11-13 10:49", or_minutes=30)
        self.assertEqual(r["opening_range"]["bars"], 6)
        self.assertEqual(r["opening_range"]["high"], 1391.00)
        self.assertEqual(r["trigger"]["time"], "10:10 AM")
        self.assertEqual(r["trigger"]["bar_index"], 10)


class OneMinute(unittest.TestCase):
    def c(self):
        return entry.parse_chart(json.dumps(doc(DEMO)), "DEMO")

    def test_wick_and_close_at_the_high_do_not_trigger(self):
        c = self.c()
        r = entry.evaluate(c, entry.utc_of(c["data_time"]), interval="1m")
        self.assertEqual(r["now"], "2026-11-13 09:51:30")
        self.assertEqual(r["opening_range"], {"high": 100.5, "low": 99.0, "minutes": 15, "bars": 15, "of": 15,
                                              "complete": True, "avg_volume": 10667})
        t = r["trigger"]
        self.assertEqual((t["time"], t["bar_start"], t["bar_index"], t["price"]), ("9:44 AM", "09:43", 28, 100.62))
        r = entry.evaluate(c, ist("2026-11-13 09:43:59"), interval="1m")
        self.assertEqual(r["status"], "waiting")
        self.assertEqual(r["forming"]["bar_start"], "09:43")
        self.assertEqual(r["last"]["close"], 100.5)             # the 9:42 bar closed AT the high

    def test_null_bar_tick_and_volume(self):
        c = self.c()
        r = entry.evaluate(c, entry.utc_of(c["data_time"]), interval="1m", min_volume_x=2)
        self.assertEqual((r["trigger"]["time"], r["trigger"]["bar_index"]), ("9:47 AM", 31))
        slots = [b["slot"] for b in r["_bars"]]
        self.assertNotIn(19, slots)                               # 9:34 came as nulls
        self.assertEqual(slots[-1], 35)                           # 9:51 still forming, 9:51:30 tick dropped
        self.assertEqual(r["forming"]["bar_start"], "09:51")

    def test_the_file_and_the_interval_must_agree(self):
        code, _, err = run(["check", "DEMO", "--offline", DEMO])
        self.assertEqual(code, 1)
        self.assertIn("1m bars, not 5m", err)


class Calendar(unittest.TestCase):
    def test_no_daylight_saving(self):
        # 9:35 IST is 04:05 UTC in December and in July alike
        for day in (datetime.date(2026, 12, 7), datetime.date(2026, 7, 7), datetime.date(2026, 3, 9)):
            d = shift_to(doc(), day)
            r = entry.evaluate(chart(d), ist("%s 09:35" % day))
            self.assertEqual(r["status"], "triggered", day)
            self.assertEqual(r["trigger"]["time"], "9:35 AM", day)
            self.assertEqual(r["trigger"]["bar_index"], 3, day)
            self.assertEqual(entry.evaluate(chart(d), ist("%s 09:34" % day))["status"], "waiting", day)
            self.assertEqual(ist("%s 09:35" % day), DT.combine(day, datetime.time(4, 5)))

    def test_no_early_closes(self):
        # Christmas Eve is a full NSE session (the NYSE closes at 1:00 p.m. that day)
        d = shift_to(no_breakout(), datetime.date(2026, 12, 24))
        r = entry.evaluate(chart(d), ist("2026-12-24 14:59"))
        self.assertEqual(r["status"], "waiting")
        self.assertEqual((r["closes"], r["no_entries_after"]), ("15:30", "15:00"))
        self.assertNotIn("early", "\n".join(entry.describe(r)).lower())

    def test_weekend_holidays_and_empty_data(self):
        r = at("2026-11-14 10:30")
        self.assertEqual((r["status"], r["phase"]), ("no-data", "closed"))
        self.assertIn("weekend", r["reason"])
        self.assertEqual(r["next_open"], "2026-11-16 09:15")
        r = at("2026-11-10 10:30")
        self.assertIn("NSE holiday: Diwali-Balipratipada", r["reason"])
        self.assertEqual(r["next_open"], "2026-11-11 09:15")
        self.assertIn("Prakash Gurpurb", at("2026-11-24 10:30")["reason"])
        self.assertIn("Dussehra", at("2026-10-20 10:30")["reason"])
        # Muhurat trading (Sun Nov 8) is a special session, not a day-trading day
        self.assertEqual(at("2026-11-08 18:30")["phase"], "closed")
        # US holidays are ordinary NSE days
        self.assertNotEqual(at("2026-11-26 10:30")["phase"], "closed")            # Thanksgiving
        empty = copy.deepcopy(doc())
        res = empty["chart"]["result"][0]
        del res["timestamp"]
        res["indicators"] = {"quote": [{}]}
        r = at("2026-11-13 09:35", empty)
        self.assertEqual((r["status"], r["phase"]), ("no-data", "open"))
        r = at("2026-11-16 09:35")                                # Yahoo sent Friday's bars only
        self.assertEqual(r["status"], "no-data")
        self.assertTrue(at("2026-11-13 09:35")["calendar_known"])
        self.assertFalse(at("2027-03-01 10:30")["calendar_known"])
        self.assertIn("NSE holiday list", "\n".join(entry.describe(at("2027-03-01 10:30"))))

    def test_yahoo_errors(self):
        bad = json.dumps({"chart": {"result": None, "error": {"code": "Not Found",
                                                              "description": "No data found, symbol may be delisted"}}})
        with self.assertRaises(entry.EntryError) as cm:
            entry.parse_chart(bad, "ZZZZ.NS")
        self.assertIn("No data found", str(cm.exception))
        with self.assertRaises(entry.EntryError):
            entry.parse_chart("<html>", "HCLTECH.NS")


class Symbols(unittest.TestCase):
    def test_nse_symbols_keep_their_dot(self):
        self.assertEqual(entry.yahoo_symbol("reliance"), "RELIANCE.NS")
        self.assertEqual(entry.yahoo_symbol("RELIANCE.NS"), "RELIANCE.NS")
        self.assertEqual(entry.yahoo_symbol("500325.bo"), "500325.BO")
        self.assertEqual(entry.yahoo_symbol(" bajaj-auto "), "BAJAJ-AUTO.NS")
        self.assertIn("/chart/RELIANCE.NS?", entry.chart_path("RELIANCE.NS", "1d", "5m"))
        self.assertNotIn("RELIANCE-NS", entry.chart_path("RELIANCE.NS", "1d", "5m"))

    def test_an_ampersand_is_quoted(self):
        self.assertEqual(entry.yahoo_symbol("m&m"), "M&M.NS")
        self.assertIn("/chart/M%26M.NS?range=1d&interval=5m", entry.chart_path("M&M", "1d", "5m"))
        self.assertIn("/chart/BAJAJ-AUTO.NS?", entry.chart_path("BAJAJ-AUTO.NS", "1d", "5m"))


class Network(unittest.TestCase):
    """Yahoo is never called: _open_url and _sleep are swapped for fakes."""

    def setUp(self):
        self.calls, self.sleeps = [], []
        self._open, self._sleep = entry._open_url, entry._sleep
        entry._sleep = lambda s: self.sleeps.append(s)
        with open(HCL) as fh:
            self.body = fh.read()

    def tearDown(self):
        entry._open_url, entry._sleep = self._open, self._sleep

    def answers(self, *codes):
        seq = list(codes)

        def fake(url, timeout=20):
            self.calls.append(url)
            code = seq.pop(0)
            if code == 200:
                return self.body
            raise urllib.error.HTTPError(url, code, "x", {}, io.BytesIO(b'{"chart":{"result":null,'
                                                                           b'"error":{"description":"No data found"}}}'))
        entry._open_url = fake

    def test_url_and_429_retry_once_after_a_pause(self):
        self.answers(429, 200)
        c = entry.get_chart("HCLTECH", "5m", datetime.date(2026, 11, 13), today=datetime.date(2026, 11, 13))
        self.assertEqual(len(c["bars"]), 20)
        self.assertEqual(self.calls, ["https://query2.finance.yahoo.com/v8/finance/chart/HCLTECH.NS?range=1d&interval=5m"] * 2)
        self.assertEqual(self.sleeps, [entry.BACKOFF])

    def test_429_twice_falls_back_to_query1(self):
        self.answers(429, 429, 200)
        entry.get_chart("HCLTECH.NS", "5m", datetime.date(2026, 11, 13), today=datetime.date(2026, 11, 13))
        self.assertEqual([u.split("/")[2] for u in self.calls],
                         ["query2.finance.yahoo.com", "query2.finance.yahoo.com", "query1.finance.yahoo.com"])

    def test_5xx_falls_back_without_waiting(self):
        self.answers(503, 200)
        entry.get_chart("HCLTECH.NS", "5m", datetime.date(2026, 11, 13), today=datetime.date(2026, 11, 13))
        self.assertEqual(self.sleeps, [])
        self.assertIn("query1", self.calls[1])

    def test_still_busy_is_one_plain_error(self):
        self.answers(429, 429, 429, 429)
        code, out, err = run(["check", "HCLTECH", "--now", "2026-11-13 09:35", "--source", "yahoo"])
        self.assertEqual(code, 1)
        self.assertIn("HTTP 429", err)
        self.assertNotIn("Traceback", err)

    def test_unknown_ticker_404(self):
        self.answers(404)
        with self.assertRaises(entry.EntryError) as cm:
            entry.get_chart("ZZZZ", "5m", datetime.date(2026, 11, 13), today=datetime.date(2026, 11, 13))
        self.assertIn("No data found", str(cm.exception))
        self.assertIn("/chart/ZZZZ.NS?", self.calls[0])

    def test_ranges_for_past_sessions(self):
        today = datetime.date(2026, 11, 16)
        self.assertEqual(entry.chart_range(today, today, "5m"), "1d")
        self.assertEqual(entry.chart_range(datetime.date(2026, 11, 13), today, "5m"), "5d")
        self.assertEqual(entry.chart_range(datetime.date(2026, 10, 27), today, "5m"), "1mo")
        self.assertEqual(entry.chart_range(datetime.date(2026, 9, 28), today, "5m"), "60d")
        with self.assertRaises(entry.EntryError):
            entry.chart_range(datetime.date(2026, 10, 27), today, "1m")


def live_provider(d, lag_until=None, calls=None):
    """Bars the way Yahoo serves them at `now`: closed bars final, the in-progress bar
    showing a spike to 1382.00 (above the high, then it closes under), plus a live tick.
    lag_until: before this UTC time Yahoo's last trade lags 30 seconds behind."""
    base = chart(d)

    def provider(now):
        if calls is not None:
            calls.append(now)
        nts = entry.ts_of(now)
        lagging = lag_until is not None and now < lag_until
        data_ts = nts - 30 if lagging else nts
        bars = []
        for b in base["bars"]:
            if b["t"] % 300 or b["t"] > data_ts:
                continue
            b = dict(b)
            if b["t"] + 300 > data_ts:
                b["c"], b["h"] = 1382.00, max(b["h"], 1382.00)
            bars.append(b)
        if data_ts % 300:
            bars.append({"t": data_ts, "o": 1382.0, "h": 1382.0, "l": 1382.0, "c": 1382.0, "v": 0})
        return {"symbol": "HCLTECH.NS", "meta": {}, "bars": bars, "prev_close": 1380.8, "data_time": data_ts}
    return provider


class Watch(unittest.TestCase):
    OPTS = {"setup": "orb", "or_minutes": 15, "interval": "5m", "level": None, "min_volume_x": None, "cfg": None}

    def loop(self, provider, start, opts=None, **kw):
        clock = entry.SimClock(ist(start))
        lines, fired = [], []
        o = dict(self.OPTS, **(opts or {}))
        code, res = entry.watch_loop(provider, clock.now, clock.sleep, lines.append, o,
                                     on_trigger=lambda r, now: fired.append((r, now)), **kw)
        return code, res, lines, fired, clock

    def test_fires_on_the_first_closed_bar_not_the_spike_in_progress(self):
        calls = []
        code, res, lines, fired, clock = self.loop(live_provider(doc(), calls=calls), "2026-11-13 09:27", every=60)
        self.assertEqual(code, 0)
        self.assertEqual(len(fired), 1)
        self.assertEqual(fired[0][0]["trigger"]["time"], "9:35 AM")
        self.assertEqual(fired[0][0]["trigger"]["price"], 1384.60)
        # it looked at 9:27 (9:25 bar spiking to 1382 in progress) and at 9:30:02 (that bar closed 1378.60)
        self.assertEqual([entry.to_ist(c).strftime("%H:%M:%S") for c in calls], ["09:27:00", "09:30:02", "09:35:02"])
        text = "\n".join(lines)
        self.assertIn(" 9:25 bar  closed Rs 1378.60  opening range set: high Rs 1381.00, low Rs 1373.80", text)
        self.assertIn(" 9:30 bar  closed Rs 1384.60  TRIGGERED", text)
        self.assertEqual(text.count("TRIGGERED"), 1)

    def test_waits_for_yahoo_to_catch_up(self):
        lag = ist("2026-11-13 09:35:30")
        calls = []
        code, res, lines, fired, clock = self.loop(live_provider(doc(), lag_until=lag, calls=calls),
                                                   "2026-11-13 09:32", every=30)
        self.assertEqual(code, 0)
        times = [entry.to_ist(c).strftime("%H:%M:%S") for c in calls]
        self.assertEqual(times, ["09:32:00", "09:35:02", "09:35:32"])   # 9:35:02: Yahoo still at 9:34:32
        self.assertEqual(fired[0][0]["trigger"]["time"], "9:35 AM")

    def test_from_before_the_open_prints_the_range_bar_by_bar(self):
        code, res, lines, fired, clock = self.loop(live_provider(doc()), "2026-11-13 09:00", every=30)
        self.assertEqual(code, 0)
        text = "\n".join(lines)
        self.assertIn("not open yet", lines[0])
        self.assertIn("09:00 IST", lines[0])
        self.assertIn(" 9:25 bar  closed Rs 1378.60  opening range set: high Rs 1381.00, low Rs 1373.80", text)
        self.assertEqual(sum(1 for x in lines if " bar  closed " in x), 4)    # 9:15 ... 9:30, one line each

    def test_a_computer_that_dozes_off_catches_up_when_it_wakes(self):
        class Dozing(entry.SimClock):
            naps = 0

            def sleep(self, seconds):
                entry.SimClock.sleep(self, seconds)
                self.naps += 1
                if self.naps == 3:                      # the laptop sleeps for 17 minutes mid-wait
                    self.t += datetime.timedelta(minutes=17)
        clock = Dozing(ist("2026-11-13 09:46"))
        calls, lines = [], []
        code, res = entry.watch_loop(live_provider(doc(), calls=calls), clock.now, clock.sleep, lines.append,
                                     dict(self.OPTS, or_minutes=30), every=30)
        self.assertEqual(code, 0)
        times = [entry.to_ist(c).strftime("%H:%M:%S") for c in calls]
        self.assertEqual(times[:2], ["09:46:00", "10:04:30"])   # straight after waking, not a long sleep later
        text = "\n".join(lines)
        for start in (" 9:45", " 9:50", " 9:55", "10:00"):
            self.assertIn(start + " bar  closed", text)          # the bars it slept through, one line each
        self.assertEqual(res["trigger"]["time"], "10:10 AM")

    def test_expires_and_until(self):
        code, res, lines, fired, clock = self.loop(live_provider(no_breakout()), "2026-11-13 14:30", every=300)
        self.assertEqual(code, 1)
        self.assertEqual(res["status"], "expired")
        self.assertEqual(fired, [])
        self.assertEqual(entry.to_ist(clock.now()).strftime("%H:%M"), "15:00")
        until = DT(2026, 11, 13, 11, 0)
        code, res, lines, fired, clock = self.loop(live_provider(no_breakout()), "2026-11-13 10:30", every=300,
                                                   until=until)
        self.assertEqual(code, 1)
        self.assertIn("--until 11:00", lines[-1])

    def test_closed_day_and_repeated_errors(self):
        code, _, lines, _, _ = self.loop(live_provider(doc()), "2026-11-14 10:00")
        self.assertEqual(code, 1)
        self.assertIn("weekend", lines[0])
        code, _, lines, _, _ = self.loop(live_provider(doc()), "2026-11-10 10:00")
        self.assertIn("Diwali", lines[0])

        def broken(now):
            raise entry.EntryError("Yahoo did not answer")
        code, _, lines, _, _ = self.loop(broken, "2026-11-13 10:00", every=30)
        self.assertEqual(code, 1)
        self.assertIn("Stopping after 5 failed reads", lines[-1])


class Cli(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.cwd = os.getcwd()
        os.chdir(self.d)

    def tearDown(self):
        os.chdir(self.cwd)
        shutil.rmtree(self.d)

    def test_check_write_is_the_contract_shape(self):
        code, text, _ = run(["check", "HCLTECH", "--offline", HCL, "--now", "2026-11-13 09:35", "--write"])
        self.assertEqual(code, 0)
        self.assertIn("TRIGGERED 9:35 AM at Rs 1384.60", text)
        self.assertIn("/trader-exit", text)
        with open(os.path.join("trader", "entry.json")) as fh:
            e = json.load(fh)
        want = {"created_by": "trader-entry", "symbol": "HCLTECH.NS", "setup": "orb", "side": "buy",
                "date": "2026-11-13", "status": "triggered", "time": "9:35 AM", "bar_start": "09:30",
                "bar_index": 3, "price": 1384.6, "level": 1381.0, "interval": "5m",
                "opening_range": {"high": 1381.0, "low": 1373.8, "minutes": 15},
                "source": "yahoo", "checked_at": "2026-11-13T04:05:00Z"}
        for k, v in want.items():
            self.assertEqual(e[k], v, k)

    def test_the_entry_file_carries_the_previous_close_for_trader_exit(self):
        # Yahoo's chart has it (1380.8), and trader-exit's price-band warning reads prev_close from entry.json
        run(["check", "HCLTECH", "--offline", HCL, "--now", "2026-11-13 09:35", "--write"])
        with open(os.path.join("trader", "entry.json")) as fh:
            self.assertEqual(json.load(fh)["prev_close"], 1380.8)
        run(["watch", "HCLTECH", "--offline", HCL, "--now", "2026-11-13 09:20", "--every", "30", "--out", "w.json"])
        with open("w.json") as fh:
            self.assertEqual(json.load(fh)["prev_close"], 1380.8)

    def test_check_waiting_json_and_exit_codes(self):
        code, text, _ = run(["check", "HCLTECH", "--offline", HCL, "--now", "2026-11-13 09:34", "--json"])
        self.assertEqual(code, 1)
        r = json.loads(text)
        self.assertEqual(r["status"], "waiting")
        self.assertNotIn("_bars", r)
        code, text, _ = run(["check", "HCLTECH", "--offline", HCL, "--now", "2026-11-13 09:34", "--write", "e.json"])
        with open("e.json") as fh:
            self.assertEqual(json.load(fh)["status"], "waiting")
        self.assertIn("still forming", text)

    def test_offline_gz_folder_and_mismatch(self):
        os.mkdir("charts")
        with open(HCL, "rb") as src, gzip.open(os.path.join("charts", "HCLTECH.NS.json.gz"), "wb") as dst:
            dst.write(src.read())
        code, text, _ = run(["check", "hcltech", "--offline", "charts", "--now", "2026-11-13 09:35"])
        self.assertEqual(code, 0)
        code, _, err = run(["check", "INFY", "--offline", HCL])
        self.assertEqual(code, 1)
        self.assertIn("holds HCLTECH.NS, not INFY.NS", err)

    def test_longs_only_and_flag_errors(self):
        code, _, err = run(["check", "HCLTECH", "--offline", HCL, "--side", "short"])
        self.assertEqual(code, 1)
        self.assertIn("longs only", err)
        code, _, err = run(["check", "HCLTECH", "--offline", HCL, "--level", "1300"])
        self.assertIn("--level is for --setup level", err)
        code, _, err = run(["check", "HCLTECH", "--offline", HCL, "--setup", "level"])
        self.assertIn("needs --level", err)

    def test_config_is_read(self):
        os.mkdir("trader")
        with open(os.path.join("trader", "config.json"), "w") as fh:
            json.dump({"no_entries_after": "09:34"}, fh)
        code, text, _ = run(["check", "HCLTECH", "--offline", HCL, "--now", "2026-11-13 09:35"])
        self.assertEqual(code, 1)
        self.assertIn("EXPIRED", text)
        with open(os.path.join("trader", "config.json"), "w") as fh:
            fh.write("{nope")
        code, _, err = run(["check", "HCLTECH", "--offline", HCL])
        self.assertIn("not valid JSON", err)

    def test_watch_replays_the_file_and_writes_the_entry(self):
        code, text, _ = run(["watch", "HCLTECH", "--offline", HCL, "--now", "2026-11-13 09:20", "--every", "30"])
        self.assertEqual(code, 0)
        self.assertIn(" 9:30 bar  closed Rs 1384.60  TRIGGERED", text)
        with open(os.path.join("trader", "entry.json")) as fh:
            self.assertEqual(json.load(fh)["bar_index"], 3)
        code, text, _ = run(["watch", "HCLTECH", "--offline", HCL, "--now", "2026-11-13 09:20", "--until", "09:30",
                             "--out", "x.json"])
        self.assertEqual(code, 1)
        self.assertFalse(os.path.exists("x.json"))

    def test_watchlist(self):
        os.mkdir("charts")
        shutil.copy(HCL, os.path.join("charts", "HCLTECH.NS.json"))
        shutil.copy(DEMO, os.path.join("charts", "DEMO.NS.json"))
        os.mkdir("trader")
        with open(os.path.join("trader", "watchlist.json"), "w") as fh:
            json.dump({"created_by": "trader-scanner", "hits": [
                {"symbol": "HCLTECH.NS", "setups": ["orb"], "or_high": 1381.0, "or_low": 1373.8},
                {"symbol": "ZZZZ.NS", "setups": ["orb"]}, {"symbol": "DEMO", "setups": ["orb"]}]}, fh)
        code, text, _ = run(["watchlist", "--offline", "charts", "--now", "2026-11-13 09:35"])
        self.assertEqual(code, 0)
        rows = text.splitlines()
        self.assertEqual(rows[1].split(), ["HCLTECH.NS", "triggered", "9:35", "AM", "1384.60", "1381.00",
                                           "1384.60", "+0.26%"])
        self.assertIn("ZZZZ.NS         error: no offline file", rows[2])
        self.assertIn("DEMO.NS         error: DEMO.NS has 1m bars", rows[3])
        self.assertIn("1 of 3 triggered", text)
        code, text, _ = run(["watchlist", "--offline", "charts", "--now", "2026-11-13 09:34", "--json"])
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(text)[0]["result"]["status"], "waiting")
        code, _, err = run(["watchlist", "--watchlist", "missing.json"])
        self.assertIn("run /trader-scanner first", err)


class SkillDoc(unittest.TestCase):
    def test_skill_md(self):
        with open(os.path.join(ROOT, "trader-entry", "SKILL.md"), encoding="utf-8") as fh:
            text = fh.read()
        with open(os.path.join(ROOT, "trader-risk", "SKILL.md"), encoding="utf-8") as fh:
            risk = fh.read()
        self.assertTrue(text.startswith("---\nname: trader-entry\n"))
        self.assertGreater(len(text.splitlines()), 60)
        self.assertEqual(text[text.index("## Safety"):], risk[risk.index("## Safety"):])
        low = " ".join(text.lower().split())
        for must in ("bar by bar", "can lag", "day trading loses most people money", "/trader-exit", "longs only",
                     "in the background", "/loop", "nothing was placed", "9:35 am", "rs 1384.60", "bar 3",
                     "hcltech.ns", "ist", "9:15"):
            self.assertIn(must, low)
        for never in (chr(0x2014), "tick " + "by tick", "real " + "time", "pro" + "fit", "new york", "nyse"):
            self.assertNotIn(never, low)


if __name__ == "__main__":
    unittest.main()
