"""fyers.py (the Fyers login, quotes and candles) and the Fyers-then-Yahoo feeds
in trader-entry and trader-alerts.

No test talks to Fyers, and none falls back to Yahoo: Fyers is the only live
source, and Yahoo is read only when a test asks for it. The answers below are the EXAMPLE answers printed in the
Fyers API v3 docs (fyers.in/api-docs, read 2026-11-15), not market data, and the
candles are the real HCLTECH bars of Fri 13 Nov 2026 from the Yahoo fixture,
rewritten in the [epoch, open, high, low, close, volume] shape the docs give.
They stand in until a live Fyers answer can be saved after a real login.
"""

import datetime
import hashlib
import io
import json
import os
import shutil
import tempfile
import unittest
import urllib.error
from contextlib import redirect_stderr

from _load import load, FIX, ROOT

fyers = load("trader-alerts", "fyers")
entry = load("trader-entry", "entry")
alerts = load("trader-alerts", "alerts")

HCL = os.path.join(FIX, "trader-entry", "HCLTECH-2026-11-13-5m.json")
QDIR = os.path.join(FIX, "trader-alerts")
UTC = datetime.datetime

# the Quotes example in the Fyers docs (the POST one: the GET one has a stray comma)
DOCS_QUOTES = {"s": "ok", "code": 200, "message": "", "d": [{"n": "NSE:SBIN-EQ", "s": "ok", "v": {
    "ch": 1.7, "chp": 0.4, "lp": 426.9, "spread": 0.05, "ask": 426.9, "bid": 426.85, "open_price": 430.5,
    "high_price": 433.65, "low_price": 423.6, "prev_close_price": 425.2, "atp": 428.07, "imbalance": -2969,
    "mkt_imbalance": 32522, "reference_price": 427.25, "indicative_price": 426.9, "volume": 38977242,
    "short_name": "SBIN-EQ", "exchange": "NSE", "description": "NSE:SBIN-EQ", "original_name": "NSE:SBIN-EQ",
    "symbol": "NSE:SBIN-EQ", "fyToken": "10100000003045", "tt": "1622160000"}}]}


def hcl_candles():
    """The Yahoo fixture's HCLTECH bars as Fyers candles (the live tick dropped)."""
    with open(HCL) as fh:
        r = json.load(fh)["chart"]["result"][0]
    q = r["indicators"]["quote"][0]
    out = []
    for i, t in enumerate(r["timestamp"]):
        if t % 300 or q["close"][i] is None:
            continue
        out.append([t, q["open"][i], q["high"][i], q["low"][i], q["close"][i], q["volume"][i] or 0])
    return out


class Resp(object):
    def __init__(self, text):
        self.text = text

    def read(self):
        return self.text.encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FakeFyers(object):
    """Stands in for urlopen: records each request, answers from a list."""

    def __init__(self, answers):
        self.answers = list(answers)
        self.calls = []

    def urlopen(self, req, timeout=None):
        self.calls.append((req.get_method(), req.full_url, dict(req.header_items()),
                           req.data.decode("utf-8") if req.data else None))
        code, body = self.answers.pop(0)
        text = body if isinstance(body, str) else json.dumps(body)
        if code != 200:
            raise urllib.error.HTTPError(req.full_url, code, "x", {}, io.BytesIO(text.encode("utf-8")))
        return Resp(text)


class Home(unittest.TestCase):
    """Each test gets its own empty token folder and a fake network."""

    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="dti-fyers-")
        self.old_home = os.environ.get("DAY_TRADER_INDIA_HOME")
        os.environ["DAY_TRADER_INDIA_HOME"] = self.home
        self.saved = (fyers._urlopen, fyers._sleep)
        self.sleeps = []
        fyers._sleep = self.sleeps.append

    def tearDown(self):
        fyers._urlopen, fyers._sleep = self.saved
        os.environ["DAY_TRADER_INDIA_HOME"] = self.old_home
        os.environ.pop("FYERS_APP_ID", None)
        shutil.rmtree(self.home, ignore_errors=True)

    def net(self, answers):
        f = FakeFyers(answers)
        fyers._urlopen = f.urlopen
        return f

    def login(self, at=UTC(2026, 11, 13, 2, 0)):   # 7:30 AM IST
        fyers.save_token("APP-100", "TOKEN", at)


