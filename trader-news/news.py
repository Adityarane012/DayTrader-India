#!/usr/bin/env python3
"""News monitor for trader-news (NSE). Standard library only.

Watches exchange filings and headlines for the stocks you watch or hold and
prints only what is new since the last check, newest first, with how far each
stock has moved today and a flag on anything that touches your symbols.

    python news.py                                    # watchlist + plan + portfolio symbols
    python news.py --symbols RELIANCE HCLTECH "M&M"
    python news.py --symbols HCLTECH --all --hours 72 # everything in the last 3 days, seen or not
    python news.py --no-nse                           # headlines only
    python news.py --no-moves                         # skip the price line per symbol

Your symbols, when --symbols is not given: every hit in trader/watchlist.json
(trader-scanner), the symbol in trader/plan.json (trader-exit) and the
positions in trader/portfolio.json. Symbols are NSE symbols (RELIANCE.NS; a
bare RELIANCE gets the .NS).

Sources, one request each per symbol, a second apart:
  - NSE corporate announcements (the exchange filings: results, board
    meetings, acquisitions, director changes, insider and takeover
    disclosures), for the last --hours:
    https://www.nseindia.com/api/corporate-announcements?index=equities&symbol=<SYM>&from_date=..&to_date=..
    This endpoint is unofficial and NSE sometimes refuses automated requests.
    One plain request, no cookies, no retries: if NSE says no (HTTP 401, 403,
    429, 5xx, or an HTML page instead of JSON), the tool says "NSE
    announcements unavailable", skips NSE for the rest of the run and goes on
    with the headlines. It never works around a block.
  - Google News RSS (India edition), searched by the company's name (from
    the watchlist, trader/universe.txt, or NSE's own name for it) next to
    share-market words, so a name like Trent or Eternal does not bring back
    a footballer or a TV show; quote pages left out:
    https://news.google.com/rss/search?q="<Company name>" (share OR shares OR stock OR NSE)&hl=en-IN&gl=IN&ceid=IN:en
    A one-word name (Trent, BSE) is searched as
    ("Trent Ltd" OR "Trent share" OR "Trent shares" OR "Trent stock").
  - Yahoo Finance headline RSS (often empty for NSE symbols, kept because it
    costs one request): https://feeds.finance.yahoo.com/rss/2.0/headline?s=<SYM>.NS&region=IN&lang=en-IN
  - The move: Yahoo Finance's chart endpoint (unofficial, can lag), the last
    price against yesterday's close.

Times print in India time (IST). State: trader/state/news.json remembers what
you have seen (30 days), so an item shows once. Offline: --offline DIR reads
nse-<SYM>.json, gnews-<SYM>.xml, yahoo-<SYM>.NS.xml and chart-<SYM>.NS.json
from DIR (<SYM> without .NS). The tests use it.

Before the open, two more sections (checked live on 2026-11-16):

  --events   NSE's event calendar, one request, today and the next 3 days:
             https://www.nseindia.com/api/event-calendar?index=equities&from_date=DD-MM-YYYY&to_date=DD-MM-YYYY
             Every result or board meeting of a stock you watch or of the
             universe (trader/universe.txt) is listed; a results day is an
             event day, a reason to skip an opening-range trade. If NSE
             refuses, it says "NSE event calendar unavailable".
  --market   The market's own headlines from the last --market-hours (12):
             Economic Times Markets RSS
               https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms
             Livemint Markets RSS
               https://www.livemint.com/rss/markets
             Moneycontrol, through Google News, its markets and stocks
             sections only (its own RSS feeds stopped updating years ago):
               site:moneycontrol.com/news/business/markets when:1d
               site:moneycontrol.com/news/business/stocks when:1d
             Newest first, one line per story; a * marks a story about the
             Nifty, the Sensex or the market as a whole.
  With either one and no symbols, only those sections run.

Headlines are leads, not facts: open the story or the filing before acting,
and treat nothing here as advice.
"""

import argparse
import datetime as _dt
import email.utils
import gzip
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

NSE_URL = ("https://www.nseindia.com/api/corporate-announcements?index=equities&symbol=%s"
           "&from_date=%s&to_date=%s")
