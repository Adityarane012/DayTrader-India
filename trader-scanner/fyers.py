#!/usr/bin/env python
"""Fyers market data for Day Trader India: the daily login, quotes and candles.

    python fyers.py login            # once a day, after 6:30 AM India time
    python fyers.py status           # is there a login for today?
    python fyers.py quote HCLTECH "M&M"
    python fyers.py bars HCLTECH --interval 5m
    python fyers.py logout

This file reads prices and nothing else. It has no order, funds or holdings
call in it, and the pack never places an order. The same file sits in
trader-alerts, trader-entry and trader-scanner (a test keeps the copies
identical), so each skill folder still works on its own. Standard library only.

Setup, once. Create an app at https://fyers.in/web/api-dashboard/user-apps
with the Market Data permission, then set three environment variables
(Windows: setx NAME "value", then open a new terminal):

    FYERS_APP_ID        the App ID, for example ABCD1234-100
    FYERS_SECRET_ID     the app's Secret ID. Never paste it in a chat.
    FYERS_REDIRECT_URI  the redirect URL you gave the app, letter for letter

Login, each trading day. Fyers access tokens expire daily at 6:30 AM India
time, and the login needs your Fyers PIN and TOTP in the browser, so nothing
here can do it for you. `login` opens the Fyers login page. If the redirect
URL is http://127.0.0.1:PORT/ (or http://localhost:PORT/), this tool catches
the redirect itself. For any other redirect URL, copy the address of the
page you land on (or just the auth code) and paste it at the prompt in your
terminal. The token is saved under your home folder (.day-trader-india),
outside any repo, and is never printed.

Endpoints, from the Fyers API v3 docs (fyers.in/api-docs, read 2026-11-15):
    GET  https://api-t1.fyers.in/api/v3/generate-authcode   the login page
    POST https://api-t1.fyers.in/api/v3/validate-authcode   auth code -> access token
    GET  https://api-t1.fyers.in/data/quotes?symbols=NSE:SBIN-EQ,...   (50 symbols a request)
    GET  https://api-t1.fyers.in/data/history?symbol=...&resolution=5&date_format=1&range_from=...&range_to=...
Every data request carries the header  Authorization: app_id:access_token.

Limits. The free Standard plan allows 5 requests a second, 50 a minute and
5,000 a day, and going over the minute limit more than 3 times in a day
blocks the account for the rest of that day. This tool counts its own
requests in a small file shared by every tool on this computer and stops at
one a second, 40 a minute and 4,500 a day (Fyers answered "too many requests"
to history requests a third of a second apart, well inside its published
limits, so the spacing is one a second); a long job (the opening-range scan) waits for
the next minute instead. If Fyers ever answers "too many requests", it does
not ask Fyers again that day. The tools then stop and say why: they do not
quietly switch to Yahoo's delayed data.
"""

import argparse
import datetime
import hashlib
import http.server
import json
import os
import secrets
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser

UA = "Mozilla/5.0 (compatible; day-trader-india/0.1)"
API = "https://api-t1.fyers.in"
AUTH_URL = API + "/api/v3/generate-authcode"
TOKEN_URL = API + "/api/v3/validate-authcode"
QUOTES_URL = API + "/data/quotes"
HISTORY_URL = API + "/data/history"
MAX_SYMBOLS = 50          # symbols in one quotes request on the Standard plan
PER_MINUTE = 40           # our own ceiling; Fyers allows 50 a minute
PER_DAY = 4500            # our own ceiling; Fyers allows 5,000 a day
MIN_GAP = 1.0             # seconds between two requests. Fyers publishes 5 a second, but answered
                          # HTTP 429 in live testing to history requests about 0.3 s apart
                          # (the 9th request in about a minute), so one a second
LOGIN_WAIT = 300          # seconds the login waits for the browser redirect
AUTH_ERRORS = (-8, -15, -16, -17)   # an expired or invalid token, per the Fyers docs
RESOLUTION = {"1m": "1", "5m": "5"}
STEP = {"1m": 60, "5m": 300}
EPOCH = datetime.datetime(1970, 1, 1)
IST = datetime.timedelta(hours=5, minutes=30)   # India Standard Time: UTC+5:30 all year, no DST
EXPIRES = datetime.time(6, 30)                  # tokens expire daily at 6:30 AM India time
OPEN = datetime.time(9, 15)
CLOSE = datetime.time(15, 30)
ENV_APP, ENV_SECRET, ENV_REDIRECT = "FYERS_APP_ID", "FYERS_SECRET_ID", "FYERS_REDIRECT_URI"
LOGIN_HINT = "log in with: python fyers.py login"


