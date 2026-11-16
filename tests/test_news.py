"""trader-news tests. Fixtures in tests/fixtures/trader-news/, all real answers fetched
Sat Nov 14 2026 (morning, IST):

nse-<SYM>.json       NSE corporate announcements for RELIANCE, HCLTECH and M&M, cut
                     to the records from Nov 1 2026 on (the full answer is the whole
                     filing history, thousands of records).
gnews-<SYM>.xml      Google News RSS, India edition, searched by company name.
yahoo-<SYM>.NS.xml   Yahoo's headline RSS. RELIANCE and HCLTECH came back EMPTY: Yahoo
                     has almost no headlines for NSE symbols, which is why the other
                     two sources are here.
chart-<SYM>.NS.json  Yahoo chart answers (the range=1d quotes from trader-alerts: only
                     the meta block is read).
"""

import datetime as dt
import io
import json
import os
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr

from _load import load, FIX

news = load("trader-news", "news")

NDIR = os.path.join(FIX, "trader-news")
NOW = "2026-11-14 09:00"            # India time
UTC = dt.timezone.utc


def raw(name):
    with open(os.path.join(NDIR, name), "rb") as fh:
        return fh.read()


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = news.main(argv)
    return code, out.getvalue(), err.getvalue()


class Sources(unittest.TestCase):
    def test_nse_announcements(self):
        items, name = news.parse_nse(raw("nse-RELIANCE.json"), "RELIANCE.NS")
        self.assertEqual(name, "Reliance Industries Limited")
        self.assertEqual(len(items), 5)
        first = items[0]
        self.assertEqual(first["id"], "nse:106859406")
        self.assertEqual(first["title"], "Reliance Industries Limited: Analysts/Institutional Investor Meet/Con. "
                                         "Call Updates")
        self.assertEqual(first["time"], dt.datetime(2026, 11, 13, 12, 55, 1, tzinfo=UTC))   # 18:25:01 IST
        self.assertEqual((first["source"], first["kind"], first["tags_nse"], first["important"]),
                         ("NSE", "filing", ["routine"], False))
        self.assertTrue(first["link"].startswith("https://nsearchives.nseindia.com/corporate/"))
        rating = [i for i in items if i["subject"] == "Credit Rating"][0]
        self.assertEqual(rating["tags_nse"], ["rating"])

    def test_an_acquisition_is_flagged(self):
        items, name = news.parse_nse(raw("nse-M&M.json"), "M&M.NS")
        self.assertEqual(name, "Mahindra & Mahindra Limited")
        acq = [i for i in items if i["subject"] == "Acquisition"]
        self.assertEqual(len(acq), 1)
        self.assertEqual((acq[0]["tags_nse"], acq[0]["important"]), (["deal"], True))
        flagged = sorted((i["subject"], i["tags_nse"][0]) for i in items if i["important"])
        self.assertEqual(flagged, [("Acquisition", "deal"), ("Cessation", "people"),
                                   ("Outcome of Board Meeting", "earnings"), ("Outcome of Board Meeting", "earnings"),
                                   ("Outcome of Board Meeting", "earnings")])
        self.assertFalse(any(i["important"] for i in items if i["tags_nse"] == ["routine"]))

    def test_an_access_page_is_unavailable_not_a_crash(self):
        for body in (b"<html><body>Access Denied</body></html>", b'{"error": "x"}', b""):
            with self.assertRaises(news.Unavailable) as cm:
                news.parse_nse(body, "RELIANCE.NS")
            self.assertIn("NSE announcements unavailable", str(cm.exception))

    def test_google_news(self):
        items = news.parse_rss(raw("gnews-RELIANCE.xml"), "RELIANCE.NS", "Google News")
        self.assertEqual(len(items), 64)                    # 65 in the feed, 1 quote page left out
        reuters = [i for i in items if i["publisher"] == "Reuters"][0]
        self.assertEqual(reuters["title"], "India's Reliance plans $4.6 billion coal-to-gas project, document shows")
        self.assertTrue(all(i["id"].startswith("gnews:") for i in items))
        self.assertTrue(any("share price jumps 2.75%" in i["title"] for i in items))   # news, kept

    def test_quote_pages_are_left_out(self):
        items = news.parse_rss(raw("gnews-HCLTECH.xml"), "HCLTECH.NS", "Google News")
        self.assertEqual(len(items), 35)                    # 39 in the feed, 4 quote pages
        for t in ("HCL TECHNOLOGIES SHARE PRICE - ICICI Direct",
                  "HCL Tech Share Price Today, HCL Tech Stock Price Live NSE/BSE Updates - The Economic Times",
                  "HCL Technologies Limited Stock (HCLTECH) - Quote NSE India S.E. - marketscreener.com"):
            self.assertTrue(news.QUOTE_PAGE.search(t), t)
        self.assertFalse(news.QUOTE_PAGE.search("HCL Technologies Share Price Target 2027: 4.2% Upside and Risks"))

    def test_yahoo_has_little_for_nse_symbols(self):
        self.assertEqual(news.parse_rss(raw("yahoo-RELIANCE.NS.xml"), "RELIANCE.NS", "Yahoo Finance"), [])
        self.assertEqual(news.parse_rss(raw("yahoo-HCLTECH.NS.xml"), "HCLTECH.NS", "Yahoo Finance"), [])
        self.assertEqual(len(news.parse_rss(raw("yahoo-M&M.NS.xml"), "M&M.NS", "Yahoo Finance")), 12)

    def test_symbols_times_and_queries(self):
        self.assertEqual((news.nse_symbol("reliance"), news.base("M&M.NS")), ("RELIANCE.NS", "M&M"))
        self.assertEqual(news.parse_ist("2026-11-13 18:25:01"), dt.datetime(2026, 11, 13, 12, 55, 1, tzinfo=UTC))
        self.assertEqual(news.parse_now("2026-11-14 09:00"), dt.datetime(2026, 11, 14, 3, 30, tzinfo=UTC))
        self.assertEqual(news.parse_now("2026-11-14T03:30:00Z"), dt.datetime(2026, 11, 14, 3, 30, tzinfo=UTC))
        self.assertEqual(news.company_query("Reliance Industries Limited", "RELIANCE.NS"),
                         '"Reliance Industries" (share OR shares OR stock OR NSE)')
        # one word is ambiguous on its own ("Trent" brought back an NFL player on 2026-11-15)
        self.assertEqual(news.company_query("Trent Ltd.", "TRENT.NS"),
                         '("Trent Ltd" OR "Trent share" OR "Trent shares" OR "Trent stock")')
        self.assertEqual(news.company_query(None, "HCLTECH.NS"),
                         '("HCLTECH Ltd" OR "HCLTECH share" OR "HCLTECH shares" OR "HCLTECH stock")')

    def test_names_come_from_the_universe_file(self):
        d = tempfile.mkdtemp()
        try:
            p = os.path.join(d, "universe.txt")
            with open(p, "w", encoding="utf-8") as fh:
                fh.write("TRENT.NS|Trent Ltd.\nM&M.NS|Mahindra & Mahindra Ltd.\n")
            self.assertEqual(news.names_from_universe(p),
                             {"TRENT.NS": "Trent Ltd.", "M&M.NS": "Mahindra & Mahindra Ltd."})
            self.assertEqual(news.names_from_universe(os.path.join(d, "none.txt")), {})
        finally:
            shutil.rmtree(d)
        self.assertFalse(hasattr(news, "sec_user_agent"))