GNEWS_URL = "https://news.google.com/rss/search?q=%s&hl=en-IN&gl=IN&ceid=IN:en"
YAHOO_URL = "https://feeds.finance.yahoo.com/rss/2.0/headline?s=%s&region=IN&lang=en-IN"
CHART_URL = "https://%s.finance.yahoo.com/v8/finance/chart/%s?range=1d&interval=5m"
EVENTS_URL = "https://www.nseindia.com/api/event-calendar?index=equities&from_date=%s&to_date=%s"
MARKET_FEEDS = [  # (label, url, offline file)
    ("Economic Times", "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms", "et-markets.xml"),
    ("Livemint", "https://www.livemint.com/rss/markets", "mint-markets.xml"),
    # Moneycontrol's own RSS stopped updating; Google News limited to its markets and stocks sections
    # (a site-wide search matched the Nifty and Sensex in every page's menu: elections, royals, quote pages)
    ("Moneycontrol", "https://news.google.com/rss/search?q=" + urllib.parse.quote(
        "site:moneycontrol.com/news/business/markets when:1d") + "&hl=en-IN&gl=IN&ceid=IN:en",
     "gnews-mc-markets.xml"),
    ("Moneycontrol", "https://news.google.com/rss/search?q=" + urllib.parse.quote(
        "site:moneycontrol.com/news/business/stocks when:1d") + "&hl=en-IN&gl=IN&ceid=IN:en",
     "gnews-mc-stocks.xml"),
]
MIN_WORDS = 5     # shorter "headlines" in these feeds are quote pages ("State Bank of India")
MARKET_HOURS = 12
MARKET_MAX = 15
EVENT_DAYS = 3
# a story about the market as a whole
MARKET_WIDE = re.compile(r"\bNifty\b|\bSensex\b|Dalal Street|\bstock market\b|\bmarkets?\b|\bFII|\bFPI|"
                         r"\bDII\b|\bRBI\b|\bopening bell\b|\btrade setup\b", re.I)
# Google News lists Moneycontrol's section front pages too; they are not stories
SECTION_PAGE = re.compile(r"^share/stock market news\b|latest nse, bse|business news, stock/share tips", re.I)
UA = "Mozilla/5.0 (compatible; day-trader-india/0.1)"
IST = _dt.timedelta(hours=5, minutes=30)
PAUSE = 1.0      # seconds between requests: be polite, these are free and unofficial
KEEP_DAYS = 30
MOVE_PCT = 3.0   # a stock this far from yesterday's close is flagged as moving

# NSE announcement subjects -> tags. "!" marks the ones that can move a stock today.
NSE_SUBJECTS = [
    ("earnings", True, r"financial result|outcome of board meeting|\bresults?\b"),
    ("people", True, r"change in director|appointment|resignation|cessation|key managerial|\bceo\b|\bcfo\b"),
    ("deal", True, r"acquisition|amalgamation|merger|scheme of arrangement|takeover|divest|sale of"),
    ("insider", True, r"insider trading|takeover regulations|substantial acquisition|\bsast\b|pledge|encumbrance"),
    ("capital", False, r"dividend|buy ?back|bonus|split|rights issue|allotment|record date|book closure|"
                       r"issue of securities|qip|esop|esos|esps|warrant"),
    ("rating", False, r"credit rating"),
    ("legal", True, r"litigation|dispute|penalt|show cause|\bsebi order\b|\border\b.*\bsebi\b|fine"),
    ("clarification", True, r"clarification|verification|spurt in volume|price movement"),
    ("routine", False, r"newspaper publication|trading window|loss of share certificate|investor meet|"
                       r"analysts? meet|con\. call|investor presentation|certificate under|shareholders meeting|"
                       r"general meeting|press release|media release|^updates$|general updates|monthly business"),
]
KEYWORDS = [
    ("earnings", r"\bearnings\b|\bresults\b|\bQ[1-4]\b|\bprofit\b|\brevenue\b|\bEBITDA\b|\bguidance\b"),
    ("analyst", r"\bupgrade[sd]?\b|\bdowngrade[sd]?\b|target price|price target|\bbuy rating\b|\bsell rating\b"),
    ("legal", r"\bSEBI\b.*\b(order|probe|penalty|notice)\b|\bprobe\b|\binvestigation\b|\bcourt\b|\bNCLT\b|\braid\b"),
    ("deal", r"\bacqui(?:re|res|red|sition)\b|\bmerger\b|\bstake\b|\bdeal\b|\border win\b|\bbags? order\b"),
    ("block", r"\bblock deal\b|\bbulk deal\b|\bOFS\b|\boffer for sale\b"),
    ("capital", r"\bdividend\b|\bbuyback\b|\bbonus\b|\bsplit\b|\bQIP\b|\brights issue\b"),
    ("people", r"\bCEO\b|\bCFO\b|\bMD\b|\bresign|\bsteps down\b|\bappoint"),
    ("risk", r"\bdefault\b|\bdowngrade\b|\bfraud\b|\bdelist|\bhack|\bbreach\b|\boutage\b|\bfire\b"),
    ("circuit", r"\bupper circuit\b|\blower circuit\b|\bcircuit limit\b"),
    ("macro", r"\bRBI\b|\brepo rate\b|\bMPC\b|\bCPI\b|\binflation\b|\bGDP\b|\bBudget\b|\bGST\b|\bFII\b|\bFPI\b"),
]
# Google News search results include quote and chart pages, not news
# (a headline like "Reliance Industries' share price jumps 2.75%" is news and stays)
QUOTE_PAGE = re.compile(r"share price today|stock price today|price live|live (?:nse|bse)\b|nse/bse|"
                        r"stock price, news, quote|stock price & chart|\bquote nse\b|"
                        r"\bshare price\s+-\s+[^-]+$", re.I)