class Unavailable(Exception):
    """Fyers cannot answer this now. The caller stops and says why."""


_urlopen = urllib.request.urlopen   # tests swap these three
_sleep = time.sleep

# The request counter (fyers-calls.json) is shared by every tool process on this computer, and
# several wake at the same moment after each 5-minute bar (a real run lost two of five entry.py
# watch processes to os.replace failing with WinError 32). Every read-modify-write of it runs under
# _counter_lock(): an exclusive lock file made with os.open(O_CREAT | O_EXCL), which is atomic on
# Windows and POSIX alike and needs only the standard library (fcntl is POSIX only, msvcrt is
# Windows only). A lock file older than LOCK_STALE seconds is taken to belong to a dead process.
# The lock is held only to RESERVE a send slot (see _spend); the pacing sleep happens after it is
# released, so one process waiting for the minute to roll never holds up the others.
# This file exists as three identical copies, kept in step by a test:
#   trader-alerts/fyers.py (master), trader-entry/fyers.py, trader-scanner/fyers.py
LOCK_STALE = 120          # seconds; a hold is a file read and write, milliseconds
LOCK_PATIENCE = 180       # seconds a caller waits for the lock before giving up
SLOT_LOOKAHEAD = 70       # seconds: reserved send slots this far ahead still count; farther is a bad entry
REPLACE_TRIES = 8         # os.replace attempts when Windows says the target is busy


def utc_now():
    return datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)


def _ts(utc):
    return (utc - EPOCH).total_seconds()


def _stamp(utc):
    return utc.strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------- files

def home():
    """Where the token lives: outside any repo, so it cannot be committed."""
    return os.environ.get("DAY_TRADER_INDIA_HOME") or os.path.join(os.path.expanduser("~"), ".day-trader-india")


def _token_path():
    return os.path.join(home(), "fyers-token.json")


def _calls_path():
    return os.path.join(home(), "fyers-calls.json")


def _read(path, tries=1):
    """A JSON object from a file, or {}. With tries above 1, a read that fails because the file is
    mid-swap (Windows: PermissionError; or half-written JSON) is retried briefly. A file that is
    simply not there is {} at once."""
    for attempt in range(tries):
        try:
            with open(path, encoding="utf-8") as fh:
                doc = json.load(fh)
            return doc if isinstance(doc, dict) else {}
        except FileNotFoundError:
            return {}
        except (OSError, ValueError):
            if attempt + 1 < tries:
                time.sleep(0.02 * (attempt + 1))
    return {}


class _counter_lock(object):
    """Cross-process lock around a read-modify-write of the request counter."""

    def __enter__(self):
        path = _calls_path() + ".lock"
        os.makedirs(os.path.dirname(path), exist_ok=True)
        start = time.time()
        while True:
            try:
                fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.close(fd)
                self.path = path
                return self
            except (FileExistsError, PermissionError):
                pass        # held by another process (PermissionError: Windows, file being deleted)
            try:
                if time.time() - os.path.getmtime(path) > LOCK_STALE:
                    os.unlink(path)     # its owner died without releasing it
                    continue
            except OSError:
                continue    # it was released between our two looks: try to take it now
            if time.time() - start > LOCK_PATIENCE:
                raise Unavailable("the Fyers request counter is locked by another process")
            time.sleep(0.005)

    def __exit__(self, *exc):
        for attempt in range(REPLACE_TRIES):
            try:
                os.unlink(self.path)
                return False
            except FileNotFoundError:
                return False
            except OSError:
                time.sleep(0.02 * (attempt + 1))
        return False


def _write(path, doc):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(doc, fh)
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    # Windows refuses os.replace (WinError 32 / 5) while another process has the target open.
    # The caller holds the counter lock; this short retry covers readers and the token file.
    for attempt in range(REPLACE_TRIES):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if attempt == REPLACE_TRIES - 1:
                raise
            _sleep(0.02 * (attempt + 1))


# ---------------------------------------------------------------- the token

def expiry_after(issued_utc):
    """The first 6:30 AM India time after the token was issued, as naive UTC."""
    local = issued_utc + IST
    cut = datetime.datetime.combine(local.date(), EXPIRES)
    if local >= cut:
        cut += datetime.timedelta(days=1)
    return cut - IST


