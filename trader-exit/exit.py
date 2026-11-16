#!/usr/bin/env python3
"""Exit Planner for trader-exit: sets the stop and the target BEFORE you
enter, so you know when to get out. Standard library only. Long side only.
It never places an order.

    python exit.py plan                                    # from trader/entry.json: or-mid stop, 2R target
    python exit.py plan --stop or-mid --target 1R --write  # HCLTECH: stop 1377.40, target 1391.80
    python exit.py plan --symbol HCLTECH --entry 1384.60 --or-high 1381.00 --or-low 1373.80
    python exit.py plan --stop atr:1.5 --offline HCLTECH.NS.json # ATR needs the session's bars
    python exit.py plan --symbol RELIANCE --entry 1342.80 --setup level --stop pct:1
    python exit.py show                                    # the current trader/plan.json

Symbols are NSE symbols (a bare HCLTECH becomes HCLTECH.NS). Times are India
time (IST); prices are rupees.

Stops (a long's stop rounds DOWN to the NSE tick, away from the entry):
  or-mid     the opening-range midpoint (the default for an orb entry)
  or-low     the opening-range low
  price:X    your price
  pct:X      X percent under the entry
  atr:K      K times the 14-bar ATR under the entry, on the session's bars up
             to the entry bar (--offline FILE or Yahoo). With fewer than 14
             bars by then it averages all of them and says so.
  A level setup has no opening-range default: give a stop.

Targets (round DOWN to the NSE tick, the side that is easier to reach):
  2R (default), 1R, 1.5R ...   entry + R x risk, where risk = entry - stop
  price:X                      your price

Ticks. An exit order off the tick is rejected by the exchange. The tick goes
by the price (NSE circular NSE/CMTR/67133): 0.01 below 250, 0.05 up to 1,000,
0.10 up to 5,000, 0.50 up to 10,000, 1.00 up to 20,000, 5.00 above. NSE sets
each stock's tick monthly from the previous month's last close, so a stock
near a boundary can differ: --tick 0.05 overrides it.

Refused, with the reason: a stop at or above the entry, a target at or below
it, a risk under 0.05% of the price (too tight to survive the spread), an
entry.json that has not triggered (unless you give --entry), a short (this
pack plans longs only).

flat_by (default 15:15, or "flat_by" in trader/config.json): out by then, win
or lose, before the broker's auto square-off (around 15:20 for intraday
orders). It must be before the 15:30 close and after the entry.
"min_reward_risk" in the config (default 1.0) only warns here; trader-risk
enforces it.

Price bands. Many NSE stocks have a daily price band (2, 5, 10 or 20 percent
of the previous close). At the band trading can stop and a stop order may not
fill. With NSE's security list saved as trader/sec_list.csv (--band-file) and
the previous close (--prev-close, or "prev_close" in entry.json), the plan
warns when the stop or the target is within "band_warn_pct" of the config
(default 1, in percent of the previous close) of the day's upper or lower
limit. It is a warning, never a refusal. No list, no previous close or an
unknown symbol: it says "band unknown" once and carries on.

A stop is a plan, not a guarantee: a gap or a fast market can fill past it.
Exit codes: plan 0 = a plan, 1 = refused or an error. show 0 = a plan exists.
"""

import argparse
import csv
import datetime
import gzip
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from decimal import Decimal, InvalidOperation, ROUND_FLOOR, ROUND_HALF_UP

UA = "Mozilla/5.0 (compatible; day-trader-india/0.1)"
BACKOFF = 5.0
HOSTS = ("query2", "query1")
INTERVALS = {"1m": 60, "5m": 300}
DEFAULTS = {"flat_by": "15:15", "min_reward_risk": 1.0, "band_warn_pct": 1}
ATR_BARS = 14
MIN_RISK_PCT = Decimal("0.05")     # risk under 0.05% of the price is inside the spread's noise
CENT = Decimal("0.01")
EPOCH = datetime.datetime(1970, 1, 1)
NOTE = "A stop is a plan, not a guarantee: a gap or a fast market can fill past it."

IST = datetime.timedelta(hours=5, minutes=30)   # India Standard Time: UTC+5:30 all year, no DST

NSE_HOLIDAYS = {  # weekday trading holidays, NSE circular NSE/CMTR/71775 (Dec 12 2025)
    "2026-01-26": "Republic Day",
    "2026-03-03": "Holi",
    "2026-03-26": "Shri Ram Navami",
    "2026-03-31": "Shri Mahavir Jayanti",
    "2026-04-03": "Good Friday",
    "2026-04-14": "Dr. Baba Saheb Ambedkar Jayanti",
    "2026-05-01": "Maharashtra Day",
    "2026-05-28": "Bakri Id",
    "2026-06-26": "Muharram",
    "2026-09-14": "Ganesh Chaturthi",
    "2026-10-02": "Mahatma Gandhi Jayanti",
    "2026-10-20": "Dussehra",
    "2026-11-10": "Diwali-Balipratipada",
    "2026-11-24": "Prakash Gurpurb Sri Guru Nanak Dev",
    "2026-12-25": "Christmas",
}
# The NSE has no scheduled early closes. Muhurat trading (Sun Nov 8 2026) is a
# special evening session, not a day to day-trade, so it stays closed here.
EARLY_CLOSE = {}
CALENDAR_YEARS = (2026,)   # NSE publishes the next year's list each December
OPEN = datetime.time(9, 15)
CLOSE = datetime.time(15, 30)


class PlanError(Exception):
    pass


# ---------------------------------------------------------------- time

def to_ist(utc):
    """Naive UTC -> naive India time."""
    return utc.replace(tzinfo=None) + IST


