"""The morning guard (scripts/morning_check.py), offline.

The clock and the Fyers status are injected: no subprocess runs, no token or
~/.day-trader-india file is touched. The status lines below are the exact shape
fyers.py cmd_status and token_state print (read from trader-entry/fyers.py).
The clock dicts are what alerts.py market_status builds, from the real code.
"""
import contextlib
import importlib.util
import io
import os
import unittest

from _load import ROOT, load

spec = importlib.util.spec_from_file_location("morning_check", os.path.join(ROOT, "scripts", "morning_check.py"))
mc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mc)
alerts = load("trader-alerts", "alerts")

LOGGED_IN = (0, "Fyers: logged in for app ABC-100, good until 2026-11-17 06:30 IST.\n"
                "Requests today: 0 of 4500, 0 in the last minute (of 40).\n")
NO_LOGIN = (1, "Fyers: no Fyers login on this computer: log in with: python fyers.py login\n")
EXPIRED = (1, "Fyers: the Fyers login expired at 6:30 AM India time: log in with: python fyers.py login\n")


def clock_at(ist_text):
    """The real alerts.py clock answer for an India time like '2026-11-16 09:00'."""
    return alerts.market_status(alerts.parse_now(ist_text))


def run(clock, status):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = mc.main(clock=lambda: clock, status=(status if callable(status) else lambda: status))
    lines = out.getvalue().splitlines()
    return code, lines


