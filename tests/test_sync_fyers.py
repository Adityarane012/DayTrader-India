"""scripts/sync_fyers.py: copies the master fyers.py over its copies. Offline, in a temp folder:
the real repo's files are never touched."""
import contextlib
import importlib.util
import io
import os
import shutil
import tempfile
import unittest

from _load import ROOT

spec = importlib.util.spec_from_file_location("sync_fyers", os.path.join(ROOT, "scripts", "sync_fyers.py"))
sf = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sf)


def run(argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = sf.main(argv)
    return code, out.getvalue()


class Sync(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="dti-sync-")
        self.addCleanup(shutil.rmtree, self.root, True)
        self.put("trader-alerts/fyers.py", b"MASTER v2\n")
        self.put("trader-entry/fyers.py", b"old\n")
        self.put("trader-scanner/fyers.py", b"MASTER v2\n")

    def put(self, rel, data):
        path = os.path.join(self.root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as fh:
            fh.write(data)

    def get(self, rel):
        with open(os.path.join(self.root, rel), "rb") as fh:
            return fh.read()

    def go(self, *extra):
        return run(["--root", self.root] + list(extra))

    def test_check_reports_a_difference_and_writes_nothing(self):
        code, out = self.go("--check")
        self.assertEqual(code, 1)
        self.assertIn("trader-entry", out)
        self.assertNotIn("trader-scanner", out)               # that copy already matches
        self.assertIn("python scripts/sync_fyers.py", out)
        self.assertEqual(self.get("trader-entry/fyers.py"), b"old\n")

    def test_it_copies_the_master_over_only_what_differs(self):
        code, out = self.go()
        self.assertEqual(code, 0)
        self.assertEqual(self.get("trader-entry/fyers.py"), b"MASTER v2\n")
        self.assertIn("trader-entry", out)
        self.assertEqual(self.go("--check")[0], 0)
        code, out = self.go()
        self.assertIn("already matches", out)

    def test_the_master_is_never_changed(self):
        self.put("trader-alerts/fyers.py", b"MASTER v3\n")
        self.go()
        self.assertEqual(self.get("trader-alerts/fyers.py"), b"MASTER v3\n")
        for rel in ("trader-entry/fyers.py", "trader-scanner/fyers.py"):
            self.assertEqual(self.get(rel), b"MASTER v3\n")

    def test_bytes_are_copied_exactly_including_line_endings(self):
        self.put("trader-alerts/fyers.py", b"a\r\nb\nc\r\n\xc3\xa9")      # mixed endings and UTF-8
        self.go()
        self.assertEqual(self.get("trader-entry/fyers.py"), b"a\r\nb\nc\r\n\xc3\xa9")

    def test_installed_copies_are_kept_in_step_when_they_exist(self):
        self.put(".claude/skills/trader-alerts/fyers.py", b"stale\n")
        self.put(".claude/skills/trader-scanner/fyers.py", b"stale\n")      # no trader-entry folder installed
        code, out = self.go("--check")
        self.assertEqual(code, 1)
        self.assertIn(os.path.join(".claude", "skills", "trader-alerts", "fyers.py"), out)
        self.go()
        self.assertEqual(self.get(".claude/skills/trader-alerts/fyers.py"), b"MASTER v2\n")
        self.assertEqual(self.get(".claude/skills/trader-scanner/fyers.py"), b"MASTER v2\n")
        self.assertFalse(os.path.exists(os.path.join(self.root, ".claude", "skills", "trader-entry")))

    def test_without_an_installed_folder_nothing_is_created_there(self):
        self.go()
        self.assertFalse(os.path.exists(os.path.join(self.root, ".claude")))

    def test_a_missing_master_cannot_be_synced(self):
        os.remove(os.path.join(self.root, "trader-alerts", "fyers.py"))
        code, out = self.go()
        self.assertEqual(code, 2)
        self.assertIn("CANNOT SYNC", out)

    def test_a_missing_copy_is_created(self):
        os.remove(os.path.join(self.root, "trader-scanner", "fyers.py"))
        self.assertEqual(self.go("--check")[0], 1)
        self.go()
        self.assertEqual(self.get("trader-scanner/fyers.py"), b"MASTER v2\n")

    def test_the_real_repo_is_in_step(self):
        code, out = run(["--check"])
        self.assertEqual(code, 0, out)


if __name__ == "__main__":
    unittest.main()
