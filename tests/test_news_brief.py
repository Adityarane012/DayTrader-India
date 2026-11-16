"""trader-news --events and --market. Fixtures in tests/fixtures/trader-news/brief/, all real
answers fetched Mon Nov 16 2026, 00:30 IST (Sunday night):

nse-events.json         NSE event calendar, 16 to 18 Nov 2026: 11 rows (SANDHAR results,
                        SMLMAH, TTL buyback on the 16th; none in the Nifty 50).
et-markets.xml          Economic Times Markets RSS (newest item Sat 14 Nov 16:40 IST).
mint-markets.xml        Livemint Markets RSS.
gnews-mc-markets.xml    Google News, site:moneycontrol.com/news/business/markets when:1d
gnews-mc-stocks.xml     Google News, site:moneycontrol.com/news/business/stocks when:1d
"""

import io
import json
import os
import unittest
from contextlib import redirect_stdout, redirect_stderr

from _load import load, FIX

news = load("trader-news", "news")

BDIR = os.path.join(FIX, "trader-news", "brief")
NOW = "2026-11-16 00:32"     # India time


def raw(name):
    with open(os.path.join(BDIR, name), "rb") as fh:
        return fh.read()


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = news.main(argv)
    return code, out.getvalue(), err.getvalue()


class Refusing(object):
    """A fetcher whose NSE answer is an access page, not JSON."""

    def get(self, url, name, accept="*/*"):
        if "nseindia.com" in url:
            return b"<html><body>Access Denied</body></html>"
        raise news.NewsError("HTTP 503")


class Events(unittest.TestCase):
    def test_the_calendar_rows(self):
        ev = news.parse_events(raw("nse-events.json"))
        self.assertEqual(len(ev), 11)
        today = [e for e in ev if e["date"].isoformat() == "2026-11-16"]
        self.assertEqual([(e["symbol"], e["results"]) for e in today],
                         [("SANDHAR.NS", True), ("SMLMAH.NS", False), ("TTL.NS", False)])
        self.assertEqual(today[2]["purpose"], "Buyback")

    def test_an_access_page_is_unavailable(self):
        with self.assertRaises(news.Unavailable):
            news.parse_events(b"<html>Access Denied</html>")
        errors = []
        ev, first, last = news.collect_events(Refusing(), news.parse_now(NOW), errors=errors)
        self.assertIsNone(ev)
        self.assertIn("NSE event calendar unavailable", errors[0])
        self.assertEqual((first.isoformat(), last.isoformat()), ("2026-11-16", "2026-11-19"))

    def test_the_request_asks_for_today_and_three_days(self):
        f = news.Fetcher(offline=BDIR)
        seen = []
        real = f.get

        def spy(url, name, accept="*/*"):
            seen.append((url, name))
            return real(url, name, accept)
        f.get = spy
        news.collect_events(f, news.parse_now(NOW))
        self.assertEqual(seen, [("https://www.nseindia.com/api/event-calendar?index=equities"
                                 "&from_date=16-11-2026&to_date=19-11-2026", "nse-events.json")])

    def test_your_stocks_first_and_a_results_day_says_skip(self):
        ev = news.parse_events(raw("nse-events.json"))
        flagged = news.flag_events(ev, {"SANDHAR.NS": None}, {"ANSALAPI.NS": "Ansal"})
        self.assertEqual([(e["symbol"], e["why"]) for e in flagged],
                         [("SANDHAR.NS", "watch"), ("ANSALAPI.NS", "universe")])
        lines = news.render_events(ev, flagged, ev[0]["date"], ev[-1]["date"], ev[0]["date"])
        text = "\n".join(lines)
        self.assertIn("TODAY      SANDHAR.NS     Financial Results  <- on your list: an event day, skip "
                      "an opening-range trade", text)
        self.assertIn("ANSALAPI.NS", text)
        self.assertIn("(9 more events for other companies.)", text)


class Market(unittest.TestCase):
    def items(self, hours=30):
        return news.collect_market(news.Fetcher(offline=BDIR), news.parse_now(NOW), hours)

    def test_three_sources_newest_first_inside_the_window(self):
        got = self.items()
        self.assertEqual(len(got), news.MARKET_MAX)
        times = [i["time"] for i in got]
        self.assertEqual(times, sorted(times, reverse=True))
        self.assertTrue({"Livemint", "Moneycontrol"} <= {i["source"] for i in got})
        cutoff = news.parse_now(NOW) - news._dt.timedelta(hours=30)
        self.assertTrue(all(i["time"] >= cutoff for i in got))

    def test_the_12_hour_window_leaves_out_saturdays_et(self):
        got = self.items(12)
        self.assertNotIn("Economic Times", {i["source"] for i in got})     # newest ET item: Sat 16:40
        self.assertTrue(got)

    def test_market_wide_stories_are_starred(self):
        got = {i["title"]: i["market"] for i in self.items()}
        self.assertTrue(got["Trade Setup for November 16: Top 15 things to know before the opening bell"])
        self.assertTrue(got["Dalal Street Week Ahead: WPI inflation, crude oil among 10 key factors to watch"])

    def test_no_empty_titles_section_pages_or_quote_pages(self):
        titles = [i["title"] for i in self.items(48)]
        self.assertTrue(all(len(t.split()) >= news.MIN_WORDS for t in titles), titles)
        self.assertFalse([t for t in titles if news.SECTION_PAGE.search(t)])
        self.assertFalse([t for t in titles if t.startswith("-") or t.endswith("Moneycontrol.com")])

    def test_a_dead_feed_is_a_note_not_a_crash(self):
        errors = []
        got = news.collect_market(Refusing(), news.parse_now(NOW), errors=errors)
        self.assertEqual(got, [])
        self.assertEqual(len(errors), len(news.MARKET_FEEDS))
        self.assertIn("headlines unavailable", errors[0])


class Command(unittest.TestCase):
    def test_market_and_events_without_symbols(self):
        code, out, err = run(["--market", "--events", "--offline", BDIR, "--now", NOW, "--market-hours", "30",
                              "--watchlist", "none", "--plan", "none", "--portfolio", "none", "--dry-run"])
        self.assertEqual((code, err), (0, ""))
        self.assertIn("NSE events 16 Nov to 19 Nov (results and board meetings):", out)
        self.assertIn("none for the stocks you watch or the universe.", out)
        self.assertIn("Market headlines, last 30 hours (* = the market as a whole):", out)
        self.assertIn("* 15 Nov 16:05  Moneycontrol   Trade Setup for November 16", out)

    def test_json(self):
        code, out, err = run(["--market", "--events", "--offline", BDIR, "--now", NOW, "--json",
                              "--watchlist", "none", "--plan", "none", "--portfolio", "none", "--dry-run"])
        doc = json.loads(out)
        self.assertEqual(doc["events"], [])
        self.assertTrue(doc["market"])
        self.assertIn("time", doc["market"][0])

    def test_without_either_flag_no_symbols_is_still_an_error(self):
        code, out, err = run(["--offline", BDIR, "--now", NOW, "--watchlist", "none", "--plan", "none",
                              "--portfolio", "none", "--dry-run"])
        self.assertEqual(code, 2)
        self.assertIn("no symbols", err)


if __name__ == "__main__":
    unittest.main()