class Copies(unittest.TestCase):
    def test_the_copies_are_the_same_file(self):
        with open(os.path.join(ROOT, "trader-alerts", "fyers.py"), "rb") as fh:
            main = fh.read()
        for other in ("trader-entry", "trader-scanner"):
            with open(os.path.join(ROOT, other, "fyers.py"), "rb") as fh:
                self.assertEqual(fh.read(), main, "run: python scripts/sync_fyers.py (it copies trader-alerts/fyers.py over %s/fyers.py)" % other)

    def test_it_reads_prices_and_nothing_else(self):
        with open(os.path.join(ROOT, "trader-alerts", "fyers.py"), encoding="utf-8") as fh:
            src = fh.read().lower()
        for never in ("/orders", "place_order", "/funds", "/holdings", "/positions", "/tradebook",
                      "modify_order", "cancel_order", "exit_position"):
            self.assertNotIn(never, src, never)
        self.assertEqual(fyers.API, "https://api-t1.fyers.in")
        self.assertEqual((fyers.QUOTES_URL, fyers.HISTORY_URL),
                         ("https://api-t1.fyers.in/data/quotes", "https://api-t1.fyers.in/data/history"))

    def test_the_token_lives_outside_the_repo(self):
        old = os.environ.pop("DAY_TRADER_INDIA_HOME")
        try:
            self.assertEqual(fyers.home(), os.path.join(os.path.expanduser("~"), ".day-trader-india"))
        finally:
            os.environ["DAY_TRADER_INDIA_HOME"] = old
        self.assertFalse(os.path.abspath(fyers.home()).startswith(ROOT))


class Symbols(unittest.TestCase):
    def test_nse_symbols_in_fyers_form_and_back(self):
        self.assertEqual(fyers.fyers_symbol("hcltech"), "NSE:HCLTECH-EQ")
        self.assertEqual(fyers.fyers_symbol("HCLTECH.NS"), "NSE:HCLTECH-EQ")
        self.assertEqual(fyers.fyers_symbol("m&m.ns"), "NSE:M&M-EQ")
        self.assertEqual(fyers.fyers_symbol("BAJAJ-AUTO"), "NSE:BAJAJ-AUTO-EQ")
        self.assertEqual(fyers.fyers_symbol("NSE:SBIN-EQ"), "NSE:SBIN-EQ")
        self.assertEqual(fyers.pack_symbol("NSE:BAJAJ-AUTO-EQ"), "BAJAJ-AUTO.NS")
        self.assertEqual(fyers.pack_symbol("NSE:M&M-EQ"), "M&M.NS")
        with self.assertRaises(fyers.Unavailable):
            fyers.fyers_symbol("500325.BO")

    def test_urls_encode_the_ampersand(self):
        u = fyers.quotes_url(["NSE:SBIN-EQ", "NSE:M&M-EQ"])
        self.assertEqual(u, "https://api-t1.fyers.in/data/quotes?symbols=NSE:SBIN-EQ,NSE:M%26M-EQ")
        h = fyers.history_url("NSE:HCLTECH-EQ", "5m", datetime.date(2026, 11, 13))
        self.assertEqual(h, "https://api-t1.fyers.in/data/history?symbol=NSE:HCLTECH-EQ&resolution=5"
                            "&date_format=1&range_from=2026-11-13&range_to=2026-11-13")
        self.assertIn("resolution=1&", fyers.history_url("NSE:HCLTECH-EQ", "1m", datetime.date(2026, 11, 13)))


class Login(Home):
    def test_login_url_and_hash(self):
        u = fyers.login_url("APP-100", "http://127.0.0.1:8765/", "st8")
        self.assertTrue(u.startswith("https://api-t1.fyers.in/api/v3/generate-authcode?"))
        for part in ("client_id=APP-100", "redirect_uri=http%3A%2F%2F127.0.0.1%3A8765%2F",
                     "response_type=code", "state=st8"):
            self.assertIn(part, u)
        self.assertEqual(fyers.app_id_hash("APP-100", "SECRET"),
                         hashlib.sha256(b"APP-100:SECRET").hexdigest())

    def test_the_auth_code_and_its_state(self):
        back = "http://127.0.0.1:8765/?s=ok&code=200&auth_code=AUTH.CODE-1&state=st8"
        self.assertEqual(fyers.auth_code_from(back, "st8"), "AUTH.CODE-1")
        self.assertEqual(fyers.auth_code_from("s=ok&auth_code=AUTH&state=st8", "st8"), "AUTH")
        self.assertEqual(fyers.auth_code_from("  AUTH.CODE-2  ", "st8"), "AUTH.CODE-2")    # a bare code
        for bad in ("http://127.0.0.1:8765/?s=ok&auth_code=AUTH&state=other",          # someone else's login
                    "http://127.0.0.1:8765/?s=error&message=bad+pin&state=st8",
                    "https://example.com/landing?x=1", ""):
            with self.assertRaises(fyers.Unavailable):
                fyers.auth_code_from(bad, "st8")

    def test_loopback_redirects_are_caught_by_the_tool(self):
        self.assertEqual(fyers.loopback("http://127.0.0.1:8765/"), ("127.0.0.1", 8765))
        self.assertEqual(fyers.loopback("http://localhost:9000/cb"), ("localhost", 9000))
        self.assertIsNone(fyers.loopback("https://127.0.0.1:8765/"))
        self.assertIsNone(fyers.loopback("http://127.0.0.1/"))
        self.assertIsNone(fyers.loopback("https://trade.fyers.in/api-login/redirect-uri/index.html"))

    def test_exchange_sends_the_hash_never_the_secret(self):
        f = self.net([(200, {"s": "ok", "code": 200, "message": "", "access_token": "TOKEN",
                             "refresh_token": "R"})])
        self.assertEqual(fyers.exchange("APP-100", "SECRET", "AUTH"), "TOKEN")
        method, url, headers, body = f.calls[0]
        self.assertEqual((method, url), ("POST", "https://api-t1.fyers.in/api/v3/validate-authcode"))
        self.assertEqual(json.loads(body), {"grant_type": "authorization_code", "code": "AUTH",
                                            "appIdHash": hashlib.sha256(b"APP-100:SECRET").hexdigest()})
        self.assertNotIn("SECRET", body)
        f = self.net([(400, {"s": "error", "code": -413, "message": "invalid auth code"})])
        with self.assertRaises(fyers.Unavailable) as e:
            fyers.exchange("APP-100", "SECRET", "AUTH")
        self.assertIn("invalid auth code", str(e.exception))

    def test_missing_settings_are_named(self):
        for k in ("FYERS_APP_ID", "FYERS_SECRET_ID", "FYERS_REDIRECT_URI"):
            os.environ.pop(k, None)
        with self.assertRaises(fyers.Unavailable) as e:
            fyers.credentials()
        for k in ("FYERS_APP_ID", "FYERS_SECRET_ID", "FYERS_REDIRECT_URI"):
            self.assertIn(k, str(e.exception))