def ist_to_utc(local):
    """Naive India time -> naive UTC."""
    return local.replace(tzinfo=None) - IST


def utc_now():
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0, tzinfo=None)


def utc_of(ts):
    return EPOCH + datetime.timedelta(seconds=int(ts))


def parse_now(text):
    """--now -> naive UTC. A time without an offset is India time."""
    if not text:
        return utc_now()
    t = text.strip()
    if t.upper().endswith(" IST"):
        t = t[:-4].strip()
    if re.match(r"^\d{1,2}:\d{2}$", t):
        t = "%s %s" % (to_ist(utc_now()).date().isoformat(), t.zfill(5))
    t = t.replace("Z", "+00:00")
    try:
        dt = datetime.datetime.fromisoformat(t)
    except ValueError:
        raise PlanError('--now wants an India time like "2026-11-13 09:35" (or ...Z for UTC)')
    if dt.tzinfo is None:
        return ist_to_utc(dt)
    return (dt - dt.utcoffset()).replace(tzinfo=None)


def parse_hhmm(text, what):
    m = re.match(r"^\s*(\d{1,2}):(\d{2})\s*$", str(text))
    if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
        raise PlanError("%s wants an India time like 15:15, not %r" % (what, text))
    return datetime.time(int(m.group(1)), int(m.group(2)))


def parse_clock(text, what):
    """10:15 AM, 10:15, 3:05 PM -> time."""
    m = re.match(r"^\s*(\d{1,2}):(\d{2})\s*([AaPp][Mm])?\s*$", str(text))
    if not m:
        raise PlanError("%s wants a time like 10:15 AM, not %r" % (what, text))
    h, mi = int(m.group(1)), int(m.group(2))
    if m.group(3):
        if not 1 <= h <= 12:
            raise PlanError("%s wants a time like 10:15 AM, not %r" % (what, text))
        h = h % 12 + (12 if m.group(3).upper() == "PM" else 0)
    if h > 23 or mi > 59:
        raise PlanError("%s wants a time like 10:15 AM, not %r" % (what, text))
    return datetime.time(h, mi)


def hm(t):
    return "%02d:%02d" % (t.hour, t.minute)


def ampm(t):
    h = t.hour % 12 or 12
    return "%d:%02d %s" % (h, t.minute, "AM" if t.hour < 12 else "PM")


def session(d):
    """(open_time, close_time) in India time, or None if closed all day."""
    if d.weekday() >= 5 or d.isoformat() in NSE_HOLIDAYS:
        return None
    return OPEN, EARLY_CLOSE.get(d.isoformat(), CLOSE)


# ---------------------------------------------------------------- money math (Decimal, to the cent)

def D(x, what="a number"):
    try:
        if isinstance(x, float):
            return Decimal(repr(x))
        t = str(x).strip()
        for pre in ("Rs.", "Rs", "INR", "\u20b9"):
            if t[:len(pre)].lower() == pre.lower():
                t = t[len(pre):].strip()
                break
        return Decimal(t.replace(",", ""))
    except (InvalidOperation, ValueError):
        raise PlanError("%s is not a number: %r" % (what, x))


def cents(x):
    """Round half up to the cent."""
    return D(x).quantize(CENT, rounding=ROUND_HALF_UP)


def floor_cents(x):
    """A long's stop: round down, away from the entry."""
    return D(x).quantize(CENT, rounding=ROUND_FLOOR)


# NSE tick sizes, capital market segment (circular NSE/CMTR/67133, from April 15 2025).
# NSE fixes each stock's tick once a month from the previous month's last close, so a
# stock near a boundary can sit one band off: --tick overrides it.
TICKS = ((Decimal("250"), Decimal("0.01"), False), (Decimal("1000"), Decimal("0.05"), True),
         (Decimal("5000"), Decimal("0.10"), True), (Decimal("10000"), Decimal("0.50"), True),
         (Decimal("20000"), Decimal("1.00"), True))
TOP_TICK = Decimal("5.00")
VALID_TICKS = (Decimal("0.01"), Decimal("0.05"), Decimal("0.10"), Decimal("0.50"), Decimal("1.00"), Decimal("5.00"))


def tick_for(price):
    """The NSE tick for a price: 0.01 below 250, 0.05 to 1,000, 0.10 to 5,000, 0.50 to
    10,000, 1.00 to 20,000, 5.00 above."""
    p = D(price)
    for top, tick, inclusive in TICKS:
        if p < top or (inclusive and p == top):
            return tick
    return TOP_TICK


def floor_tick(x, tick):
    """Down to a multiple of the tick: an exit order off the tick is rejected."""
    return (D(x) / tick).to_integral_value(rounding=ROUND_FLOOR) * tick


def group_in(whole):
    """Indian digit grouping: 1234567 -> 12,34,567 (lakh and crore)."""
    if len(whole) <= 3:
        return whole
    head, tail = whole[:-3], whole[-3:]
    parts = []
    while len(head) > 2:
        parts.insert(0, head[-2:])
        head = head[:-2]
    if head:
        parts.insert(0, head)
    return ",".join(parts + [tail])


def money(x):
    """Rs 1,384.60; Rs 1,00,000.00; -Rs 46.88."""
    q = D(x).quantize(CENT)
    whole, frac = format(abs(q), "f").split(".")
    return "%sRs %s.%s" % ("-" if q < 0 else "", group_in(whole), frac)


def num(x):
    """1, 1.5, 2.25: a Decimal without trailing zeros."""
    s = format(D(x).normalize(), "f")
    return s


def ratio(x):
    """reward:risk for people: 1.0, 1.5, 1.37."""
    s = "%.2f" % float(x)
    return s[:-1] if s.endswith("0") else s