def save_token(app_id, access_token, now=None):
    now = now or utc_now()
    _write(_token_path(), {"app_id": app_id, "access_token": access_token, "issued": _stamp(now)})
    return expiry_after(now)


def forget_token():
    try:
        os.remove(_token_path())
        return True
    except OSError:
        return False


def token_state(now=None):
    """(app_id, access_token, expires_utc), or Unavailable with the reason."""
    now = now or utc_now()
    doc = _read(_token_path())
    if not doc.get("access_token") or not doc.get("app_id") or not doc.get("issued"):
        raise Unavailable("no Fyers login on this computer: " + LOGIN_HINT)
    try:
        issued = datetime.datetime.strptime(doc["issued"], "%Y-%m-%dT%H:%M:%SZ")
    except (TypeError, ValueError):
        raise Unavailable("the saved Fyers login is unreadable: " + LOGIN_HINT)
    if doc.get("rejected"):
        raise Unavailable("Fyers refused the saved login: " + LOGIN_HINT)
    expires = expiry_after(issued)
    if now >= expires:
        raise Unavailable("the Fyers login expired at 6:30 AM India time: " + LOGIN_HINT)
    want = os.environ.get(ENV_APP)
    if want and want != doc["app_id"]:
        raise Unavailable("the saved Fyers login is for another app: " + LOGIN_HINT)
    return doc["app_id"], doc["access_token"], expires


def has_token(now=None):
    try:
        token_state(now)
        return True
    except Unavailable:
        return False


def _reject_token():
    doc = _read(_token_path())
    if doc:
        doc["rejected"] = True
        _write(_token_path(), doc)


# ---------------------------------------------------------------- the request budget

def _india_day(now):
    return (now + IST).date().isoformat()


def _calls(now, tries=1):
    doc = _read(_calls_path(), tries)
    if doc.get("day") != _india_day(now):
        doc = {"day": _india_day(now), "count": 0, "recent": [], "stopped": ""}
    return doc


def _spend(now=None, wait=False):
    """Count one request, or refuse it. Never lets this computer near a Fyers limit.
    With wait, a full minute is waited out instead of refused (the day's cap never is).

    The send slot is reserved under the lock and the sleep happens after it is released. The
    counter records the time each request is SENT (its slot), not the time it was asked for, so two
    requests are never closer than MIN_GAP apart whatever order the processes ask in (recording the
    ask time let two requests leave about 0.3 s apart)."""
    real = now is None
    with _counter_lock():
        ts, send_at = _spend_locked(now, wait)
    delay = send_at - (_ts(utc_now()) if real else ts)
    if delay > 0:
        _sleep(delay)


def _spend_locked(now, wait):
    """Reserve the next send slot in the counter. Returns (asked_at, send_at) in epoch seconds."""
    now = now or utc_now()
    doc = _calls(now)
    if doc.get("stopped"):
        raise Unavailable("Fyers said too many requests earlier today, so it is not asked again today")
    ts = _ts(now)
    recent = sorted(t for t in doc.get("recent", [])
                    if isinstance(t, (int, float)) and ts - 60 < t <= ts + SLOT_LOOKAHEAD)
    send_at = ts
    if len(recent) >= PER_MINUTE:
        if not wait:
            raise Unavailable("this minute's Fyers requests are used up (%d, kept under its limit of 50)" % PER_MINUTE)
        send_at = recent[len(recent) - PER_MINUTE] + 60 + 0.05   # when the oldest of the last PER_MINUTE ages out
    if doc.get("count", 0) >= PER_DAY:
        raise Unavailable("today's Fyers requests are used up (%d, kept under its limit of 5,000)" % PER_DAY)
    if recent:
        send_at = max(send_at, recent[-1] + MIN_GAP)
    recent.append(send_at)
    doc.update(count=doc.get("count", 0) + 1, recent=recent)
    _write(_calls_path(), doc)
    return ts, send_at


def _stop_today(now=None):
    now = now or utc_now()
    with _counter_lock():
        doc = _calls(now)
        doc["stopped"] = _stamp(now)
        _write(_calls_path(), doc)


def budget(now=None):
    """Today's counts. Read without the lock (it can be held for a moment), so a read that lands
    mid-swap is retried briefly rather than shown as zero."""
    now = now or utc_now()
    doc = _calls(now, tries=5)
    ts = _ts(now)
    return {"today": doc.get("count", 0), "per_day": PER_DAY, "per_minute": PER_MINUTE,
            "last_minute": len([t for t in doc.get("recent", []) if ts - 60 < t <= ts + 5]),
            "stopped": bool(doc.get("stopped"))}