class Token(Home):
    def test_tokens_expire_at_630_india_time(self):
        # issued 7:30 AM IST: good until 6:30 AM IST the next day (01:00 UTC)
        self.assertEqual(fyers.expiry_after(UTC(2026, 11, 13, 2, 0)), UTC(2026, 11, 14, 1, 0))
        # issued 5:00 AM IST: dead at 6:30 AM the same day
        self.assertEqual(fyers.expiry_after(UTC(2026, 11, 12, 23, 30)), UTC(2026, 11, 13, 1, 0))

    def test_no_login_then_a_login_then_expired(self):
        with self.assertRaises(fyers.Unavailable) as e:
            fyers.token_state(UTC(2026, 11, 13, 4, 0))
        self.assertIn("fyers.py login", str(e.exception))
        self.login()
        self.assertTrue(fyers.has_token(UTC(2026, 11, 13, 4, 0)))
        self.assertEqual(fyers.token_state(UTC(2026, 11, 13, 4, 0))[:2], ("APP-100", "TOKEN"))
        with self.assertRaises(fyers.Unavailable) as e:
            fyers.token_state(UTC(2026, 11, 14, 1, 0))
        self.assertIn("expired at 6:30 AM", str(e.exception))
        os.environ["FYERS_APP_ID"] = "OTHER-100"
        self.assertFalse(fyers.has_token(UTC(2026, 11, 13, 4, 0)))

    def test_logout_deletes_it(self):
        self.login()
        self.assertTrue(fyers.forget_token())
        self.assertFalse(fyers.has_token(UTC(2026, 11, 13, 4, 0)))
        self.assertFalse(fyers.forget_token())