WORDS = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five"}


def parse_stop(text):
    t = str(text).strip().lower()
    if t in ("or-mid", "or_mid", "mid", "or-midpoint"):
        return "or_mid", None
    if t in ("or-low", "or_low", "low"):
        return "or_low", None
    m = re.match(r"^(price|pct|atr):\s*(?:rs\.?\s*)?([0-9][0-9,]*\.?[0-9]*)$", t)
    if not m:
        raise PlanError("--stop is or-mid, or-low, price:X, pct:X or atr:K (got %r)" % text)
    kind, val = m.group(1), D(m.group(2), "--stop")
    if val <= 0:
        raise PlanError("--stop %s needs a number above 0" % kind)
    if kind == "pct" and val >= 100:
        raise PlanError("--stop pct:X needs X under 100")
    return kind, val


def parse_target(text):
    t = str(text).strip()
    m = re.match(r"^([0-9]*\.?[0-9]+)\s*[Rr]$", t)
    if m:
        r = D(m.group(1), "--target")
        if r <= 0:
            raise PlanError("--target needs an R multiple above 0, like 1R or 2R")
        return "r", r
    m = re.match(r"^price:\s*(?:rs\.?\s*)?([0-9][0-9,]*\.?[0-9]*)$", t.lower())
    if m:
        return "price", D(m.group(1), "--target")
    raise PlanError("--target is 2R, 1R, 1.5R ... or price:X (got %r)" % text)


def r_label(r):
    n = int(r) if r == r.to_integral_value() else None
    return "%sR (%s times the risk)" % (num(r), WORDS.get(n, num(r)))


def compute(entry, stop_rule, stop_param, target_rule, target_param, or_high=None, or_low=None,
            atr=None, atr_bars=None, tick=None):
    """The stop, the target and the risk, in exact paise, both exits on the NSE tick
    (rounded DOWN: they are sell orders). Raises PlanError with the reason."""
    e = cents(entry)
    if e <= 0:
        raise PlanError("the entry price must be above Rs 0")
    if tick is None:
        tick = tick_for(e)
    else:
        tick = D(tick, "--tick")
        if tick not in VALID_TICKS:
            raise PlanError("--tick wants an NSE tick size: 0.01, 0.05, 0.10, 0.50, 1 or 5")
    notes = []
    detail = ""
    if stop_rule in ("or_mid", "or_low"):
        if or_high is None or or_low is None:
            raise PlanError("an %s stop needs the opening range (--or-high and --or-low)" % stop_rule.replace("_", "-"))
        oh, ol = cents(or_high), cents(or_low)
        if oh <= ol:
            raise PlanError("the opening-range high %s must be above its low %s" % (money(oh), money(ol)))
        if stop_rule == "or_mid":
            raw = (oh + ol) / 2
            label = "opening-range midpoint"
            detail = "(%s + %s) / 2 = Rs %s" % (money(oh), money(ol), num(raw))
        else:
            raw, label = ol, "opening-range low"
    elif stop_rule == "price":
        raw, label = stop_param, "your price"
    elif stop_rule == "pct":
        raw = e * (1 - stop_param / 100)
        label = "%s%% under the entry" % num(stop_param)
        detail = "%s x (1 - %s%%) = Rs %s" % (money(e), num(stop_param), num(raw))
    elif stop_rule == "atr":
        if atr is None:
            raise PlanError("an atr stop needs the session's bars")
        a = D(round(atr, 6))
        raw = e - stop_param * a
        label = "%s x ATR(%d) under the entry" % (num(stop_param), atr_bars)
        detail = "ATR Rs %s over the %d bars to the entry%s" % (
            num(a.quantize(Decimal("0.0001"))), atr_bars, " (fewer than 14 so far)" if atr_bars < ATR_BARS else "")
    else:
        raise PlanError("unknown stop rule %r" % stop_rule)
    stop = floor_tick(raw, tick).quantize(CENT)
    if stop != D(raw):
        how = "rounded down to the Rs %s tick" % tick
        detail = (detail + ", " + how if detail else "Rs %s %s" % (num(raw), how))
    if stop >= e:
        raise PlanError("the stop %s (%s) is at or above the entry %s: a long's stop goes under the entry"
                        % (money(stop), label, money(e)))
    if stop <= 0:
        raise PlanError("the stop works out to %s: pick a stop above Rs 0" % money(stop))
    risk = e - stop
    floor_risk = e * MIN_RISK_PCT / 100
    if risk < floor_risk:
        raise PlanError("the stop is %s under the entry, less than 0.05%% of the price (%s on %s): too tight to "
                        "survive the spread, normal wiggle would stop you out. Widen it."
                        % (money(risk), money(floor_risk.quantize(CENT, rounding=ROUND_HALF_UP)), money(e)))
    if target_rule == "r":
        t_raw = e + target_param * risk
        t_label = r_label(target_param)
    else:
        t_raw = D(target_param)
        t_label = None
    target = floor_tick(t_raw, tick).quantize(CENT)
    if target != t_raw:
        notes.append("Target %s is Rs %s rounded down to the Rs %s tick." % (money(target), num(t_raw), tick))
    if target <= e:
        raise PlanError("the target %s is at or below the entry %s: a long's target goes above it"
                        % (money(target), money(e)))
    rr = ((target - e) / risk).quantize(CENT, rounding=ROUND_HALF_UP)
    if t_label is None:
        t_label = "your price (%sR)" % ratio(rr)
    return {"entry": e, "stop": stop, "stop_label": label, "stop_detail": detail, "target": target,
            "target_r": target_param if target_rule == "r" else rr, "target_label": t_label,
            "risk": risk, "reward_risk": rr, "tick": tick, "notes": notes}