# ---------------------------------------------------------------- HTTP

def _http(url, headers=None, body=None, timeout=20):
    """(HTTP status, text). A network failure is Unavailable. Nothing here logs a header."""
    h = {"User-Agent": UA, "Accept": "application/json"}
    h.update(headers or {})
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        h["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=h)
    try:
        with _urlopen(req, timeout=timeout) as r:
            return 200, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        try:
            text = e.read().decode("utf-8", "replace")
        except Exception:
            text = ""
        finally:
            try:
                e.close()
            except Exception:
                pass
        return e.code, text
    except urllib.error.URLError as e:
        raise Unavailable("could not reach Fyers: %s" % (e.reason,))
    except OSError as e:
        raise Unavailable("network error talking to Fyers: %s" % (e,))


def _answer(status, text):
    try:
        doc = json.loads(text)
    except ValueError:
        doc = None
    if not isinstance(doc, dict):
        raise Unavailable("Fyers answered HTTP %d with something that is not JSON" % status)
    return doc


def _data(url, now=None, wait=False):
    """One authorised GET to a data endpoint -> the JSON answer."""
    app_id, token, _ = token_state(now)
    _spend(now, wait)
    status, text = _http(url, {"Authorization": "%s:%s" % (app_id, token)})
    if status == 429:
        _stop_today(now)
        raise Unavailable("Fyers said too many requests (HTTP 429): not asking it again today")
    doc = _answer(status, text)
    code = doc.get("code")
    if code == -429:
        _stop_today(now)
        raise Unavailable("Fyers said too many requests (code -429): not asking it again today")
    if status in (401, 403) or code in AUTH_ERRORS:
        _reject_token()
        raise Unavailable("Fyers refused the login (HTTP %d, code %s): %s" % (status, code, LOGIN_HINT))
    if status != 200:
        raise Unavailable("Fyers answered HTTP %d: %s" % (status, str(doc.get("message") or "no message")[:120]))
    return doc


# ---------------------------------------------------------------- symbols

def fyers_symbol(sym):
    """HCLTECH.NS or HCLTECH -> NSE:HCLTECH-EQ (Fyers' EXCHANGE:SYMBOL-SERIES form)."""
    s = str(sym).strip().upper()
    if s.startswith("NSE:"):
        return s
    if s.endswith(".BO") or ":" in s:
        raise Unavailable("only NSE symbols are read from Fyers here, not %s" % s)
    if s.endswith(".NS"):
        s = s[:-3]
    if not s:
        raise Unavailable("no symbol")
    return "NSE:%s-EQ" % s


def pack_symbol(fy):
    """NSE:HCLTECH-EQ -> HCLTECH.NS, the pack's own form."""
    s = str(fy).strip().upper()
    if s.startswith("NSE:"):
        s = s[4:]
    if s.endswith("-EQ"):
        s = s[:-3]
    return s + ".NS"


def _q(text):
    """For a URL: keeps : and , as the Fyers docs write them, encodes & (M&M -> M%26M)."""
    return urllib.parse.quote(text, safe=":,-")


# ---------------------------------------------------------------- quotes

def quotes_url(fy_symbols):
    return "%s?symbols=%s" % (QUOTES_URL, _q(",".join(fy_symbols)))


def parse_quotes(doc, stamp):
    """A Fyers quotes answer -> ({SYMBOL.NS: quote}, [errors]), in the alerts tool's shape."""
    if doc.get("s") != "ok" or not isinstance(doc.get("d"), list):
        raise Unavailable("Fyers quotes said: %s (code %s)" % (str(doc.get("message") or "no data")[:120], doc.get("code")))
    quotes, errors = {}, []
    for row in doc["d"]:
        if not isinstance(row, dict):
            continue
        name = row.get("n") or ""
        v = row.get("v") if isinstance(row.get("v"), dict) else {}
        sym = pack_symbol(name)
        price = v.get("lp")
        if row.get("s") != "ok" or not isinstance(price, (int, float)) or price <= 0:
            errors.append("Fyers has no quote for %s: %s" % (sym, str(v.get("errmsg") or row.get("s") or "no price")[:80]))
            continue

        def num(key):
            x = v.get(key)
            return float(x) if isinstance(x, (int, float)) and x > 0 else None

        quotes[sym] = {"symbol": sym, "price": float(price), "open": num("open_price"), "high": num("high_price"),
                       "low": num("low_price"), "prev_close": num("prev_close_price"), "time": stamp,
                       "bid": num("bid"), "ask": num("ask"), "currency": "INR", "source": "fyers"}
    return quotes, errors


def quotes(symbols, now=None):
    """({SYMBOL.NS: quote}, [errors]) for NSE symbols, 50 to a request.
    A quote's "time" is when it was read here: Fyers' answer carries no trade time."""
    wanted, errors = [], []
    for s in symbols:
        try:
            fy = fyers_symbol(s)
            if fy not in wanted:
                wanted.append(fy)
        except Unavailable as e:
            errors.append(str(e))
    out = {}
    for i in range(0, len(wanted), MAX_SYMBOLS):
        doc = _data(quotes_url(wanted[i:i + MAX_SYMBOLS]), now)
        got, errs = parse_quotes(doc, _stamp(utc_now() if now is None else now))
        out.update(got)
        errors.extend(errs)
    for fy in wanted:
        s = pack_symbol(fy)
        if s not in out and not any(s in e for e in errors):
            errors.append("Fyers sent no quote for %s" % s)
    return out, errors


# ---------------------------------------------------------------- candles

def history_url(fy_symbol, interval, day):
    d = day.isoformat()
    return "%s?symbol=%s&resolution=%s&date_format=1&range_from=%s&range_to=%s" % (
        HISTORY_URL, _q(fy_symbol), RESOLUTION[interval], d, d)


def parse_history(doc, sym, interval, day, now):
    """A Fyers history answer -> the chart the entry timer reads:
    {symbol, meta, bars: [{t, o, h, l, c, v}], prev_close, data_time, source}.

    Fyers documents a candle as [epoch, open, high, low, close, volume]. The bars
    are only used if their times make sense for an NSE session: every bar inside
    9:15 to 15:30 India time must start on the bar grid, none may start in the
    future, and an answer with candles must have some inside the session.
    Anything else is Unavailable, and the caller uses Yahoo."""
    s = doc.get("s")
    if s == "no_data":
        candles = []
    elif s == "ok" and isinstance(doc.get("candles"), list):
        candles = doc["candles"]
    else:
        raise Unavailable("Fyers candles said: %s (code %s)" % (str(doc.get("message") or s or "no data")[:120],
                                                               doc.get("code")))
    step = STEP[interval]
    open_dt = datetime.datetime.combine(day, OPEN)
    close_dt = datetime.datetime.combine(day, CLOSE)
    now_ts = _ts(now)
    bars = []
    for c in candles:
        if not isinstance(c, (list, tuple)) or len(c) < 6 or not all(isinstance(x, (int, float)) for x in c[:6]):
            raise Unavailable("Fyers sent a candle in a shape this tool does not know")
        t = int(c[0])
        if t > now_ts + 60:
            raise Unavailable("Fyers sent a candle that starts in the future, so its times cannot be trusted")
        local = EPOCH + datetime.timedelta(seconds=t) + IST
        if not (open_dt <= local < close_dt):
            continue
        if int((local - open_dt).total_seconds()) % step:
            raise Unavailable("Fyers candles are not on the NSE %s grid" % interval)
        bars.append({"t": t, "o": float(c[1]), "h": float(c[2]), "l": float(c[3]), "c": float(c[4]),
                     "v": int(c[5])})
    if candles and not bars:
        raise Unavailable("Fyers sent candles, but none inside the 9:15 to 15:30 session of %s" % day.isoformat())
    bars.sort(key=lambda b: b["t"])
    return {"symbol": sym, "meta": {"dataGranularity": interval, "symbol": sym, "currency": "INR"},
            "bars": bars, "prev_close": None, "data_time": int(now_ts), "source": "fyers"}


def history(sym, interval, day, now=None, wait=False):
    """One session's bars for one NSE symbol. The bar still forming is included, as Yahoo's is.
    wait=True waits for the next minute when this minute's requests are used up."""
    if interval not in RESOLUTION:
        raise Unavailable("Fyers bars here are 1m or 5m, not %s" % interval)
    fy = fyers_symbol(sym)
    doc = _data(history_url(fy, interval, day), now, wait)
    return parse_history(doc, pack_symbol(fy), interval, day, utc_now() if now is None else now)


# ---------------------------------------------------------------- login

def credentials(need_secret=True):
    """(app_id, secret, redirect_uri) from the environment. The secret is never printed."""
    app_id = (os.environ.get(ENV_APP) or "").strip()
    secret = (os.environ.get(ENV_SECRET) or "").strip()
    redirect = (os.environ.get(ENV_REDIRECT) or "").strip()
    missing = [n for n, v in ((ENV_APP, app_id), (ENV_SECRET, secret if need_secret else "x"),
                              (ENV_REDIRECT, redirect)) if not v]
    if missing:
        raise Unavailable("set %s first (Windows: setx NAME \"value\", then open a new terminal). "
                          "FYERS_REDIRECT_URI is the redirect URL you gave the app in the Fyers API dashboard, "
                          "letter for letter" % ", ".join(missing))
    return app_id, secret, redirect


def login_url(app_id, redirect_uri, state):
    return AUTH_URL + "?" + urllib.parse.urlencode(
        {"client_id": app_id, "redirect_uri": redirect_uri, "response_type": "code", "state": state})


def app_id_hash(app_id, secret):
    """SHA-256 of app_id:app_secret, which is what Fyers takes in place of the secret."""
    return hashlib.sha256(("%s:%s" % (app_id, secret)).encode("utf-8")).hexdigest()


def auth_code_from(text, state):
    """The auth code from what came back: the redirect address, its query, or a bare code.
    A redirect address must carry the state this login sent."""
    text = (text or "").strip()
    if not text:
        raise Unavailable("nothing was pasted")
    query = urllib.parse.urlparse(text).query if "://" in text else (text[1:] if text.startswith("?") else text)
    if "auth_code=" not in query:
        if "=" in text or "/" in text or " " in text:
            raise Unavailable("that address has no auth_code in it: the login did not finish")
        return text     # a bare code, copied from the redirect page
    q = urllib.parse.parse_qs(query)
    if (q.get("s") or ["ok"])[0] != "ok":
        raise Unavailable("Fyers did not log you in: %s" % (q.get("message") or ["no reason given"])[0][:120])
    if (q.get("state") or [""])[0] != state:
        raise Unavailable("the redirect's state does not match this login: start again with fyers.py login")
    code = (q.get("auth_code") or [""])[0]
    if not code:
        raise Unavailable("the redirect carried an empty auth_code")
    return code


def exchange(app_id, secret, code):
    """auth code -> access token. One request, not counted in the data budget."""
    status, text = _http(TOKEN_URL, body={"grant_type": "authorization_code",
                                          "appIdHash": app_id_hash(app_id, secret), "code": code})
    doc = _answer(status, text)
    token = doc.get("access_token")
    if doc.get("s") != "ok" or not token:
        raise Unavailable("Fyers did not give a token (HTTP %d, code %s): %s" % (
            status, doc.get("code"), str(doc.get("message") or "no message")[:120]))
    return token


def loopback(redirect_uri):
    """(host, port) when this tool can catch the redirect itself, else None."""
    u = urllib.parse.urlparse(redirect_uri)
    if u.scheme == "http" and u.hostname in ("127.0.0.1", "localhost") and u.port:
        return u.hostname, u.port
    return None


def wait_for_redirect(host, port, timeout=LOGIN_WAIT):
    """Serve one request on the loopback address and hand back its query string."""
    got = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            query = urllib.parse.urlparse(self.path).query
            if "auth_code=" in query or "s=" in query:
                got["query"] = query
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"<p>Day Trader India: the Fyers login came back. You can close this tab.</p>")

        def log_message(self, *args):    # the request line holds the auth code: log nothing
            pass

    try:
        server = http.server.HTTPServer((host, port), Handler)
    except OSError as e:
        raise Unavailable("could not listen on %s:%d for the redirect: %s" % (host, port, e))
    try:
        end = time.time() + timeout
        while "query" not in got and time.time() < end:
            server.timeout = max(1, min(5, end - time.time()))
            server.handle_request()
    finally:
        server.server_close()
    if "query" not in got:
        raise Unavailable("no redirect came back in %d minutes: start again with fyers.py login" % (timeout // 60))
    return got["query"]


def cmd_login(a):
    app_id, secret, redirect = credentials()
    state = secrets.token_urlsafe(16)
    url = login_url(app_id, redirect, state)
    print("Fyers login for app %s. Log in with your Fyers ID, PIN and TOTP in the browser." % app_id)
    print("If the browser does not open, open this address yourself:")
    print(url)
    if not a.no_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass
    lb = loopback(redirect)
    if lb:
        print("Waiting for the redirect on %s:%d ..." % lb, flush=True)
        came = wait_for_redirect(lb[0], lb[1])
    else:
        print("After you log in, the browser lands on your redirect URL (%s)." % redirect)
        print("Copy that page's full address, or just the auth code, and paste it here.")
        print("Paste it in this terminal only, never in a chat.")
        try:
            came = input("> ")
        except EOFError:
            raise Unavailable("nothing to read: run fyers.py login in your own terminal, where you can paste")
    token = exchange(app_id, secret, auth_code_from(came, state))
    expires = save_token(app_id, token)
    print("Logged in. The token is saved in %s and is good until %s IST."
          % (home(), (expires + IST).strftime("%Y-%m-%d %H:%M")))
    print("It reads prices only here. Nothing in this pack places an order.")
    return 0


def cmd_status(a):
    b = budget()
    try:
        app_id, _, expires = token_state()
    except Unavailable as e:
        print("Fyers: %s" % e)
        return 1
    print("Fyers: logged in for app %s, good until %s IST." % (app_id, (expires + IST).strftime("%Y-%m-%d %H:%M")))
    print("Requests today: %d of %d, %d in the last minute (of %d).%s" % (
        b["today"], b["per_day"], b["last_minute"], b["per_minute"],
        " Fyers said too many requests today: not asked again until tomorrow." if b["stopped"] else ""))
    return 0


def cmd_logout(a):
    print("Removed the saved Fyers token." if forget_token() else "No saved Fyers token.")
    return 0


def cmd_quote(a):
    got, errors = quotes(a.symbols)
    for s, q in got.items():
        chg = ""
        if q.get("prev_close"):
            chg = " (%+.2f%% vs prev close Rs %.2f)" % (100.0 * (q["price"] / q["prev_close"] - 1), q["prev_close"])
        print("%-14s Rs %.2f%s  read %s  [fyers]" % (s, q["price"], chg, q["time"]))
    for e in errors:
        print("error: " + e)
    return 0 if got else 1


def cmd_bars(a):
    now = utc_now()
    day = datetime.datetime.strptime(a.date, "%Y-%m-%d").date() if a.date else (now + IST).date()
    ch = history(a.symbol, a.interval, day)
    print("%s: %d %s bar(s) on %s from Fyers." % (ch["symbol"], len(ch["bars"]), a.interval, day.isoformat()))
    for b in ch["bars"][-a.last:]:
        local = EPOCH + datetime.timedelta(seconds=b["t"]) + IST
        print("  %s IST  open %.2f  high %.2f  low %.2f  close %.2f  volume %d"
              % (local.strftime("%H:%M"), b["o"], b["h"], b["l"], b["c"], b["v"]))
    return 0 if ch["bars"] else 1


def main(argv=None):
    ap = argparse.ArgumentParser(description="Fyers market data for Day Trader India: login, quotes, candles.")
    sub = ap.add_subparsers(dest="cmd")
    p = sub.add_parser("login", help="today's login (your PIN and TOTP go in the browser, not here)")
    p.add_argument("--no-browser", action="store_true", help="print the address, do not open it")
    sub.add_parser("status", help="is there a login for today, and the request count")
    sub.add_parser("logout", help="delete the saved token")
    p = sub.add_parser("quote", help="a live quote, to see that the login works")
    p.add_argument("symbols", nargs="+")
    p = sub.add_parser("bars", help="a session's bars, to see that the login works")
    p.add_argument("symbol")
    p.add_argument("--interval", choices=sorted(RESOLUTION), default="5m")
    p.add_argument("--date", help="YYYY-MM-DD (default today, India time)")
    p.add_argument("--last", type=int, default=5, help="how many bars to print (default 5)")
    a = ap.parse_args(argv)
    if not a.cmd:
        ap.print_help()
        return 1
    try:
        return {"login": cmd_login, "status": cmd_status, "logout": cmd_logout, "quote": cmd_quote,
                "bars": cmd_bars}[a.cmd](a)
    except Unavailable as e:
        print("fyers.py: %s" % e, file=sys.stderr)
        return 1
    except ValueError as e:
        print("fyers.py: %s" % e, file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("fyers.py: stopped.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