class FakeFetcher(object):
    """Answers from the fixture folder, except the sources told to fail."""

    def __init__(self, fail=()):
        self.offline, self.calls, self.fail = None, [], fail

    def get(self, url, name, accept="*/*"):
        self.calls.append(url)
        for host, err in self.fail:
            if host in url:
                raise news.NewsError(err)
        path = os.path.join(NDIR, name)
        if not os.path.exists(path):
            raise news.NewsError("HTTP 404")
        with open(path, "rb") as fh:
            return fh.read()


class Politeness(unittest.TestCase):
    def test_a_refusal_stops_nse_for_the_rest_of_the_run(self):
        f = FakeFetcher(fail=[("nseindia.com", "HTTP 403")])
        errors = []
        watch = {"RELIANCE.NS": None, "HCLTECH.NS": None, "M&M.NS": None}
        items = news.collect(f, watch, news.parse_now(NOW), errors=errors)
        nse_calls = [u for u in f.calls if "nseindia.com" in u]
        self.assertEqual(len(nse_calls), 1)                 # asked once, never again this run
        self.assertEqual(len(errors), 1)
        self.assertIn("NSE announcements unavailable (HTTP 403): skipped for the rest of this check", errors[0])
        self.assertIn("unofficial", errors[0])
        self.assertTrue(items)                              # the headlines still came
        self.assertTrue(all(i["source"] != "NSE" for i in items))
        self.assertEqual(len([u for u in f.calls if "news.google.com" in u]), 3)

    def test_the_request_urls(self):
        f = FakeFetcher()
        news.collect(f, {"M&M.NS": "Mahindra & Mahindra Limited"}, news.parse_now(NOW), hours=48)
        nse, g, y = f.calls
        self.assertEqual(nse, "https://www.nseindia.com/api/corporate-announcements?index=equities&symbol=M%26M"
                              "&from_date=12-11-2026&to_date=14-11-2026")
        self.assertEqual(g, "https://news.google.com/rss/search?q=%22Mahindra%20%26%20Mahindra%22%20%28share%20OR"
                            "%20shares%20OR%20stock%20OR%20NSE%29&hl=en-IN&gl=IN&ceid=IN:en")
        self.assertEqual(y, "https://feeds.finance.yahoo.com/rss/2.0/headline?s=M%26M.NS&region=IN&lang=en-IN")

    def test_nse_names_the_company_for_google(self):
        f = FakeFetcher()
        news.collect(f, {"RELIANCE.NS": None}, news.parse_now(NOW))
        self.assertIn("q=%22Reliance%20Industries%22", f.calls[1])

    def test_a_slow_polite_pace(self):
        self.assertGreaterEqual(news.PAUSE, 1.0)
        self.assertEqual(news.Fetcher().pause, news.PAUSE)