class NewsError(Exception):
    pass


class Unavailable(NewsError):
    """The source refused or broke: say so once and stop asking it this run."""


# ---------------------------------------------------------------- symbols and time

def nse_symbol(sym):
    """RELIANCE -> RELIANCE.NS; .NS and .BO kept."""
    s = str(sym).strip().upper()
    return s if s.endswith((".NS", ".BO")) else s + ".NS"


def base(sym):
    """RELIANCE.NS -> RELIANCE, the form NSE's own site uses."""
    s = nse_symbol(sym)
    return s[:-3]


def to_ist(utc):
    """Aware or naive UTC -> naive India wall-clock time."""
    if utc.tzinfo is not None:
        utc = utc.astimezone(_dt.timezone.utc)
    return utc.replace(tzinfo=None) + IST


def parse_time(value):
    """RFC 822 (RSS) or ISO 8601 -> aware UTC datetime, or None. A naive ISO time is UTC."""
    value = (value or "").strip()
    if not value:
        return None
    try:
        d = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError):
        d = None
    if d is None:
        try:
            d = _dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=_dt.timezone.utc)
    return d.astimezone(_dt.timezone.utc)


def parse_ist(value):
    """NSE's "2026-11-13 18:25:01" (India time) -> aware UTC, or None."""
    try:
        local = _dt.datetime.strptime(str(value).strip(), "%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError):
        return None
    return (local - IST).replace(tzinfo=_dt.timezone.utc)


def parse_now(text):
    """--now: an offset or Z is absolute; a time without one is India time."""
    t = str(text).strip()
    try:
        d = _dt.datetime.fromisoformat(t.replace("Z", "+00:00"))
    except ValueError:
        raise NewsError("--now wants a time like \"2026-11-13 09:00\" (India) or ...Z (UTC)")
    if d.tzinfo is None:
        return (d - IST).replace(tzinfo=_dt.timezone.utc)
    return d.astimezone(_dt.timezone.utc)


# ---------------------------------------------------------------- inputs

def load_json(path):
    if path and os.path.isfile(path):
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    return None


def watch_from_files(portfolio="trader/portfolio.json", watchlist="trader/watchlist.json",
                     plan="trader/plan.json"):
    """{SYMBOL.NS: name or None}: the scanner's hits, the planned trade and your holdings."""
    out = {}
    wl = load_json(watchlist) or {}
    for h in wl.get("hits", []):
        sym = h.get("symbol") or h.get("ticker")
        if sym:
            out[nse_symbol(sym)] = h.get("name")
    pl = load_json(plan) or {}
    if pl.get("symbol"):
        out.setdefault(nse_symbol(pl["symbol"]), pl.get("name"))
    pf = load_json(portfolio) or {}
    for p in pf.get("positions", []):
        sym = p.get("ticker") or p.get("symbol")
        if sym:
            s = nse_symbol(sym)
            out[s] = p.get("name") or out.get(s)
    return out


# ---------------------------------------------------------------- fetching

class Fetcher(object):
    def __init__(self, offline=None, pause=PAUSE):
        self.offline = offline
        self.pause = pause
        self._last = 0.0

    def get(self, url, name, accept="*/*"):
        if self.offline:
            path = os.path.join(self.offline, name)
            if not os.path.isfile(path):
                raise NewsError("offline: no file %s" % path)
            with open(path, "rb") as fh:
                return fh.read()
        gap = time.time() - self._last
        if gap < self.pause:
            time.sleep(self.pause - gap)
        self._last = time.time()
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": accept,
                                                   "Accept-Encoding": "gzip"})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = resp.read()
                if resp.headers.get("Content-Encoding") == "gzip":
                    data = gzip.decompress(data)
                return data
        except urllib.error.HTTPError as exc:
            raise NewsError("HTTP %s" % exc.code)
        except urllib.error.URLError as exc:
            raise NewsError("could not connect (%s)" % (exc.reason,))
        except OSError as exc:
            raise NewsError("network error (%s)" % exc)