class Quotes(Home):
    NOW = UTC(2026, 11, 13, 4, 30)   # 10:00 AM IST

    def test_the_docs_example_in_the_alerts_shape(self):
        q, errors = fyers.parse_quotes(DOCS_QUOTES, "2026-11-13T04:30:00Z")
        self.assertEqual(errors, [])
        s = q["SBIN.NS"]
        self.assertEqual((s["price"], s["prev_close"], s["open"], s["high"], s["low"], s["source"]),
                         (426.9, 425.2, 430.5, 433.65, 423.6, "fyers"))
        self.assertEqual(s["time"], "2026-11-13T04:30:00Z")

    def test_one_request_for_many_symbols_with_the_header(self):
        self.login()
        two = json.loads(json.dumps(DOCS_QUOTES))
        two["d"].append({"n": "NSE:NOPE-EQ", "s": "error", "v": {"errmsg": "invalid symbol"}})
        f = self.net([(200, two)])
        q, errors = fyers.quotes(["SBIN", "NOPE.NS", "SBIN.NS"], self.NOW)
        self.assertEqual(list(q), ["SBIN.NS"])
        self.assertEqual(len(errors), 1)
        self.assertIn("NOPE.NS", errors[0])
        method, url, headers, _ = f.calls[0]
        self.assertEqual(len(f.calls), 1)
        self.assertEqual(url, "https://api-t1.fyers.in/data/quotes?symbols=NSE:SBIN-EQ,NSE:NOPE-EQ")
        self.assertEqual(headers.get("Authorization"), "APP-100:TOKEN")
        self.assertEqual(headers.get("User-agent"), fyers.UA)

    def test_fifty_symbols_a_request(self):
        self.login()
        f = self.net([(200, {"s": "ok", "code": 200, "d": []})] * 2)
        fyers.quotes(["S%d" % i for i in range(51)], self.NOW)
        self.assertEqual(len(f.calls), 2)
        self.assertEqual(f.calls[0][1].count("NSE:"), 50)

    def test_a_refused_token_is_not_used_again(self):
        for code, body in ((401, {"s": "error", "code": -16, "message": "invalid token"}),
                           (200, {"s": "error", "code": -8, "message": "token expired"})):
            self.login()
            self.net([(code, body)])
            with self.assertRaises(fyers.Unavailable) as e:
                fyers.quotes(["SBIN"], self.NOW)
            self.assertIn("fyers.py login", str(e.exception))
            self.assertFalse(fyers.has_token(self.NOW))

    def test_too_many_requests_stops_fyers_for_the_day(self):
        self.login()
        f = self.net([(429, {"s": "error", "code": -429, "message": "limit"})])
        with self.assertRaises(fyers.Unavailable):
            fyers.quotes(["SBIN"], self.NOW)
        with self.assertRaises(fyers.Unavailable) as e:
            fyers.quotes(["SBIN"], self.NOW + datetime.timedelta(hours=2))
        self.assertIn("not asked again today", str(e.exception))
        self.assertEqual(len(f.calls), 1)
        self.assertTrue(fyers.budget(self.NOW)["stopped"])
        self.assertFalse(fyers.budget(UTC(2026, 11, 14, 4, 0))["stopped"])   # the next India day

    def test_its_own_ceiling_stays_under_the_fyers_limits(self):
        self.assertLess(fyers.PER_MINUTE, 50)
        self.assertLess(fyers.PER_DAY, 5000)
        self.login()
        f = self.net([(200, DOCS_QUOTES)] * 41)
        for i in range(40):
            fyers.quotes(["SBIN"], self.NOW + datetime.timedelta(seconds=i))
        with self.assertRaises(fyers.Unavailable) as e:
            fyers.quotes(["SBIN"], self.NOW + datetime.timedelta(seconds=40))
        self.assertIn("this minute", str(e.exception))
        self.assertEqual(len(f.calls), 40)
        fyers.quotes(["SBIN"], self.NOW + datetime.timedelta(seconds=61))      # the minute has passed
        self.assertEqual(len(f.calls), 41)

    def test_no_network_is_unavailable(self):
        self.login()

        def down(req, timeout=None):
            raise urllib.error.URLError("no route")
        fyers._urlopen = down
        with self.assertRaises(fyers.Unavailable):
            fyers.quotes(["SBIN"], self.NOW)


class Candles(Home):
    DAY = datetime.date(2026, 11, 13)

    def chart(self, candles, now, s="ok"):
        return fyers.parse_history({"s": s, "candles": candles}, "HCLTECH.NS", "5m", self.DAY, now)

    def test_fyers_candles_give_the_same_trigger_as_yahoo(self):
        now = entry.parse_now("2026-11-13 09:35")
        live = [c for c in hcl_candles() if c[0] < fyers._ts(now)]   # what Fyers would have at 9:35
        ch = self.chart(live, now)
        res = entry.evaluate(ch, now)
        self.assertEqual(res["source"], "fyers")
        self.assertEqual(res["status"], "triggered")
        self.assertEqual((res["trigger"]["time"], res["trigger"]["price"], res["trigger"]["bar_index"]),
                         ("9:35 AM", 1384.6, 3))
        self.assertEqual((res["opening_range"]["high"], res["opening_range"]["low"]), (1381.0, 1373.8))
        self.assertIn("(Fyers, your own login)", entry.describe(res)[0])
        self.assertEqual(entry.entry_doc(res, now)["source"], "fyers")

    def test_a_forming_bar_does_not_count(self):
        now = entry.parse_now("2026-11-13 09:33")
        live = [c for c in hcl_candles() if c[0] < fyers._ts(now)]   # the 9:30 bar is still forming
        res = entry.evaluate(self.chart(live, now), now)
        self.assertEqual(res["status"], "waiting")
        self.assertEqual(res["forming"]["bar_start"], "09:30")

    def test_candles_that_do_not_fit_a_session_are_refused(self):
        now = entry.parse_now("2026-11-13 10:00")
        good = [c for c in hcl_candles() if c[0] < fyers._ts(now)]
        off = [list(good[0])]
        off[0][0] += 60                                  # 9:16, not on the 5-minute grid
        late = [list(good[0])]
        late[0][0] = int(fyers._ts(now)) + 3600          # an hour in the future
        outside = [list(good[0])]
        outside[0][0] -= 86400                           # the day before
        for bad in (off, late, outside, [["x", 1, 2, 3, 4, 5]], [[1, 2, 3]]):
            with self.assertRaises(fyers.Unavailable):
                self.chart(bad, now)
        self.assertEqual(self.chart([], now, s="no_data")["bars"], [])
        with self.assertRaises(fyers.Unavailable):
            fyers.parse_history({"s": "error", "code": -300, "message": "bad symbol"}, "X.NS", "5m", self.DAY, now)