# ---------------------------------------------------------------- bars for ATR (same reader as trader-entry)

def _open_url(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def _sleep(seconds):
    time.sleep(seconds)


def yahoo_get(path):
    """query2 first, query1 on 429 or 5xx; one retry after a pause on 429."""
    last = "no answer"
    for host in HOSTS:
        url = "https://%s.finance.yahoo.com%s" % (host, path)
        for attempt in (0, 1):
            try:
                return _open_url(url)
            except urllib.error.HTTPError as e:
                code, body = e.code, None
                try:
                    if code == 404:     # Yahoo says why in the body: an unknown ticker
                        body = e.read().decode("utf-8", "replace")
                except Exception:
                    body = None
                finally:
                    e.close()
                if code == 404:
                    if body:
                        return body
                    raise PlanError("Yahoo has no chart at %s (HTTP 404)" % url.split("?")[0])
                last = "HTTP %d" % code
                if code == 429 and attempt == 0:
                    _sleep(BACKOFF)
                    continue
                if code == 429 or code >= 500:
                    break
                raise PlanError("Yahoo answered HTTP %d for %s" % (code, url.split("?")[0]))
            except urllib.error.URLError as e:
                last = "could not connect: %s" % (e.reason,)
                break
            except OSError as e:
                last = "network error: %s" % (e,)
                break
    raise PlanError("Yahoo did not answer (%s on query2 and query1): wait a minute and try again" % last)


def read_text(path):
    if path.endswith(".gz"):
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            return fh.read()
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def yahoo_symbol(sym):
    """Yahoo's form of an NSE symbol: RELIANCE -> RELIANCE.NS. A .NS or .BO
    suffix is kept as it is (Yahoo wants the dot: RELIANCE-NS is not a ticker)."""
    s = str(sym).strip().upper()
    return s if s.endswith((".NS", ".BO")) else s + ".NS"


def url_symbol(sym):
    """The symbol as it goes in a URL path: M&M.NS -> M%26M.NS (a bare & would end it)."""
    return urllib.parse.quote(yahoo_symbol(sym), safe=".-")


def load_chart(sym, interval, day, offline=None):
    ysym = yahoo_symbol(sym)
    if offline:
        path = offline
        if os.path.isdir(offline):
            path = os.path.join(offline, ysym + ".json")
            if not os.path.exists(path):
                path += ".gz"
        if not os.path.exists(path):
            raise PlanError("no offline file %s" % path)
        try:
            text = read_text(path)
        except (OSError, ValueError) as e:
            raise PlanError("could not read %s: %s" % (path, e))
    else:
        back = (to_ist(utc_now()).date() - day).days
        rng = "1d" if back <= 0 else "5d" if back <= 6 else "1mo" if back <= 28 else "60d"
        if interval == "1m" and back > 6:
            raise PlanError("Yahoo keeps 1-minute bars for about a week")
        text = yahoo_get("/v8/finance/chart/%s?range=%s&interval=%s" % (url_symbol(sym), rng, interval))
    try:
        data = json.loads(text)
        res = data["chart"]["result"]
    except (ValueError, KeyError, TypeError):
        raise PlanError("Yahoo returned something unexpected for %s" % sym)
    if not res:
        err = (data.get("chart") or {}).get("error") or {}
        raise PlanError("Yahoo has no data for %s: %s" % (sym, err.get("description") or "unknown ticker"))
    r = res[0] or {}
    meta = r.get("meta") or {}
    if str(meta.get("symbol") or ysym).upper() != ysym:
        raise PlanError("the chart file holds %s, not %s" % (meta.get("symbol"), sym))
    q = ((r.get("indicators") or {}).get("quote") or [{}])[0] or {}

    def at(key, i):
        arr = q.get(key) or []
        return arr[i] if i < len(arr) else None

    bars = []
    for i, t in enumerate(r.get("timestamp") or []):
        c = at("close", i)
        if t is None or c is None:
            continue
        h, lo = at("high", i), at("low", i)
        bars.append({"t": int(t), "h": float(c if h is None else h), "l": float(c if lo is None else lo),
                     "c": float(c)})
    return {"bars": bars, "data_time": meta.get("regularMarketTime")}


def session_bars(chart, day, interval, upto_slot=None, now_utc=None):
    """Closed, on-grid bars of one NSE session, oldest first (the live tick is dropped)."""
    step = INTERVALS[interval]
    s = session(day)
    if not s:
        return []
    open_dt = datetime.datetime.combine(day, s[0])
    close_dt = datetime.datetime.combine(day, s[1])
    if now_utc is None and chart.get("data_time"):
        now_utc = utc_of(chart["data_time"])
    local = to_ist(now_utc) if now_utc else None
    out = {}
    for b in chart["bars"]:
        if b["t"] % step:
            continue
        et = to_ist(utc_of(b["t"]))
        if et.date() != day or not (open_dt <= et < close_dt):
            continue
        if local and et + datetime.timedelta(seconds=step) > local:
            continue
        slot = int((et - open_dt).total_seconds()) // step
        if upto_slot is not None and slot > upto_slot:
            continue
        out[slot] = b
    return [out[k] for k in sorted(out)]


def atr_of(bars, n=ATR_BARS):
    """Average true range of the last n bars (all of them if fewer). The first
    bar of the session uses its own high - low (no overnight gap)."""
    trs, prev = [], None
    for b in bars:
        tr = b["h"] - b["l"]
        if prev is not None:
            tr = max(tr, abs(b["h"] - prev), abs(b["l"] - prev))
        trs.append(tr)
        prev = b["c"]
    use = trs[-n:]
    return sum(use) / len(use), len(use)


# ---------------------------------------------------------------- price bands

SEC_COLUMNS = ("symbol", "series", "security name", "band")


def parse_sec_list(text, skipped=None, duplicates=None):
    """NSE's sec_list.csv (Symbol, Series, Security Name, Band) -> records, file order.

    A record is {"symbol", "series", "name", "band_pct", "band", "reason", "line"}:
      band "percent": band_pct is a float, e.g. 20.0
      band "none":    the stock has no band ("No Band" or blank); band_pct is None
      band "unknown": the band cell is malformed (non-numeric, zero, negative,
                      over 100) or the row is short; band_pct is None, reason says why
    Never guessed, never raises. Header rows (the first, or a repeated one) and
    blank lines are skipped. A row with no symbol is skipped and, if a list is
    passed as `skipped`, noted there as "line N: why". A BOM and extra spaces are
    ignored. Columns are found by header name, so their order and extra columns
    do not matter; with no header, the four columns are in the order above.
    Symbols are upper-cased. Duplicates are all kept: see band_for. If a list is
    passed as `duplicates`, each EQ symbol that appears more than once is noted
    there as (symbol, "line N: ... the last row wins"), once per extra row."""
    text = (text or "").lstrip("\ufeff")
    cols = {name: i for i, name in enumerate(SEC_COLUMNS)}
    records = []
    first_eq = {}
    reader = csv.reader(text.splitlines())
    for row in reader:
        line = reader.line_num
        cells = [c.strip().lstrip("\ufeff").strip() for c in row]
        if not any(cells):
            continue
        low = [c.lower() for c in cells]
        if "symbol" in low and "band" in low:
            cols = {name: low.index(name) for name in SEC_COLUMNS if name in low}
            continue

        def cell(name):
            i = cols.get(name)
            return cells[i] if i is not None and i < len(cells) else None

        symbol = (cell("symbol") or "").upper()
        if not symbol:
            if skipped is not None:
                skipped.append("line %d: no symbol" % line)
            continue
        rec = {"symbol": symbol, "series": (cell("series") or "").upper(), "name": cell("security name") or "",
               "band_pct": None, "band": "unknown", "reason": None, "line": line}
        raw = cell("band")
        if raw is None:
            rec["reason"] = "row has no Band column"
        else:
            word = raw.replace("%", "").strip()
            if word == "" or word.lower() in ("no band", "noband"):
                rec["band"] = "none"
            else:
                try:
                    pct = float(word)
                except ValueError:
                    pct = None
                if pct is None or pct != pct or pct <= 0 or pct > 100:
                    rec["reason"] = "band %r is not a percent between 0 and 100" % raw
                else:
                    rec["band"], rec["band_pct"] = "percent", pct
        if rec["series"] == "EQ":
            if symbol in first_eq:
                if duplicates is not None:
                    duplicates.append((symbol, "line %d: %s is in the EQ series again (first at line %d): "
                                               "the last row wins" % (line, symbol, first_eq[symbol])))
            else:
                first_eq[symbol] = line
        records.append(rec)
    return records


def band_for(records, symbol):
    """The record for a symbol, or None. Only the EQ series counts (the pack
    trades -EQ). If EQ appears more than once the LAST row wins. A trailing .NS is ignored."""
    sym = str(symbol or "").upper()
    if sym.endswith(".NS"):
        sym = sym[:-3]
    found = None
    for r in records:
        if r["symbol"] == sym and r["series"] == "EQ":
            found = r
    return found


def ceil_tick(x, tick):
    return -floor_tick(-D(x), tick)


def band_limits(prev_close, pct, tick):
    """(lower, upper) of the day's band: previous close x (1 -/+ pct/100), the
    upper rounded DOWN and the lower UP to the tick, so both stay inside the band."""
    p, f = D(prev_close), D(pct) / 100
    return ceil_tick(p * (1 - f), tick).quantize(CENT), floor_tick(p * (1 + f), tick).quantize(CENT)


def band_warnings(symbol, prev_close, rec, stop, target, tick, warn_pct):
    """Plain-words lines about the stop and the target against the day's band."""
    name = str(symbol or "").upper()
    if name.endswith(".NS"):
        name = name[:-3]
    if rec is None:
        return ["Band unknown for %s: it is not in the security list (EQ series), so no band check." % name]
    if rec["band"] == "unknown":
        return ["Band unknown for %s: the security list is unclear (%s), so no band check." % (name, rec["reason"])]
    if rec["band"] == "none":
        return ["%s has no price band: no band check." % name]
    if prev_close is None:
        return ["Band unknown for %s: no previous close (pass --prev-close), so no band check." % name]
    pct = D(rec["band_pct"])
    lo, hi = band_limits(prev_close, pct, tick)
    pc, warn = D(prev_close), D(warn_pct)
    near = pc * warn / 100
    where = "%s has a %s%% price band today: %s to %s from the previous close of %s." % (
        name, num(pct), money(lo), money(hi), money(pc))
    out = []
    for label, px in (("stop", D(stop)), ("target", D(target))):
        if px >= hi:
            out.append("The %s %s is above the upper limit %s: it cannot be reached today."
                       % (label, money(px), money(hi)) if px > hi else
                       "The %s %s is at the upper limit: trading can stop there and the order may not fill."
                       % (label, money(px)))
        elif px <= lo:
            out.append("The %s %s is below the lower limit %s: price cannot trade there, so a stop "
                       "order may never fill." % (label, money(px), money(lo)) if px < lo else
                       "The %s %s is at the lower limit: trading can stop there and the order may not fill."
                       % (label, money(px)))
        elif hi - px <= near:
            out.append("The %s %s is within %s%% of the upper limit %s (%s away): at the limit trading "
                       "can stop and the order may not fill." % (label, money(px), num(warn), money(hi), money(hi - px)))
        elif px - lo <= near:
            out.append("The %s %s is within %s%% of the lower limit %s (%s away): at the limit trading "
                       "can stop and a stop order may not fill." % (label, money(px), num(warn), money(lo), money(px - lo)))
    return [where + " " + out[0]] + out[1:] if out else []


# ---------------------------------------------------------------- plan

def read_json(path, what):
    if not path or not os.path.exists(path):
        raise PlanError("no %s at %s" % (what, path))
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except ValueError as e:
        raise PlanError("%s is not valid JSON: %s" % (path, e))


def read_config(path):
    cfg = dict(DEFAULTS)
    if path and os.path.exists(path):
        doc = read_json(path, "config")
        for k in DEFAULTS:
            if doc.get(k) is not None:
                cfg[k] = doc[k]
    return cfg


def resolve_flat_by(day, explicit, cfg, entry_time):
    """(HH:MM, note). Flat by must be inside the session, after the entry."""
    t = parse_hhmm(explicit or cfg.get("flat_by") or DEFAULTS["flat_by"], "--flat-by" if explicit else "flat_by")
    note = ""
    s = session(day) if day else None
    if s:
        close_dt = datetime.datetime.combine(day, s[1])
        at = datetime.datetime.combine(day, t)
        if at >= close_dt:
            if explicit:
                raise PlanError("--flat-by %s is at or after the %s close on %s" % (hm(t), ampm(s[1]), day))
            raise PlanError("flat_by %s in the config is at or after the %s close" % (hm(t), ampm(s[1])))
    if entry_time and entry_time >= t:
        raise PlanError("the entry at %s is at or after your flat-by %s: there is no time left to hold it"
                        % (ampm(entry_time), hm(t)))
    return hm(t), note


def gather(a):
    """The entry facts, from trader/entry.json or the flags."""
    if a.symbol and a.from_path:
        raise PlanError("use --from or --symbol, not both")
    if a.side in ("sell", "short"):
        raise PlanError("This pack plans longs only: no stops above a short entry. Plan a buy instead.")
    if a.symbol:
        if a.entry is None:
            raise PlanError("--symbol needs --entry PRICE")
        if (a.or_high is None) != (a.or_low is None):
            raise PlanError("give both --or-high and --or-low, or neither")
        info = {"symbol": yahoo_symbol(a.symbol), "entry": a.entry, "setup": a.setup or ("orb" if a.or_high is not None else "level"),
                "date": a.date, "entry_time": a.time, "entry_bar": a.entry_bar, "interval": a.interval or "5m",
                "or_high": a.or_high, "or_low": a.or_low, "or_minutes": a.or_minutes, "source": "flags",
                "prev_close": None}
    else:
        path = a.from_path or "trader/entry.json"
        doc = read_json(path, "entry (run /trader-entry first, or give --symbol and --entry)")
        if str(doc.get("side") or "buy").lower() not in ("buy", "long"):
            raise PlanError("%s is a %s: this pack plans longs only" % (path, doc.get("side")))
        if doc.get("status") != "triggered" and a.entry is None:
            raise PlanError("%s says %s is %s, not triggered: plan once it triggers, or give --entry PRICE to plan ahead"
                            % (path, doc.get("symbol"), doc.get("status") or "unknown"))
        orr = doc.get("opening_range") or {}
        info = {"symbol": yahoo_symbol(doc.get("symbol")) if doc.get("symbol") else "", "entry": a.entry if a.entry is not None else doc.get("price"),
                "setup": a.setup or doc.get("setup") or "orb", "date": a.date or doc.get("date"),
                "entry_time": a.time or (doc.get("time") if a.entry is None else None),
                "entry_bar": a.entry_bar if a.entry_bar is not None else (doc.get("bar_index") if a.entry is None else None),
                "interval": a.interval or doc.get("interval") or "5m",
                "or_high": a.or_high if a.or_high is not None else orr.get("high"),
                "or_low": a.or_low if a.or_low is not None else orr.get("low"),
                "or_minutes": orr.get("minutes") or a.or_minutes, "source": path,
                "prev_close": doc.get("prev_close")}
        if not info["symbol"] or info["entry"] is None:
            raise PlanError("%s has no symbol or price" % path)
    if info["interval"] not in INTERVALS:
        raise PlanError("interval is 5m or 1m")
    return info


def last_trading_day(d):
    """The latest NSE trading day on or before d (a date)."""
    while session(d) is None:
        d -= datetime.timedelta(days=1)
    return d


def first_notice_today(state_dir, today, key):
    """True the first time `key` is noticed on India day `today`, then False for the rest of
    that day. A plan is one run of this program, so "once per session" needs a note on disk:
    <state_dir>/exit-band-notice.json. Never raises: if the note cannot be read or written the
    notice simply shows every time (loud, never silent)."""
    path = os.path.join(state_dir, "exit-band-notice.json")
    day = today.isoformat()
    seen = []
    try:
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
        if isinstance(doc, dict) and doc.get("day") == day and isinstance(doc.get("seen"), list):
            seen = doc["seen"]
    except (OSError, ValueError):
        pass
    if key in seen:
        return False
    try:
        os.makedirs(state_dir, exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"day": day, "seen": seen + [key]}, fh)
    except OSError:
        pass
    return True