# ---------------------------------------------------------------- parsing

def _text(el, name):
    c = el.find(name)
    return (c.text or "").strip() if c is not None and c.text else ""


def parse_rss(data, sym, source):
    """RSS 2.0 (Google News or Yahoo) -> items. Google's quote pages are left out."""
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise NewsError("%s RSS for %s is not valid XML: %s" % (source, sym, exc))
    out = []
    for it in root.iter("item"):
        title = _text(it, "title")
        if not title or QUOTE_PAGE.search(title):
            continue
        publisher = _text(it, "source")
        if publisher and title.endswith(" - " + publisher):
            title = title[:-len(" - " + publisher)]
        link = _text(it, "link")
        guid = _text(it, "guid") or link
        out.append({"id": "%s:%s" % ("gnews" if source == "Google News" else "rss", guid),
                    "source": source, "publisher": publisher or None, "kind": "headline",
                    "ticker": sym, "title": title, "summary": "", "link": link,
                    "time": parse_time(_text(it, "pubDate"))})
    return out


def parse_nse(data, sym):
    """NSE corporate announcements JSON -> (items, company name). Raises Unavailable on a
    page that is not the JSON list (NSE's access page, an error page)."""
    try:
        rows = json.loads(data.decode("utf-8") if isinstance(data, bytes) else data)
    except ValueError:
        raise Unavailable("NSE announcements unavailable for %s: the answer was not JSON (an access or "
                          "error page), skipped" % sym)
    if not isinstance(rows, list):
        raise Unavailable("NSE announcements unavailable for %s: unexpected answer, skipped" % sym)
    out, name = [], None
    for r in rows:
        if not isinstance(r, dict):
            continue
        name = name or r.get("sm_name")
        subject = str(r.get("desc") or "announcement").strip()
        text = re.sub(r"\s+", " ", str(r.get("attchmntText") or "")).strip()
        tags, important = [], False
        for label, imp, rx in NSE_SUBJECTS:
            if re.search(rx, subject, re.I):
                tags.append(label)
                important = important or imp
        if "routine" in tags and len(tags) > 1:
            tags.remove("routine")
        seq = r.get("seq_id") or "%s|%s" % (r.get("sort_date"), subject)
        out.append({"id": "nse:%s" % seq, "source": "NSE", "kind": "filing", "ticker": sym,
                    "title": "%s: %s" % (r.get("sm_name") or base(sym), subject), "subject": subject,
                    "summary": text[:300], "link": r.get("attchmntFile") or "", "tags_nse": tags,
                    "important": important, "time": parse_ist(r.get("sort_date"))})
    return out, name


def parse_events(data):
    """NSE event calendar JSON -> [{symbol, company, purpose, desc, date}]. Unavailable on a
    page that is not the JSON list."""
    try:
        rows = json.loads(data.decode("utf-8") if isinstance(data, bytes) else data)
    except ValueError:
        raise Unavailable("NSE event calendar unavailable: the answer was not JSON (an access or error page)")
    if not isinstance(rows, list):
        raise Unavailable("NSE event calendar unavailable: unexpected answer")
    out = []
    for r in rows:
        if not isinstance(r, dict) or not r.get("symbol"):
            continue
        try:
            day = _dt.datetime.strptime(str(r.get("date")), "%d-%b-%Y").date()
        except ValueError:
            continue
        purpose = re.sub(r"\s+", " ", str(r.get("purpose") or "")).strip()
        out.append({"symbol": nse_symbol(r["symbol"]), "company": str(r.get("company") or "").strip(),
                    "purpose": purpose, "desc": re.sub(r"\s+", " ", str(r.get("bm_desc") or "")).strip(),
                    "date": day, "results": bool(re.search(r"result", purpose, re.I))})
    out.sort(key=lambda e: (e["date"], e["symbol"]))
    return out