class Pacing(Home):
    def test_a_long_job_waits_for_the_next_minute(self):
        # a clock that moves only when the tool sleeps, plus a tenth of a second a request
        clock = [UTC(2026, 11, 13, 4, 30)]
        saved = fyers.utc_now

        def sleep(x):
            self.sleeps.append(x)
            clock[0] += datetime.timedelta(seconds=x)
        fyers.utc_now = lambda: clock[0]
        fyers._sleep = sleep
        try:
            self.login(clock[0])
            f = self.net([(200, {"s": "ok", "candles": []})] * 50)
            for i in range(50):
                fyers.history("SBIN", "5m", datetime.date(2026, 11, 13), wait=True)
                clock[0] += datetime.timedelta(seconds=0.1)
        finally:
            fyers.utc_now = saved
        self.assertEqual(len(f.calls), 50)          # the Nifty 50: every one asked, none refused
        waits = [x for x in self.sleeps if x > 1]
        self.assertEqual(len(waits), 1)             # one wait, at the 41st request
        self.assertTrue(10 < waits[0] <= 61, waits)
        gaps = [x for x in self.sleeps if x <= 1]
        self.assertTrue(gaps and all(x <= fyers.MIN_GAP for x in gaps))      # never closer than MIN_GAP
        self.assertGreaterEqual(fyers.MIN_GAP, 1.0)                          # Fyers 429'd at 0.3 s apart
        self.assertLess((clock[0] - UTC(2026, 11, 13, 4, 30)).total_seconds(), 120)

    def test_without_wait_a_full_minute_is_refused(self):
        self.login()
        now = UTC(2026, 11, 13, 4, 30)
        self.net([(200, {"s": "ok", "candles": []})] * 41)
        for i in range(40):
            fyers.history("SBIN", "5m", datetime.date(2026, 11, 13), now)
        with self.assertRaises(fyers.Unavailable):
            fyers.history("SBIN", "5m", datetime.date(2026, 11, 13), now)


class SlotReservation(Home):
    """The counter records when a request is SENT, the lock is held only to reserve the slot, and
    budget() survives a read that lands mid-swap."""

    def test_requests_are_never_closer_than_min_gap_when_sent(self):
        # each request takes 0.3 s to come back. Recording the time a request was ASKED for let the
        # next one leave about 0.3 s after it (the spacing Fyers answered 429 to); the send slot keeps the gap.
        clock = [UTC(2026, 11, 13, 4, 30)]
        saved = fyers.utc_now
        sent = []

        def sleep(x):
            self.sleeps.append(x)
            clock[0] += datetime.timedelta(seconds=x)
        fyers.utc_now = lambda: clock[0]
        fyers._sleep = sleep
        try:
            for _ in range(8):
                fyers._spend()
                sent.append(fyers._ts(clock[0]))
                clock[0] += datetime.timedelta(seconds=0.3)        # the request itself
        finally:
            fyers.utc_now = saved
        gaps = [b - a for a, b in zip(sent, sent[1:])]
        self.assertEqual(len(gaps), 7)
        self.assertTrue(all(g >= fyers.MIN_GAP - 1e-5 for g in gaps), gaps)

    def test_a_burst_asked_at_the_same_instant_is_spread_one_slot_apart(self):
        now = UTC(2026, 11, 13, 4, 30)
        for _ in range(5):
            fyers._spend(now)
        self.assertEqual([round(x, 3) for x in self.sleeps], [1.0, 2.0, 3.0, 4.0])   # the first goes at once
        doc = fyers._calls(now)
        recent = sorted(doc["recent"])
        self.assertEqual([round(b - a, 3) for a, b in zip(recent, recent[1:])], [1.0] * 4)
        self.assertEqual(doc["count"], 5)

    def test_the_lock_is_not_held_while_waiting_for_a_slot(self):
        now = UTC(2026, 11, 13, 4, 30)
        lock = os.path.join(self.home, "fyers-calls.json.lock")
        held = []
        fyers._sleep = lambda s: held.append(os.path.exists(lock))
        fyers._spend(now)
        fyers._spend(now)
        self.assertEqual(held, [False])             # one wait (the second request), and no lock during it

    def test_budget_retries_a_read_that_lands_mid_swap(self):
        from unittest import mock
        now = UTC(2026, 11, 13, 4, 30)
        for _ in range(3):
            fyers._spend(now)
        real_load = fyers.json.load
        calls = []

        def flaky(fh):
            calls.append(1)
            if len(calls) <= 2:
                raise ValueError("half-written")
            return real_load(fh)
        with mock.patch.object(fyers.json, "load", flaky):
            self.assertEqual(fyers.budget(now)["today"], 3)       # not a false 0
        self.assertEqual(len(calls), 3)
        with mock.patch.object(fyers.json, "load", side_effect=ValueError("always bad")):
            self.assertEqual(fyers.budget(now)["today"], 0)       # gives up after a few tries, no hang

    def test_budget_with_no_file_is_zero_at_once(self):
        from unittest import mock
        with mock.patch.object(fyers.time, "sleep") as slept:
            self.assertEqual(fyers.budget(UTC(2026, 11, 13, 4, 30))["today"], 0)
        slept.assert_not_called()