class Tagging(unittest.TestCase):
    def test_touches_and_tags(self):
        watch = {"RELIANCE.NS": "Reliance Industries Limited", "M&M.NS": "Mahindra & Mahindra Limited"}
        items = [{"id": "a", "kind": "headline", "ticker": "M&M.NS", "title":
                  "Reliance Industries Q2 results: profit jumps; RBI holds the repo rate", "summary": "",
                  "link": "x", "time": None},
                 {"id": "b", "kind": "headline", "ticker": "M&M.NS", "title": "Block deal: 2% stake changes hands "
                  "in NSE: M&M", "summary": "", "link": "y", "time": None}]
        a, b = news.tag(items, watch)
        self.assertEqual(a["touches"], ["M&M.NS", "RELIANCE.NS"])
        self.assertEqual(a["tags"], ["earnings", "macro"])
        self.assertEqual(b["touches"], ["M&M.NS"])
        self.assertIn("block", b["tags"])
        self.assertIn("deal", b["tags"])

    def test_filings_keep_their_nse_tags(self):
        items, _ = news.parse_nse(raw("nse-M&M.json"), "M&M.NS")
        tagged = news.tag(items, {"M&M.NS": None})
        self.assertTrue(all("tags_nse" not in i for i in tagged))
        self.assertEqual([i["tags"] for i in tagged if i["subject"] == "Acquisition"], [["deal"]])

    def test_dedupe_merges_the_same_story(self):
        t = dt.datetime(2026, 11, 13, 8, 0, tzinfo=UTC)
        a = {"id": "1", "link": "l1", "title": "Reliance to invest Rs 1 lakh crore", "time": t, "touches": ["RELIANCE.NS"]}
        b = {"id": "2", "link": "l2", "title": "Reliance to invest Rs 1 lakh crore!", "time": t, "touches": ["M&M.NS"]}
        out = news.dedupe([a, b])
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["touches"], ["M&M.NS", "RELIANCE.NS"])