def collect_events(fetcher, now, days=EVENT_DAYS, errors=None):
    """Today and the next `days` days from NSE's event calendar, one request."""
    errors = [] if errors is None else errors
    first = to_ist(now).date()
    last = first + _dt.timedelta(days=days)
    try:
        data = fetcher.get(EVENTS_URL % (first.strftime("%d-%m-%Y"), last.strftime("%d-%m-%Y")),
                           "nse-events.json", accept="application/json")
        return parse_events(data), first, last
    except Unavailable as exc:
        errors.append(str(exc))
    except NewsError as exc:
        errors.append("NSE event calendar unavailable (%s). NSE's endpoints are unofficial and sometimes "
                      "refuse automated requests; see nseindia.com in a browser" % exc)
    return None, first, last


def collect_market(fetcher, now, hours=MARKET_HOURS, most=MARKET_MAX, errors=None):
    """The market's headlines from the last `hours`, newest first, one per story."""
    errors = [] if errors is None else errors
    items = []
    for label, url, fname in MARKET_FEEDS:
        try:
            got = parse_rss(fetcher.get(url, fname), "MARKET", label)
        except NewsError as exc:
            errors.append("%s headlines unavailable (%s)" % (label, exc))
            continue
        for it in got:
            it["title"] = re.sub(r"^[\s-]+", "", it["title"])
            if SECTION_PAGE.search(it["title"]) or len(it["title"].split()) < MIN_WORDS:
                continue
            if label == "Moneycontrol" and it.get("publisher") and "moneycontrol" not in it["publisher"].lower():
                continue
            it["source"] = label
            it["publisher"] = None
            items.append(it)
    cutoff = now - _dt.timedelta(hours=hours)
    ahead = now + _dt.timedelta(minutes=10)
    items = [i for i in items if i["time"] is not None and cutoff <= i["time"] <= ahead]
    for it in items:
        it["touches"] = []
        it["market"] = bool(MARKET_WIDE.search(it["title"]))
    items.sort(key=lambda i: i["time"], reverse=True)
    return dedupe(items)[:most]


def flag_events(events, watch, universe):
    """The events that matter here: stocks you watch first, then the universe."""
    out = []
    for e in events or []:
        if e["symbol"] in watch:
            out.append(dict(e, why="watch"))
        elif e["symbol"] in universe:
            out.append(dict(e, why="universe"))
    return out


def render_events(events, flagged, first, last, today):
    out = ["NSE events %s to %s (results and board meetings):" % (first.strftime("%d %b"), last.strftime("%d %b"))]
    if events is None:
        return out[:0]
    if not flagged:
        out.append("  none for the stocks you watch or the universe.")
    for e in flagged:
        when = "TODAY" if e["date"] == today else e["date"].strftime("%a %d %b")
        tail = ""
        if e["why"] == "watch":
            tail = "  <- on your list: an event day, skip an opening-range trade" if e["date"] == today \
                else "  <- on your list"
        out.append("  %-10s %-14s %s%s" % (when, e["symbol"], e["purpose"] or "board meeting", tail))
    others = len(events) - len(flagged)
    if others:
        out.append("  (%d more event%s for other companies.)" % (others, "" if others == 1 else "s"))
    return out


def render_market(items, hours):
    out = ["Market headlines, last %s hours (* = the market as a whole):" % ("%g" % hours)]
    if not items:
        out.append("  nothing in the window.")
    for it in items:
        out.append("%s %s  %-14s %s" % ("*" if it.get("market") else " ",
                                         to_ist(it["time"]).strftime("%d %b %H:%M"), it["source"][:14], it["title"]))
    return out


def parse_chart(data, sym):
    """Yahoo chart JSON -> {"ticker", "price", "prev_close", "pct", "time"} or raise."""
    try:
        doc = json.loads(data.decode("utf-8") if isinstance(data, bytes) else data)
        meta = doc["chart"]["result"][0]["meta"]
    except (ValueError, KeyError, IndexError, TypeError):
        raise NewsError("chart for %s is not usable" % sym)
    price = meta.get("regularMarketPrice")
    prev = meta.get("chartPreviousClose") or meta.get("previousClose")
    if not price or not prev:
        raise NewsError("chart for %s has no price" % sym)
    when = meta.get("regularMarketTime")
    return {"ticker": sym, "price": round(float(price), 2), "prev_close": round(float(prev), 2),
            "pct": round((float(price) / float(prev) - 1) * 100, 2),
            "time": _dt.datetime.fromtimestamp(when, _dt.timezone.utc) if when else None}


def company_query(name, sym):
    """The Google News search for a symbol: its company name (without "Limited") next to
    share-market words. A one-word name is ambiguous on its own (Trent, Eternal, BSE),
    so it is searched only as "<name> Ltd", "<name> share(s)" or "<name> stock".
    Checked against live Google News results on 2026-11-15."""
    n = re.sub(r"\s+(Limited|Ltd\.?)$", "", str(name).strip(), flags=re.I) if name else base(sym)
    if len(n.split()) == 1:
        return '("%s Ltd" OR "%s share" OR "%s shares" OR "%s stock")' % (n, n, n, n)
    return '"%s" (share OR shares OR stock OR NSE)' % n