class EntryFeed(Home):
    """Fyers is the only live source: no login or no answer is an error, never Yahoo."""

    def setUp(self):
        super(EntryFeed, self).setUp()
        self.fy = entry._fyers()
        self.saved_feed = (self.fy.history, entry.get_chart)
        self.saved_more = (self.fy.quotes, entry.utc_now)
        self.yahoo = []

        def yahoo(sym, interval, day=None, offline=None, today=None):
            self.yahoo.append(sym)
            return {"symbol": "HCLTECH.NS", "bars": []}
        entry.get_chart = yahoo

    def tearDown(self):
        self.fy.history, entry.get_chart = self.saved_feed
        self.fy.quotes, entry.utc_now = self.saved_more
        super(EntryFeed, self).tearDown()

    def live_check(self, at, quote=None, extra=()):
        """`entry.py check HCLTECH --write` as a live run at India time `at`, on Fyers bars up to then.
        quote: the previous close the fake Fyers quote gives, or an Unavailable to raise.
        Returns (exit code, entry.json as written, quote requests made, stderr)."""
        now = entry.parse_now(at)
        ch = fyers.parse_history({"s": "ok", "candles": [c for c in hcl_candles() if c[0] < fyers._ts(now)]},
                                 "HCLTECH.NS", "5m", datetime.date(2026, 11, 13), now)
        self.assertIsNone(ch["prev_close"])                  # Fyers' bars carry no previous close
        asked = []

        def quotes(symbols, now_=None):
            asked.append(list(symbols))
            if isinstance(quote, Exception):
                raise quote
            return {"HCLTECH.NS": {"symbol": "HCLTECH.NS", "price": 1384.6, "prev_close": quote}}, []
        self.fy.history = lambda sym, interval, day, now=None: ch
        self.fy.quotes = quotes
        entry.utc_now = lambda: now
        self.login(fyers.utc_now())
        out_path = os.path.join(self.home, "entry.json")
        err = io.StringIO()
        out = io.StringIO()
        from contextlib import redirect_stdout
        with redirect_stdout(out), redirect_stderr(err):
            code = entry.main(["check", "HCLTECH", "--write", out_path, "--config", os.path.join(self.home, "none.json")]
                              + list(extra))
        written = None
        if os.path.exists(out_path):
            with open(out_path, encoding="utf-8") as fh:
                written = json.load(fh)
        return code, written, asked, err.getvalue()

    def test_a_trigger_from_fyers_bars_gets_its_previous_close_from_one_quote(self):
        code, e, asked, _ = self.live_check("2026-11-13 09:35", quote=1380.8)
        self.assertEqual(code, 0)
        self.assertEqual(e["status"], "triggered")
        self.assertEqual(e["prev_close"], 1380.8)
        self.assertEqual(asked, [["HCLTECH.NS"]])             # one quote, for this stock only

    def test_no_quote_is_asked_while_nothing_has_triggered(self):
        code, e, asked, _ = self.live_check("2026-11-13 09:34", quote=1380.8)
        self.assertEqual(code, 1)
        self.assertEqual(e["status"], "waiting")
        self.assertIsNone(e["prev_close"])
        self.assertEqual(asked, [])

    def test_a_failing_quote_does_not_stop_the_entry_being_written(self):
        code, e, asked, err = self.live_check("2026-11-13 09:35", quote=self.fy.Unavailable("Fyers answered HTTP 503"))
        self.assertEqual(code, 0)
        self.assertEqual(e["status"], "triggered")
        self.assertIsNone(e["prev_close"])
        self.assertEqual(len(asked), 1)
        self.assertIn("Could not read the previous close", err)
        self.assertIn("--prev-close", err)
        self.assertEqual(self.yahoo, [])                      # and never a fall back to Yahoo

    def test_a_replay_asks_for_no_quote(self):
        # --now means a replay: today's previous close would belong to another day
        code, e, asked, _ = self.live_check("2026-11-13 09:35", quote=1380.8, extra=["--now", "2026-11-13 09:35"])
        self.assertEqual(code, 0)
        self.assertEqual(asked, [])
        self.assertIsNone(e["prev_close"])

    def test_an_entry_for_another_day_asks_for_no_quote(self):
        now = entry.parse_now("2026-11-13 09:35")
        entry.utc_now = lambda: now + datetime.timedelta(days=3)    # the bars are Friday's, the clock is Monday's
        res = {"status": "triggered", "date": "2026-11-13", "prev_close": None}
        asked = []
        self.fy.quotes = lambda symbols, now_=None: asked.append(symbols) or ({}, [])
        self.login(fyers.utc_now())
        entry.with_prev_close(res, entry.Feed(), "HCLTECH.NS", True)
        self.assertEqual(asked, [])
        self.assertIsNone(res["prev_close"])

    def test_without_a_login_it_stops_and_says_how_to_log_in(self):
        with self.assertRaises(entry.EntryError) as e:
            entry.Feed()
        self.assertIn("no Fyers login today", str(e.exception))
        self.assertIn("fyers.py\" login", str(e.exception))
        self.assertEqual(self.yahoo, [])
        code_out = io.StringIO()
        with redirect_stderr(code_out):
            code = entry.main(["check", "HCLTECH", "--config", os.path.join(self.home, "none.json")])
        self.assertEqual(code, 1)
        self.assertIn("no Fyers login today", code_out.getvalue())
        self.assertEqual(self.yahoo, [])

    def test_fyers_failing_is_an_error_not_yahoo(self):
        self.login(fyers.utc_now())

        def broken(sym, interval, day, now=None):
            raise self.fy.Unavailable("Fyers answered HTTP 503")
        self.fy.history = broken
        feed = entry.Feed()
        self.assertEqual(feed.name(), "fyers")
        for _ in range(2):
            with self.assertRaises(entry.EntryError) as e:
                feed.chart("HCLTECH", "5m", datetime.date(2026, 11, 13))
            self.assertIn("Fyers unavailable (Fyers answered HTTP 503)", str(e.exception))
        self.assertEqual(self.yahoo, [])

    def test_fyers_bars_when_logged_in(self):
        self.login(fyers.utc_now())
        now = entry.parse_now("2026-11-13 09:35")
        ch = fyers.parse_history({"s": "ok", "candles": [c for c in hcl_candles() if c[0] < fyers._ts(now)]},
                                 "HCLTECH.NS", "5m", datetime.date(2026, 11, 13), now)
        self.fy.history = lambda sym, interval, day, now=None: ch
        feed = entry.Feed()
        res = entry.evaluate(feed.chart("HCLTECH", "5m", datetime.date(2026, 11, 13)), now)
        self.assertEqual((res["source"], res["status"], res["trigger"]["price"]), ("fyers", "triggered", 1384.6))
        self.assertEqual(self.yahoo, [])

    def test_yahoo_only_when_asked(self):
        feed = entry.Feed("yahoo")
        self.assertEqual(feed.name(), "yahoo")
        feed.chart("HCLTECH", "5m", datetime.date(2026, 11, 13))
        self.assertEqual(self.yahoo, ["HCLTECH"])

    def test_the_offline_replay_ignores_any_login(self):
        self.login(fyers.utc_now())
        entry.get_chart = self.saved_feed[1]
        err = io.StringIO()
        out = io.StringIO()
        from contextlib import redirect_stdout
        with redirect_stdout(out), redirect_stderr(err):
            code = entry.main(["check", "HCLTECH", "--now", "2026-11-13 09:35", "--offline", HCL,
                               "--config", os.path.join(self.home, "none.json")])
        self.assertEqual(code, 0)
        self.assertIn("(Yahoo, delayed: practice only)", out.getvalue())
        self.assertEqual(err.getvalue(), "")