def check_band(a, info, cfg, c, now_utc=None):
    """The price-band lines for a plan. Never raises: any trouble reads as band unknown.
    The "no security list" and "list is older than the last trading day" notes show once per
    India day (see first_notice_today), not on every plan."""
    name = info["symbol"][:-3] if info["symbol"].upper().endswith(".NS") else info["symbol"]
    path = getattr(a, "band_file", None) or "trader/sec_list.csv"
    state_dir = getattr(a, "state_dir", None) or "trader/state"
    today = to_ist(now_utc or utc_now()).date()
    lines = []
    dups = []
    try:
        with open(path, encoding="utf-8-sig") as fh:
            records = parse_sec_list(fh.read(), duplicates=dups)
        saved = to_ist(utc_of(os.path.getmtime(path))).date()
    except (OSError, UnicodeDecodeError):
        if first_notice_today(state_dir, today, "missing:" + path):
            return ["Band unknown for %s: no security list at %s, so no band check. Save NSE's sec_list.csv "
                    "there (this note shows once a day)." % (name.upper(), path)]
        return []
    latest = last_trading_day(today)
    if saved < latest and first_notice_today(state_dir, today, "stale:%s:%s" % (path, saved.isoformat())):
        lines.append("The security list %s was saved on %s, before the latest trading day %s: price bands may "
                     "have changed. Save NSE's current sec_list.csv (this note shows once a day)."
                     % (path, saved.isoformat(), latest.isoformat()))
    sym = name.upper()
    lines.extend("Security list: %s." % why for s, why in dups if s == sym)
    pc = getattr(a, "prev_close", None)
    if pc is None:
        pc = info.get("prev_close")
    try:
        pc = D(pc) if pc is not None else None
        warn = D(cfg.get("band_warn_pct", 1), "band_warn_pct in the config")
        if warn < 0:
            raise PlanError("band_warn_pct in the config wants a number of 0 or more")
    except PlanError as e:
        return lines + ["Band check skipped: %s." % e]
    if pc is not None and pc <= 0:
        pc = None
    return lines + band_warnings(info["symbol"], pc, band_for(records, info["symbol"]), c["stop"], c["target"],
                                 c["tick"], warn)