def names_from_universe(path="trader/universe.txt"):
    """{SYMBOL.NS: company name} from the scanner's universe file (SYMBOL.NS|Name a line)."""
    out = {}
    try:
        with open(path, encoding="utf-8") as fh:
            for ln in fh:
                sym, _, name = ln.strip().partition("|")
                if sym and name and not sym.startswith("#"):
                    out[nse_symbol(sym)] = name.strip()
    except OSError:
        pass
    return out


# ---------------------------------------------------------------- the check

def collect(fetcher, watch, now, hours=48, nse=True, google=True, yahoo=True, errors=None):
    """Every source for every symbol. NSE that refuses once is skipped for the rest of the run."""
    errors = [] if errors is None else errors
    items, nse_ok = [], nse
    day_from = to_ist(now - _dt.timedelta(hours=hours)).strftime("%d-%m-%Y")
    day_to = to_ist(now).strftime("%d-%m-%Y")
    for sym in sorted(watch):
        name = watch.get(sym)
        b = base(sym)
        if nse_ok:
            try:
                data = fetcher.get(NSE_URL % (urllib.parse.quote(b, safe=""), day_from, day_to),
                                   "nse-%s.json" % b, accept="application/json")
                found, nse_name = parse_nse(data, sym)
                items += found
                name = name or nse_name
            except Unavailable as exc:
                errors.append(str(exc))
                nse_ok = False
            except NewsError as exc:
                if fetcher.offline and "no file" in str(exc):
                    pass
                else:
                    errors.append("NSE announcements unavailable (%s): skipped for the rest of this check. "
                                  "NSE's endpoints are unofficial and sometimes refuse automated requests; "
                                  "see nseindia.com in a browser" % exc)
                    nse_ok = False
        if google:
            try:
                q = urllib.parse.quote(company_query(name, sym))
                items += parse_rss(fetcher.get(GNEWS_URL % q, "gnews-%s.xml" % b), sym, "Google News")
            except NewsError as exc:
                if not (fetcher.offline and "no file" in str(exc)):
                    errors.append("Google News for %s: %s" % (sym, exc))
        if yahoo:
            try:
                items += parse_rss(fetcher.get(YAHOO_URL % urllib.parse.quote(sym, safe=".-"),
                                               "yahoo-%s.xml" % sym), sym, "Yahoo Finance")
            except NewsError as exc:
                if not (fetcher.offline and "no file" in str(exc)):
                    errors.append("Yahoo headlines for %s: %s" % (sym, exc))
    return items


def collect_moves(fetcher, watch, errors=None):
    errors = [] if errors is None else errors
    out = []
    for sym in sorted(watch):
        name = "chart-%s.json" % sym
        q = urllib.parse.quote(sym, safe=".-")
        try:
            try:
                data = fetcher.get(CHART_URL % ("query2", q), name)
            except NewsError as exc:
                if fetcher.offline or not re.search(r"HTTP (429|5\d\d)", str(exc)):
                    raise
                data = fetcher.get(CHART_URL % ("query1", q), name)
            out.append(parse_chart(data, sym))
        except NewsError as exc:
            if not (fetcher.offline and "no file" in str(exc)):
                errors.append("price for %s: %s" % (sym, exc))
    return out


def mention_patterns(watch):
    pats = {}
    for sym, name in watch.items():
        b = re.escape(base(sym))
        alts = [r"\b%s\b" % re.escape(sym), r"\b(?:NSE|BSE)\s*:\s*%s\b" % b, r"\(%s\)" % b]
        if name and len(name) >= 4:
            short = re.sub(r"\s+(Limited|Ltd\.?)$", "", name.strip(), flags=re.I)
            alts.append(r"\b%s\b" % re.escape(short).replace(r"\ ", r"[\s-]"))
        pats[sym] = re.compile("|".join(alts), re.I)
    return pats


def tag(items, watch):
    """Which of your symbols each item touches, and why it matters."""
    pats = mention_patterns(watch)
    for it in items:
        hay = "%s %s" % (it["title"], it.get("summary") or "")
        touches = {it["ticker"]} if it["ticker"] in watch else set()
        for sym, rx in pats.items():
            if rx.search(hay):
                touches.add(sym)
        it["touches"] = sorted(touches)
        if it["kind"] == "filing":
            it["tags"] = list(it.pop("tags_nse", []))
        else:
            it["tags"] = [label for label, rx in KEYWORDS if re.search(rx, hay, re.I if label != "macro" else 0)]
    return items