class AlertsFeed(Home):
    def setUp(self):
        super(AlertsFeed, self).setUp()
        self.fy = alerts._fyers()
        self.saved_feed = (self.fy.quotes, alerts.fetch_yahoo, alerts._sleep)
        alerts._sleep = lambda s: None
        self.yahoo = []

        def yahoo(sym, timeout=20):
            self.yahoo.append(sym)
            with open(os.path.join(QDIR, "yahoo-%s.json" % sym), encoding="utf-8") as fh:
                return fh.read()
        alerts.fetch_yahoo = yahoo

    def tearDown(self):
        self.fy.quotes, alerts.fetch_yahoo, alerts._sleep = self.saved_feed
        super(AlertsFeed, self).tearDown()

    def fyers_gives(self, prices, errors=()):
        def quotes(symbols, now=None):
            return ({s: {"symbol": s, "price": p, "prev_close": None, "time": "2026-11-13T04:30:00Z",
                         "source": "fyers"} for s, p in prices.items()}, list(errors))
        self.fy.quotes = quotes

    def test_without_a_login_no_quote_and_no_yahoo(self):
        q, errors = alerts.get_quotes(["HCLTECH", "ITC"])
        self.assertEqual(q, {})
        self.assertIn("no Fyers login today", errors[0])
        self.assertEqual(self.yahoo, [])

    def test_fyers_quotes_and_what_it_missed_is_an_error(self):
        self.login(fyers.utc_now())
        self.fyers_gives({"HCLTECH.NS": 1380.5}, ["Fyers has no quote for ITC.NS: no price"])
        q, errors = alerts.get_quotes(["HCLTECH", "ITC"])
        self.assertEqual((list(q), q["HCLTECH.NS"]["source"]), (["HCLTECH.NS"], "fyers"))
        self.assertEqual(errors, ["Fyers has no quote for ITC.NS: no price"])
        self.assertEqual(self.yahoo, [])
        self.assertEqual(alerts.used_source(q), "fyers")

    def test_fyers_down_is_an_error(self):
        self.login(fyers.utc_now())

        def down(symbols, now=None):
            raise self.fy.Unavailable("could not reach Fyers: no route")
        self.fy.quotes = down
        q, errors = alerts.get_quotes(["HCLTECH"])
        self.assertEqual(q, {})
        self.assertEqual(errors, ["Fyers unavailable (could not reach Fyers: no route)"])
        self.assertEqual(self.yahoo, [])

    def test_yahoo_only_when_asked(self):
        q, errors = alerts.get_quotes(["HCLTECH"], "yahoo")
        self.assertEqual((q["HCLTECH.NS"]["source"], errors), ("yahoo", []))
        self.assertEqual(alerts.used_source(q), "yahoo")

    def test_prices_json_says_where_each_price_came_from(self):
        self.login(fyers.utc_now())
        self.fyers_gives({"HCLTECH.NS": 1380.5})
        q, _ = alerts.get_quotes(["HCLTECH"])
        path = os.path.join(self.home, "prices.json")
        doc = alerts.write_prices(path, q, UTC(2026, 11, 13, 4, 30), alerts.used_source(q))
        self.assertEqual((doc["source"], doc["detail"]["HCLTECH.NS"]["source"]), ("fyers", "fyers"))
        self.assertEqual(doc["prices"]["HCLTECH.NS"], 1380.5)

    def test_a_time_alert_needs_no_login(self):
        rules = os.path.join(self.home, "alerts.json")
        out = io.StringIO()
        from contextlib import redirect_stdout
        with redirect_stdout(out), redirect_stderr(io.StringIO()):
            alerts.main(["add", "--rules", rules, "--state", os.path.join(self.home, "st.json"),
                         "--at", "15:15", "--label", "flat by 15:15", "--date", "2026-11-13"])
            code = alerts.main(["check", "--rules", rules, "--state", os.path.join(self.home, "st.json"),
                                "--prices-out", os.path.join(self.home, "p.json"), "--now", "2026-11-13 15:15"])
        self.assertEqual(code, 0)
        self.assertIn("ALERT", out.getvalue())