def build_plan(a, now_utc):
    info = gather(a)
    cfg = read_config(a.config)
    stop_text = a.stop
    if not stop_text:
        if info["setup"] != "orb":
            raise PlanError("a %s setup has no opening-range stop to default to: give --stop price:X, pct:X or atr:K"
                            % info["setup"])
        stop_text = "or-mid"
    stop_rule, stop_param = parse_stop(stop_text)
    target_rule, target_param = parse_target(a.target or "2R")
    day = None
    if info["date"]:
        try:
            day = datetime.date.fromisoformat(str(info["date"]))
        except ValueError:
            raise PlanError("date wants YYYY-MM-DD, not %r" % info["date"])
    else:
        day = to_ist(now_utc).date()
    entry_time = parse_clock(info["entry_time"], "the entry time") if info["entry_time"] else None
    atr = atr_n = None
    if stop_rule == "atr":
        chart = load_chart(info["symbol"], info["interval"], day, a.offline)
        bars = session_bars(chart, day, info["interval"], info["entry_bar"], parse_now(a.now) if a.now else None)
        if len(bars) < 3:
            raise PlanError("an atr stop needs at least 3 closed %s bars of %s on %s by the entry; found %d"
                            % (info["interval"], info["symbol"], day, len(bars)))
        atr, atr_n = atr_of(bars)
    c = compute(info["entry"], stop_rule, stop_param, target_rule, target_param, info["or_high"], info["or_low"],
                atr, atr_n, a.tick)
    flat_by, flat_note = resolve_flat_by(day, a.flat_by, cfg, entry_time)
    orr = None
    if info["or_high"] is not None and info["or_low"] is not None:
        orr = {"high": float(cents(info["or_high"])), "low": float(cents(info["or_low"])),
               "minutes": int(info["or_minutes"] or 15)}
    plan = {"created_by": "trader-exit", "symbol": info["symbol"], "side": "buy", "date": day.isoformat(),
            "setup": info["setup"], "entry": float(c["entry"]),
            "entry_time": ampm(entry_time) if entry_time else None,
            "entry_bar": info["entry_bar"], "interval": info["interval"], "opening_range": orr,
            "stop": float(c["stop"]), "stop_rule": stop_rule, "stop_label": c["stop_label"],
            "target": float(c["target"]), "target_r": float(c["target_r"]), "target_label": c["target_label"],
            "risk_per_share": float(c["risk"]), "reward_risk": float(c["reward_risk"]), "flat_by": flat_by,
            "tick": float(c["tick"]),
            "stop_detail": c["stop_detail"], "created_at": now_utc.strftime("%Y-%m-%dT%H:%M:%SZ"), "note": NOTE}
    if atr is not None:
        plan["atr"] = round(atr, 4)
        plan["atr_bars"] = atr_n
    warnings = list(c["notes"])
    if c["entry"] != floor_tick(c["entry"], c["tick"]):
        warnings.append("The entry %s is not on the Rs %s tick for its price band: if this stock's tick differs, "
                        "pass --tick." % (money(c["entry"]), c["tick"]))
    if flat_note:
        warnings.append("Flat-by %s: %s." % (flat_by, flat_note))
    warnings.extend(check_band(a, info, cfg, c, now_utc))
    mrr = cfg.get("min_reward_risk")
    try:
        if mrr is not None and c["reward_risk"] < D(mrr):
            warnings.append("Reward:risk %s is under your min_reward_risk %s in the config: trader-risk checks that."
                            % (ratio(c["reward_risk"]), num(D(mrr))))
    except PlanError:
        pass
    today = to_ist(now_utc).date()
    if day != today:
        warnings.append("This plan is for %s, not today (%s)." % (day.isoformat(), today.isoformat()))
    return plan, warnings