class Check(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.state = os.path.join(self.d, "news.json")

    def tearDown(self):
        shutil.rmtree(self.d)

    def args(self, *extra):
        return ["--offline", NDIR, "--state", self.state, "--now", NOW, "--portfolio", self.d + "/n",
                "--watchlist", self.d + "/n", "--plan", self.d + "/n"] + list(extra)

    def test_new_items_once_newest_first(self):
        code, text, _ = run(self.args("--symbols", "RELIANCE", "--no-moves"))
        self.assertEqual(code, 0)
        lines = [l for l in text.splitlines() if l.startswith(("  2026", "! 2026"))]
        stamps = [l[2:22] for l in lines]
        self.assertEqual(stamps, sorted(stamps, reverse=True))
        self.assertIn("NSE                      Reliance Industries Limited: Analysts/Institutional Investor Meet",
                      text)
        self.assertIn("2026-11-13 18:25 IST", text)
        self.assertIn("Not financial advice", text)
        code, text, _ = run(self.args("--symbols", "RELIANCE", "--no-moves"))
        self.assertEqual(code, 1)
        self.assertIn("Nothing new.", text)
        code, text, _ = run(self.args("--symbols", "RELIANCE", "--no-moves", "--all"))
        self.assertEqual(code, 1)
        self.assertNotIn("Nothing new.", text)

    def test_the_window(self):
        code, text, _ = run(self.args("--symbols", "M&M", "--no-moves", "--hours", "24", "--dry-run", "--json"))
        doc = json.loads(text)
        cutoff = news.parse_now(NOW) - dt.timedelta(hours=24)
        self.assertTrue(all(news.parse_time(i["time"]) >= cutoff for i in doc["items"] if i["time"]))
        self.assertNotIn("Acquisition", [i.get("subject") for i in doc["items"]])        # Nov 6: outside 24h
        code, text, _ = run(self.args("--symbols", "M&M", "--no-moves", "--hours", "200", "--dry-run", "--json"))
        acq = [i for i in json.loads(text)["items"] if i.get("subject") == "Acquisition"]
        self.assertEqual(len(acq), 1)
        self.assertTrue(acq[0]["important"])

    def test_symbols_from_watchlist_and_plan(self):
        wl = os.path.join(self.d, "watchlist.json")
        with open(wl, "w") as fh:
            json.dump({"hits": [{"symbol": "HCLTECH.NS", "name": "HCL Technologies"}]}, fh)
        pl = os.path.join(self.d, "plan.json")
        with open(pl, "w") as fh:
            json.dump({"symbol": "M&M"}, fh)
        code, text, _ = run(["--offline", NDIR, "--state", self.state, "--now", NOW, "--watchlist", wl,
                             "--plan", pl, "--portfolio", self.d + "/n", "--json", "--dry-run"])
        doc = json.loads(text)
        self.assertEqual(sorted({i["ticker"] for i in doc["items"]}), ["HCLTECH.NS", "M&M.NS"])
        self.assertEqual(sorted(m["ticker"] for m in doc["moves"]), ["HCLTECH.NS", "M&M.NS"])

    def test_no_symbols_is_an_error(self):
        code, _, err = run(self.args())
        self.assertEqual(code, 2)
        self.assertIn("no symbols", err)
        code, _, err = run(self.args("--symbols", "X", "--now", "monday"))
        self.assertEqual(code, 2)
        self.assertIn("--now wants", err)

    def test_moves(self):
        code, text, _ = run(self.args("--symbols", "HCLTECH", "M&M", "--no-nse", "--no-google", "--no-yahoo"))
        self.assertIn("HCLTECH.NS     Rs 1378.00 -0.20% vs yesterday's close Rs 1380.80 at 15:28 IST", text)
        self.assertIn("M&M.NS         Rs 3333.00 -1.94% vs yesterday's close Rs 3399.00 at 15:28 IST", text)
        self.assertNotIn("MOVING", text)
        code, text, _ = run(self.args("--symbols", "M&M", "--no-nse", "--no-google", "--no-yahoo",
                                      "--move-pct", "1.5"))
        self.assertIn("MOVING", text)

    def test_the_rupee_sign_prints_on_a_windows_console(self):
        it = {"id": "x", "source": "Google News", "publisher": None, "ticker": "RELIANCE.NS", "kind": "headline",
              "title": "Reliance adds ₹2.38 lakh crore", "link": "", "tags": [], "touches": ["RELIANCE.NS"],
              "time": None}
        text = news.render([it], [], news.parse_now(NOW))
        self.assertIn("Reliance adds Rs 2.38 lakh crore", text)
        text.encode("cp1252")                               # nothing left that cp1252 cannot print

    def test_state_forgets_after_30_days(self):
        state = {"seen": {"old": "2026-09-01T00:00:00+00:00", "new": "2026-11-10T00:00:00+00:00"}}
        news.remember([], state, news.parse_now(NOW))
        self.assertEqual(sorted(state["seen"]), ["new"])


if __name__ == "__main__":
    unittest.main()