class ScannerFeed(Home):
    """The 9:35 opening-range scan reads Fyers: one request per stock, real highs and lows."""

    def setUp(self):
        super(ScannerFeed, self).setUp()
        self.scan = load("trader-scanner", "scan")
        self.fy = self.scan._fyers()
        self.saved_hist = self.fy.history
        self.asked = []

    def tearDown(self):
        self.fy.history = self.saved_hist
        super(ScannerFeed, self).tearDown()

    def run_orb(self, *extra):
        out, err = io.StringIO(), io.StringIO()
        from contextlib import redirect_stdout
        with redirect_stdout(out), redirect_stderr(err):
            code = self.scan.main(["orb", "--symbols", "HCLTECH,ITC", "--now", "2026-11-13 09:40",
                                   "--no-write", "--config", os.path.join(self.home, "none.json")] + list(extra))
        return code, out.getvalue(), err.getvalue()

    def test_without_a_login_the_scan_stops(self):
        code, out, err = self.run_orb()
        self.assertEqual(code, 1)
        self.assertIn("no Fyers login today", err)

    def test_the_hcltech_breakout_from_fyers_candles(self):
        self.login(fyers.utc_now())
        now = entry.parse_now("2026-11-13 09:40")

        def hist(sym, interval, day, now_=None, wait=False):
            self.asked.append((sym, interval, day.isoformat(), wait))
            if sym == "ITC.NS":
                return {"symbol": "ITC.NS", "bars": []}
            return fyers.parse_history({"s": "ok", "candles": [c for c in hcl_candles() if c[0] < fyers._ts(now)]},
                                       "HCLTECH.NS", "5m", day, now)
        self.fy.history = hist
        code, out, err = self.run_orb()
        self.assertEqual(code, 0, err)
        self.assertEqual(self.asked, [("HCLTECH.NS", "5m", "2026-11-13", True), ("ITC.NS", "5m", "2026-11-13", True)])
        self.assertIn("5-minute bars, Fyers (your own login).", out)
        self.assertIn("9:35 AM  HCLTECH.NS", out)
        self.assertIn("1,373.80 to 1,381.00", out)

    def test_a_lost_login_stops_the_scan(self):
        self.login(fyers.utc_now())

        def hist(sym, interval, day, now_=None, wait=False):
            fyers.forget_token()
            raise self.fy.Unavailable("Fyers refused the login (HTTP 401, code -16)")
        self.fy.history = hist
        code, out, err = self.run_orb()
        self.assertEqual(code, 1)
        self.assertIn("the scan stopped after 0 of 2 symbols", err)


if __name__ == "__main__":
    unittest.main()