def describe(plan):
    day = datetime.date.fromisoformat(plan["date"])
    setup = {"orb": "opening-range breakout", "level": "close above a level"}.get(plan["setup"], plan["setup"])
    e = D(plan["entry"])
    risk = D(plan["risk_per_share"])
    pct = (risk / e * 100).quantize(CENT, rounding=ROUND_HALF_UP)
    when = ""
    if plan.get("entry_time"):
        when = " at %s" % plan["entry_time"]
        if plan.get("entry_bar") is not None:
            when += " (bar %d)" % plan["entry_bar"]
    out = ["Exit plan: %s long, %s, %s on %s bars" % (
        plan["symbol"], day.strftime("%a %Y-%m-%d"), setup, "5-minute" if plan["interval"] == "5m" else "1-minute")]
    out.append("  Entry         %s%s" % (money(plan["entry"]), when))
    out.append("  Stop          %s  %s%s" % (money(plan["stop"]), plan["stop_label"],
                                             (": " + plan["stop_detail"]) if plan.get("stop_detail") else ""))
    out.append("  Target        %s  %s" % (money(plan["target"]), plan["target_label"]))
    out.append("  Risk a share  %s (%s%% of the entry)" % (money(plan["risk_per_share"]), pct))
    out.append("  Reward:risk   %s" % ratio(plan["reward_risk"]))
    out.append("  Flat by       %s IST, win or lose: no overnight hold" % plan["flat_by"])
    out.append("Set before the entry. If price hits the stop, you are out; never move it further away.")
    out.append(NOTE)
    return out