def dedupe(items):
    """One item per story: same id, or same link, or same title the same day."""
    seen, out = {}, []
    for it in items:
        keys = [it["id"], it["link"],
                "%s|%s" % (re.sub(r"\W+", " ", it["title"].lower()).strip(),
                           it["time"].date() if it["time"] else "")]
        hit = next((seen[k] for k in keys if k and k in seen), None)
        if hit is not None:
            for t in it.get("touches", []):
                if t not in hit["touches"]:
                    hit["touches"].append(t)
            hit["touches"].sort()
            continue
        for k in keys:
            if k:
                seen[k] = it
        out.append(it)
    return out


def fingerprint(it):
    return hashlib.sha1(it["id"].encode("utf-8")).hexdigest()[:16]


def select(items, state, now, hours=48, show_all=False):
    """Items within the window; only unseen ones unless show_all."""
    seen = state.setdefault("seen", {})
    cutoff = now - _dt.timedelta(hours=hours)
    ahead = now + _dt.timedelta(minutes=10)  # a pinned --now: nothing from after it
    out = []
    for it in items:
        if it["time"] is not None and (it["time"] < cutoff or it["time"] > ahead):
            continue
        fp = fingerprint(it)
        it["new"] = fp not in seen
        if it["new"] or show_all:
            out.append(it)
    out.sort(key=lambda i: (i["time"] or now), reverse=True)
    return out


def remember(items, state, now):
    seen = state.setdefault("seen", {})
    stamp = now.isoformat()
    for it in items:
        seen.setdefault(fingerprint(it), stamp)
    cutoff = (now - _dt.timedelta(days=KEEP_DAYS)).isoformat()
    state["seen"] = {k: v for k, v in seen.items() if v >= cutoff}
    state["last_check"] = stamp


def render_moves(moves, move_pct=MOVE_PCT):
    out = []
    for m in moves:
        flag = "MOVING" if abs(m["pct"]) >= move_pct else ""
        when = (" at %s IST" % to_ist(m["time"]).strftime("%H:%M")) if m.get("time") else ""
        out.append("%-14s Rs %s %+.2f%% vs yesterday's close Rs %s%s  %s" % (
            m["ticker"], "%.2f" % m["price"], m["pct"], "%.2f" % m["prev_close"], when, flag))
    return out


def render(items, errors, now, moves=None, move_pct=MOVE_PCT):
    out = render_moves(moves or [], move_pct)
    if out:
        out.append("")
    if not items:
        out.append("Nothing new.")
    for it in items:
        when = to_ist(it["time"]).strftime("%Y-%m-%d %H:%M IST") if it["time"] else "time unknown"
        mark = "!" if it.get("important") else " "
        who = ",".join(it["touches"]) or it["ticker"]
        src = it["source"] if not it.get("publisher") else "%s/%s" % (it["source"], it["publisher"])
        out.append("%s %s  %-14s %-24s %s" % (mark, when, who, src[:24], it["title"]))
        extra = []
        if it["tags"]:
            extra.append("tags: " + ", ".join(it["tags"]))
        if it["link"]:
            extra.append(it["link"])
        if extra:
            out.append("      " + "  ".join(extra))
    for e in errors:
        out.append("note: %s" % e)
    out.append("Checked %s. Headlines are leads, not facts; open the story or the filing before acting. "
               "Not financial advice." % to_ist(now).strftime("%Y-%m-%d %H:%M IST"))
    return ("\n".join(out) + "\n").replace("₹", "Rs ")


def safe_stdout():
    """Headlines carry text a Windows console code page (cp1252) cannot print: write
    it as ? instead of crashing. The rupee sign itself is turned into Rs by render."""
    try:
        sys.stdout.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass


