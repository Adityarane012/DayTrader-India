"""The Fyers request counter under many processes at once.

In live use two of five concurrent `entry.py watch` processes died with
`PermissionError: [WinError 32]` from os.replace in fyers.py, because several
woke at the same moment and rewrote ~/.day-trader-india/fyers-calls.json
together. Here, for each of the three copies of fyers.py, 8 real processes each
count 200 requests as fast as they can against a temporary
DAY_TRADER_INDIA_HOME (the three groups run at the same time, to keep the test
short). The file must end at exactly 1,600 and no process may crash. No
network, no token, no real home folder.

That full test costs about 30 s, so it is SLOW and off by default. The default
suite runs a small smoke version instead (4 processes x 30 counts on the
master copy trader-alerts/fyers.py; the other two copies are checked to be
byte-identical by another test). To run the full one, set DAYTRADER_SLOW_TESTS:

    bash:        DAYTRADER_SLOW_TESTS=1 python -m unittest discover -s tests -p "test_fyers_counter.py"
    PowerShell:  $env:DAYTRADER_SLOW_TESTS = "1"; python -m unittest discover -s tests -p "test_fyers_counter.py"

Run it after any change to the counter, the lock or the pacing in fyers.py.
(The project is standard-library only, so this is an environment switch, not a
pytest marker.)
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

from _load import ROOT

PROCS, EACH = 8, 200
SMOKE_PROCS, SMOKE_EACH = 4, 30
COPIES = ("trader-alerts", "trader-entry", "trader-scanner")
SLOW = bool(os.environ.get("DAYTRADER_SLOW_TESTS"))

WORKER = r'''
import datetime, importlib.util, sys
spec = importlib.util.spec_from_file_location("fyers_under_test", sys.argv[1])
f = importlib.util.module_from_spec(spec)
spec.loader.exec_module(f)
f._sleep = lambda s: None            # no pacing: this test is about the file, not the clock
f.MIN_GAP = 0
f.PER_MINUTE = f.PER_DAY = 10 ** 9
now = datetime.datetime(2026, 11, 16, 4, 0)
for _ in range(int(sys.argv[2])):
    f._spend(now)
'''


class CounterRace(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="dti-counter-")
        self.addCleanup(shutil.rmtree, self.home, True)

    def start(self, folder, procs, each):
        home = os.path.join(self.home, folder)
        os.makedirs(home)
        script = os.path.join(self.home, "worker.py")
        env = dict(os.environ, DAY_TRADER_INDIA_HOME=home)
        path = os.path.join(ROOT, folder, "fyers.py")
        return [subprocess.Popen([sys.executable, script, path, str(each)], env=env,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE) for _ in range(procs)]

    def hammer(self, copies, procs, each):
        with open(os.path.join(self.home, "worker.py"), "w", encoding="utf-8") as fh:
            fh.write(WORKER)
        running = {folder: self.start(folder, procs, each) for folder in copies}
        for folder, ps in running.items():
            errors = []
            for p in ps:
                _, err = p.communicate(timeout=300)
                if p.returncode != 0:
                    errors.append(err.decode("utf-8", "replace").strip().splitlines()[-1:])
            self.assertEqual(errors, [], folder)
            calls = os.path.join(self.home, folder, "fyers-calls.json")
            with open(calls, encoding="utf-8") as fh:
                self.assertEqual(json.load(fh)["count"], procs * each, folder)
            self.assertFalse(os.path.exists(calls + ".lock"), folder)

    def test_smoke_no_request_is_lost_and_no_process_dies(self):
        self.hammer(COPIES[:1], SMOKE_PROCS, SMOKE_EACH)

    @unittest.skipUnless(SLOW, "slow (about 30 s): set DAYTRADER_SLOW_TESTS=1 to run it")
    def test_slow_all_three_copies_8_processes_x_200(self):
        self.hammer(COPIES, PROCS, EACH)


if __name__ == "__main__":
    unittest.main()