def cmd_plan(a):
    now = parse_now(a.now)
    plan, warnings = build_plan(a, now)
    if a.write:
        d = os.path.dirname(a.write)
        if d:
            os.makedirs(d, exist_ok=True)
        with open(a.write, "w", encoding="utf-8") as fh:
            json.dump(plan, fh, indent=2)
            fh.write("\n")
    if a.json:
        print(json.dumps(dict(plan, warnings=warnings), indent=2))
        return 0
    for line in describe(plan):
        print(line)
    for w in warnings:
        print("Note: " + w)
    if a.write:
        print("Wrote %s." % a.write)
    print("Next: /trader-timemachine replays it, then /trader-budget sizes it to your max loss. Nothing was placed.")
    return 0


def cmd_show(a):
    if not os.path.exists(a.plan):
        print("No plan at %s yet. Make one: exit.py plan --write" % a.plan)
        return 1
    plan = read_json(a.plan, "plan")
    for k in ("symbol", "date", "entry", "stop", "target", "risk_per_share", "reward_risk", "flat_by"):
        if plan.get(k) is None:
            raise PlanError("%s is missing %r: make a new plan with exit.py plan --write" % (a.plan, k))
    if a.json:
        print(json.dumps(plan, indent=2))
        return 0
    for line in describe(dict({"setup": "orb", "interval": "5m", "stop_label": "", "target_label": ""}, **plan)):
        print(line)
    today = to_ist(parse_now(a.now)).date().isoformat()
    if plan["date"] != today:
        print("Note: this plan is for %s, not today (%s)." % (plan["date"], today))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="Exit Planner (trader-exit): the stop and target before the entry.")
    sub = ap.add_subparsers(dest="cmd")
    p = sub.add_parser("plan", help="set the stop and target")
    p.add_argument("--from", dest="from_path", metavar="PATH", help="entry.json to plan from (default trader/entry.json)")
    p.add_argument("--symbol")
    p.add_argument("--entry", type=float, help="entry price (or a plan-ahead price with --from)")
    p.add_argument("--or-high", type=float)
    p.add_argument("--or-low", type=float)
    p.add_argument("--or-minutes", type=int, default=15)
    p.add_argument("--setup", choices=["orb", "level"])
    p.add_argument("--date", help="session date YYYY-MM-DD (default: the entry's, or today)")
    p.add_argument("--time", help="entry time, e.g. 10:15 AM")
    p.add_argument("--entry-bar", type=int)
    p.add_argument("--interval", choices=["5m", "1m"])
    p.add_argument("--side", default="buy", choices=["buy", "long", "sell", "short"], help="buy only")
    p.add_argument("--stop", help="or-mid (orb default), or-low, price:X, pct:X, atr:K")
    p.add_argument("--target", help="2R (default), 1R, 1.5R, price:X")
    p.add_argument("--flat-by", help="HH:MM India time (default: config flat_by, 15:15)")
    p.add_argument("--tick", help="the stock's NSE tick size, if not the one for its price band (0.05, 0.10 ...)")
    p.add_argument("--config", default="trader/config.json")
    p.add_argument("--band-file", default="trader/sec_list.csv", metavar="PATH",
                   help="NSE security list (sec_list.csv) for the price-band warning")
    p.add_argument("--state-dir", default="trader/state", metavar="DIR",
                   help="where the once-a-day band notes are remembered (default trader/state)")
    p.add_argument("--prev-close", type=float, help="the previous close, for the price-band warning")
    p.add_argument("--offline", metavar="PATH", help="saved Yahoo chart JSON for an atr stop")
    p.add_argument("--now", help='pretend it is this India time, e.g. "2026-11-13 09:35"')
    p.add_argument("--write", nargs="?", const="trader/plan.json", metavar="PATH",
                   help="save the plan (default trader/plan.json)")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("show", help="print the current plan")
    p.add_argument("--plan", default="trader/plan.json")
    p.add_argument("--now")
    p.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    if not a.cmd:
        ap.print_help()
        return 1
    try:
        return {"plan": cmd_plan, "show": cmd_show}[a.cmd](a)
    except PlanError as e:
        print("exit.py: %s" % e, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
