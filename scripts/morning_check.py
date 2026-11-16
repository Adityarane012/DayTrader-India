#!/usr/bin/env python
"""Morning guard for Day Trader India. Standard library only.

    python scripts/morning_check.py          # run it at 9:00 IST

Prints exactly one line and exits:

  OK ...                    0   a trading day, Fyers login good for the session
  MARKET CLOSED TODAY ...   0   weekend or NSE holiday (see CLOSED_EXIT below)
  MARKET CLOSED FOR THE DAY 0   a trading day, run at 15:30 IST or later
  LOG IN TO FYERS NOW ...   2   no login today, or it expired; you log in
  CANNOT CHECK ...          3   the clock or the status check failed or was unreadable

It reads two things, both from the pack's own tools, as subprocesses:

  python trader-alerts/alerts.py clock --json   the NSE clock and the 2026 holiday
                                                list (one calendar, no second copy
                                                to drift out of date)
  python trader-entry/fyers.py status           the saved login. status reads only
                                                the local token file and the local
                                                request counter. It makes no Fyers
                                                request, so it costs none of the
                                                5,000 a day.

India time comes from alerts.py (UTC plus 5:30, never the computer's zone). This
script never runs `fyers.py login`, never opens the token file and never prints
the token: it prints only fixed words and the expiry time that status reports.
"""
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
ALERTS = os.path.join(ROOT, "trader-alerts", "alerts.py")
FYERS = os.path.join(ROOT, "trader-entry", "fyers.py")

LOGIN_COMMAND = "python trader-entry/fyers.py login"
LATE_AFTER = (9, 30)      # the opening range closes; the first entry bar is 9:35
CLOSE_AT = (15, 30)       # the NSE session ends: nothing left to log in for
LOGIN_EXIT = 2
CANNOT_CHECK_EXIT = 3
CLOSED_EXIT = 0           # a closed market is not a failure; set to 1 to make it one

GOOD_UNTIL = re.compile(r"logged in for app \S+, good until (\d{4}-\d\d-\d\d) (\d\d:\d\d) IST")
# the ways fyers.py status says "no usable login" (token_state in fyers.py)
NO_LOGIN_WORDS = ("no Fyers login", "expired", "refused the saved login",
                  "saved Fyers login is unreadable", "saved Fyers login is for another app")


def run_clock():
    """The alerts.py clock as a dict. Raises on any failure."""
    p = subprocess.run([sys.executable, ALERTS, "clock", "--json"], capture_output=True,
                       text=True, timeout=30, cwd=ROOT)   # exit 1 just means closed
    return json.loads(p.stdout)


def run_status():
    """(exit code, stdout) of fyers.py status. Raises on any failure to run it."""
    p = subprocess.run([sys.executable, FYERS, "status"], capture_output=True,
                       text=True, timeout=30, cwd=ROOT)
    return p.returncode, p.stdout


def clock_part(now_ist):
    return now_ist.split(" ")[1]


def is_late(now_ist):
    h, m = (int(x) for x in clock_part(now_ist).split(":"))
    return (h, m) >= LATE_AFTER


def is_over(now_ist):
    """True from 15:30 IST on: the session has ended."""
    h, m = (int(x) for x in clock_part(now_ist).split(":"))
    return (h, m) >= CLOSE_AT


def check(clock, status):
    """(line, exit code). clock is the alerts.py clock dict; status is (code, text)."""
    try:
        now = clock["now_ist"]
        reason = clock["reason"]
        trading = "opens" in clock
    except (KeyError, TypeError):
        return "CANNOT CHECK: the NSE clock gave an answer I could not read.", CANNOT_CHECK_EXIT
    if not trading:
        return "MARKET CLOSED TODAY (%s): %s IST. No login needed." % (reason, now), CLOSED_EXIT
    if is_over(now):
        return "MARKET CLOSED FOR THE DAY: %s IST, the session ended at 15:30. No login needed." % clock_part(now), CLOSED_EXIT
    code, text = status
    text = text or ""
    m = GOOD_UNTIL.search(text)
    if code == 0 and m:
        late = ""
        if is_late(now):
            late = " Late: the first entry is 9:35."
        return ("OK: %s IST, logged in, good until %s IST on %s.%s"
                % (clock_part(now), m.group(2), m.group(1), late)), 0
    if any(w in text for w in NO_LOGIN_WORDS):
        why = "the Fyers login expired" if "expired" in text else "there is no Fyers login today"
        late = " Late: the first entry is 9:35." if is_late(now) else ""
        return ("LOG IN TO FYERS NOW: %s (%s IST). In your own terminal run: %s.%s"
                % (why, clock_part(now), LOGIN_COMMAND, late)), LOGIN_EXIT
    return ("CANNOT CHECK: fyers.py status gave an answer I could not read. "
            "Run: python trader-entry/fyers.py status"), CANNOT_CHECK_EXIT


def main(clock=run_clock, status=run_status):
    """clock and status are injectable so tests need no subprocess."""
    try:
        c = clock()
    except Exception:
        print("CANNOT CHECK: the NSE clock did not run. Run: python trader-alerts/alerts.py clock")
        return CANNOT_CHECK_EXIT
    try:
        trading = isinstance(c, dict) and "opens" in c
        over = trading and isinstance(c.get("now_ist"), str) and is_over(c["now_ist"])
        s = status() if trading and not over else (0, "")
    except Exception:
        print("CANNOT CHECK: fyers.py status did not run. Run: python trader-entry/fyers.py status")
        return CANNOT_CHECK_EXIT
    line, code = check(c, s)
    print(line)
    return code


if __name__ == "__main__":
    sys.exit(main())