def _json_ready(items):
    out = []
    for it in items:
        d = dict(it)
        d["time"] = it["time"].isoformat() if it["time"] else None
        out.append(d)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--symbols", "--tickers", dest="symbols", nargs="*",
                    help="default: watchlist + plan + portfolio")
    ap.add_argument("--portfolio", default="trader/portfolio.json")
    ap.add_argument("--watchlist", default="trader/watchlist.json")
    ap.add_argument("--universe", default="trader/universe.txt",
                    help="company names for the Google News search (the scanner writes it)")
    ap.add_argument("--plan", default="trader/plan.json")
    ap.add_argument("--state", default="trader/state/news.json")
    ap.add_argument("--hours", type=float, default=48, help="ignore items older than this")
    ap.add_argument("--all", action="store_true", help="show seen items too")
    ap.add_argument("--no-nse", action="store_true", help="skip NSE announcements")
    ap.add_argument("--no-google", action="store_true", help="skip Google News")
    ap.add_argument("--no-yahoo", action="store_true", help="skip Yahoo headlines")
    ap.add_argument("--no-moves", action="store_true", help="skip the price line per symbol")
    ap.add_argument("--move-pct", type=float, default=MOVE_PCT, help="flag a move this big (percent)")
    ap.add_argument("--offline", metavar="DIR")
    ap.add_argument("--now", help="ISO time (no offset = India time), for reproducible runs")
    ap.add_argument("--market", action="store_true", help="the market's headlines: ET, Livemint, Moneycontrol")
    ap.add_argument("--market-hours", type=float, default=MARKET_HOURS, help="headline window for --market")
    ap.add_argument("--events", action="store_true", help="NSE results and board meetings, today + 3 days")
    ap.add_argument("--dry-run", action="store_true", help="do not update the state file")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    safe_stdout()

    try:
        now = parse_now(args.now) if args.now else _dt.datetime.now(_dt.timezone.utc)
    except NewsError as exc:
        print("news: %s" % exc, file=sys.stderr)
        return 2
    known = watch_from_files(args.portfolio, args.watchlist, args.plan)
    if args.symbols:
        watch = {nse_symbol(s): None for s in args.symbols}
        watch.update({s: known[s] for s in watch if known.get(s)})
    else:
        watch = known
    names = names_from_universe(args.universe)
    watch = {s: (n or names.get(s)) for s, n in watch.items()}
    brief = args.market or args.events
    if not watch and not brief:
        print("news: no symbols. Pass --symbols, or run /trader-scanner first (it writes "
              "trader/watchlist.json).", file=sys.stderr)
        return 2
    state = load_json(args.state) or {}
    errors = []
    fetcher = Fetcher(offline=args.offline)
    head, extra = [], {}
    if args.events:
        events, first, last = collect_events(fetcher, now, errors=errors)
        flagged = flag_events(events, watch, names)
        extra["events"] = None if events is None else [
            dict(e, date=e["date"].isoformat()) for e in flagged]
        head += render_events(events, flagged, first, last, to_ist(now).date()) + [""]
    if args.market:
        market = collect_market(fetcher, now, args.market_hours, errors=errors)
        extra["market"] = _json_ready(market)
        head += render_market(market, args.market_hours) + [""]
    if not watch:
        if args.json:
            print(json.dumps(dict({"checked": now.isoformat(), "notes": errors}, **extra), indent=2))
        else:
            for e in errors:
                head.append("note: %s" % e)
            head.append("Checked %s. Headlines are leads, not facts. Not financial advice."
                        % to_ist(now).strftime("%Y-%m-%d %H:%M IST"))
            sys.stdout.write(("\n".join(head) + "\n").replace("\u20b9", "Rs "))
        return 0 if (extra.get("market") or extra.get("events")) else 1
    if head and not args.json:
        sys.stdout.write(("\n".join(head) + "\n").replace("\u20b9", "Rs "))
    items = collect(fetcher, watch, now, args.hours, nse=not args.no_nse, google=not args.no_google,
                    yahoo=not args.no_yahoo, errors=errors)
    items = dedupe(tag(items, watch))
    shown = select(items, state, now, hours=args.hours, show_all=args.all)
    moves = [] if args.no_moves else collect_moves(fetcher, watch, errors)
    if args.json:
        mv = [dict(m, time=m["time"].isoformat() if m.get("time") else None,
                   moving=abs(m["pct"]) >= args.move_pct) for m in moves]
        print(json.dumps(dict({"checked": now.isoformat(), "moves": mv, "items": _json_ready(shown),
                               "notes": errors}, **extra), indent=2))
    else:
        sys.stdout.write(render(shown, errors, now, moves, args.move_pct))
    if not args.dry_run:
        remember(items, state, now)
        folder = os.path.dirname(args.state)
        if folder:
            os.makedirs(folder, exist_ok=True)
        with open(args.state, "w", encoding="utf-8") as fh:
            json.dump(state, fh, indent=2)
            fh.write("\n")
    return 0 if any(i["new"] for i in shown) else 1


if __name__ == "__main__":
    sys.exit(main())