class Guard(unittest.TestCase):
    def test_logged_in_is_ok(self):
        code, lines = run(clock_at("2026-11-16 09:00"), LOGGED_IN)
        self.assertEqual(code, 0)
        self.assertEqual(len(lines), 1)
        self.assertTrue(lines[0].startswith("OK"), lines[0])
        self.assertIn("09:00 IST", lines[0])
        self.assertIn("logged in, good until 06:30 IST", lines[0])
        self.assertNotIn("Late", lines[0])

    def test_no_login_today(self):
        code, lines = run(clock_at("2026-11-16 09:00"), NO_LOGIN)
        self.assertEqual(code, mc.LOGIN_EXIT)
        self.assertNotEqual(code, 0)
        self.assertEqual(len(lines), 1)
        self.assertTrue(lines[0].startswith("LOG IN TO FYERS NOW"), lines[0])
        self.assertIn("python trader-entry/fyers.py login", lines[0])

    def test_login_expired(self):
        code, lines = run(clock_at("2026-11-16 09:00"), EXPIRED)
        self.assertEqual(code, mc.LOGIN_EXIT)
        self.assertTrue(lines[0].startswith("LOG IN TO FYERS NOW"), lines[0])
        self.assertIn("expired", lines[0])
        self.assertIn("python trader-entry/fyers.py login", lines[0])

    def test_weekend(self):
        code, lines = run(clock_at("2026-11-15 09:00"), NO_LOGIN)   # a Sunday
        self.assertEqual(code, 0)
        self.assertEqual(len(lines), 1)
        self.assertTrue(lines[0].startswith("MARKET CLOSED TODAY"), lines[0])
        self.assertIn("weekend", lines[0])

    def test_2026_holiday(self):
        code, lines = run(clock_at("2026-11-10 09:00"), NO_LOGIN)   # Tuesday
        self.assertEqual(code, 0)
        self.assertTrue(lines[0].startswith("MARKET CLOSED TODAY"), lines[0])
        self.assertIn("Diwali-Balipratipada", lines[0])

    def test_closed_day_never_asks_for_status(self):
        def boom():
            raise AssertionError("status must not run on a closed day")
        code, _ = run(clock_at("2026-12-25 09:00"), boom)
        self.assertEqual(code, mc.CLOSED_EXIT)

    def test_run_late_warns_and_still_ok(self):
        code, lines = run(clock_at("2026-11-16 10:40"), LOGGED_IN)
        self.assertEqual(code, 0)
        self.assertTrue(lines[0].startswith("OK"), lines[0])
        self.assertIn("late: the first entry is 9:35".lower(), lines[0].lower())

    def test_run_late_and_no_login_warns_too(self):
        code, lines = run(clock_at("2026-11-16 09:30"), NO_LOGIN)
        self.assertEqual(code, mc.LOGIN_EXIT)
        self.assertIn("late: the first entry is 9:35", lines[0].lower())

    def test_not_late_at_9_29(self):
        _, lines = run(clock_at("2026-11-16 09:29"), LOGGED_IN)
        self.assertNotIn("late", lines[0].lower())

    def test_after_the_close_says_closed_for_the_day_not_late(self):
        def boom():
            raise AssertionError("status must not run after the close")
        for t in ("2026-11-16 15:30", "2026-11-16 19:16"):
            code, lines = run(clock_at(t), boom)
            self.assertEqual(code, mc.CLOSED_EXIT, t)
            self.assertEqual(len(lines), 1)
            self.assertTrue(lines[0].startswith("MARKET CLOSED FOR THE DAY"), lines[0])
            self.assertNotIn("late", lines[0].lower())
            self.assertNotIn("LOG IN", lines[0])

    def test_still_late_not_closed_at_15_29(self):
        code, lines = run(clock_at("2026-11-16 15:29"), LOGGED_IN)
        self.assertTrue(lines[0].startswith("OK"), lines[0])
        self.assertIn("late", lines[0].lower())

    def test_status_subprocess_fails(self):
        def boom():
            raise OSError("no python")
        code, lines = run(clock_at("2026-11-16 09:00"), boom)
        self.assertEqual(code, mc.CANNOT_CHECK_EXIT)
        self.assertEqual(len(lines), 1)
        self.assertTrue(lines[0].startswith("CANNOT CHECK"), lines[0])

    def test_status_crashes_with_traceback_text(self):
        code, lines = run(clock_at("2026-11-16 09:00"), (1, "Traceback (most recent call last):\n  boom\n"))
        self.assertEqual(code, mc.CANNOT_CHECK_EXIT)
        self.assertTrue(lines[0].startswith("CANNOT CHECK"), lines[0])
        self.assertNotIn("Traceback", lines[0])

    def test_unparseable_status(self):
        for bad in ((0, "all good, trust me\n"), (0, ""), (0, None)):
            code, lines = run(clock_at("2026-11-16 09:00"), bad)
            self.assertEqual(code, mc.CANNOT_CHECK_EXIT, bad)
            self.assertTrue(lines[0].startswith("CANNOT CHECK"), lines[0])

    def test_exit_zero_with_a_no_login_message_is_still_login(self):
        # the words decide, not only the exit code
        code, _ = run(clock_at("2026-11-16 09:00"), (0, NO_LOGIN[1]))
        self.assertEqual(code, mc.LOGIN_EXIT)

    def test_clock_fails_or_is_unreadable(self):
        def boom():
            raise ValueError("not json")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(mc.main(clock=boom, status=lambda: LOGGED_IN), mc.CANNOT_CHECK_EXIT)
            self.assertEqual(mc.main(clock=lambda: {"weird": 1}, status=lambda: LOGGED_IN), mc.CANNOT_CHECK_EXIT)
        self.assertEqual(len(out.getvalue().splitlines()), 2)

    def test_no_token_is_ever_printed(self):
        secret = "eyJSECRETTOKEN"
        _, lines = run(clock_at("2026-11-16 09:00"), (0, LOGGED_IN[1] + "access_token=" + secret + "\n"))
        self.assertNotIn(secret, " ".join(lines))

    def test_uses_the_pack_clock_and_never_runs_login(self):
        with open(os.path.join(ROOT, "scripts", "morning_check.py"), encoding="utf-8") as fh:
            src = fh.read()
        self.assertIn('"status"]', src)
        self.assertNotIn('"login"]', src)
        self.assertNotIn("fyers-token", src)
        self.assertNotIn("datetime", src)   # India time comes from alerts.py, not this file


if __name__ == "__main__":
    unittest.main()
