"""scripts/make_public_snapshot.py: builds the clean public repo. Offline, in temp folders, on a
throwaway source repo (never this one). Every private term here is invented (SECRETWORD). Skipped
when git is not installed."""
import contextlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

from _load import ROOT

spec = importlib.util.spec_from_file_location("make_public_snapshot", os.path.join(ROOT, "scripts", "make_public_snapshot.py"))
ms = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ms)

HAVE_GIT = shutil.which("git") is not None
NOREPLY = "1234+someone@users.noreply.github.com"
PERSONAL = "someone@example.com"
URL = "https://github.com/someone/day-trader-india"


@unittest.skipUnless(HAVE_GIT, "git is not installed")
class Snapshot(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.dict(os.environ, {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.d = tempfile.mkdtemp(prefix="dti-snap-")
        self.addCleanup(shutil.rmtree, self.d, True)
        self.src = os.path.join(self.d, "src")
        self.target = os.path.join(self.d, "public")
        os.makedirs(self.src)
        self.git(self.src, "init", "-q")
        self.put("README.md", "# A project\n")
        self.put("docs/a.md", "clean text\n")
        self.put(".gitignore", "trader/\nCLAUDE.local.md\n")
        self.put(".claude-plugin/plugin.json", json.dumps(
            {"name": "x", "homepage": "https://example.org/up", "repository": "https://example.org/up", "skills": "./"}))
        self.put(".claude-plugin/marketplace.json", json.dumps(
            {"name": "x", "plugins": [{"name": "x", "homepage": "https://example.org/up"}]}))
        self.commit("An old commit that mentions SECRETWORD")           # old history must not travel
        # local-only, git-ignored files: the private denylist and the private notes
        self.put("trader/private/denylist.txt", "# private\nSECRETWORD\n")
        self.put("CLAUDE.local.md", "private notes about SECRETWORD\n")
        self.deny = os.path.join(self.src, "trader", "private", "denylist.txt")

    def git(self, repo, *args, **env):
        e = dict(os.environ, GIT_AUTHOR_NAME="Old Author", GIT_AUTHOR_EMAIL=PERSONAL,
                 GIT_COMMITTER_NAME="Old Author", GIT_COMMITTER_EMAIL=PERSONAL, **env)
        p = subprocess.run(["git", "-C", repo] + list(args), capture_output=True, env=e)
        self.assertEqual(p.returncode, 0, p.stderr.decode("utf-8", "replace"))
        return p.stdout.decode("utf-8", "replace")

    def put(self, rel, text):
        path = os.path.join(self.src, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)

    def commit(self, message):
        self.git(self.src, "add", "-A")
        self.git(self.src, "commit", "-q", "-m", message)

    def build(self, name="Some One", email=NOREPLY, **kw):
        kw.setdefault("repo_url", URL)
        return ms.build(self.src, self.target, name, email, denylist=kw.pop("denylist", None), **kw)

    def run_main(self, *extra):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = ms.main([self.target, "--source", self.src] + list(extra))
        return code, out.getvalue()

    def read_json(self, rel):
        with open(os.path.join(self.target, rel), encoding="utf-8") as fh:
            return json.load(fh)

    # ---- the good path

    def test_it_builds_one_clean_commit_by_the_noreply_author_with_no_remote(self):
        lines = self.build()
        self.assertTrue(lines[0].startswith("Snapshot ready"))
        self.assertTrue(os.path.isdir(os.path.join(self.target, ".git")))
        log = self.git(self.target, "log", "--format=%an|%ae|%cn|%ce|%s").strip().splitlines()
        self.assertEqual(log, ["Some One|%s|Some One|%s|Day Trader India: public snapshot" % (NOREPLY, NOREPLY)])
        self.assertEqual(self.git(self.target, "remote").strip(), "")
        self.assertEqual(self.git(self.target, "branch", "--show-current").strip(), "main")

    def test_only_tracked_files_travel_and_old_history_does_not(self):
        self.build()
        self.assertTrue(os.path.exists(os.path.join(self.target, "docs", "a.md")))
        self.assertFalse(os.path.exists(os.path.join(self.target, "trader")))
        self.assertFalse(os.path.exists(os.path.join(self.target, "CLAUDE.local.md")))
        self.assertNotIn("SECRETWORD", self.git(self.target, "log", "--all", "-p"))   # the old message stayed behind

    def test_the_plugin_manifests_point_at_the_new_repo(self):
        self.build()
        plugin = self.read_json(".claude-plugin/plugin.json")
        self.assertEqual((plugin["homepage"], plugin["repository"], plugin["name"]), (URL, URL, "x"))
        self.assertEqual(self.read_json(".claude-plugin/marketplace.json")["plugins"][0]["homepage"], URL)

    def test_without_a_repo_url_the_manifests_are_left_alone(self):
        self.build(repo_url=None)
        self.assertEqual(self.read_json(".claude-plugin/plugin.json")["homepage"], "https://example.org/up")

    def test_this_repo_is_not_changed(self):
        head = self.git(self.src, "rev-parse", "HEAD")
        status = self.git(self.src, "status", "--porcelain")
        self.build()
        self.assertEqual(self.git(self.src, "rev-parse", "HEAD"), head)
        self.assertEqual(self.git(self.src, "status", "--porcelain"), status)
        self.assertEqual(self.git(self.src, "remote").strip(), "")

    def test_the_default_denylist_is_the_private_file_in_the_source(self):
        self.put("docs/leak.md", "SECRETWORD\n")
        self.commit("Add a leak")
        with self.assertRaises(ms.Stop) as e:                          # found via trader/private/denylist.txt
            self.build()
        self.assertEqual(e.exception.code, 1)

    # ---- refusals

    def test_a_personal_email_or_a_bad_name_is_refused(self):
        for name, email in (("Some One", PERSONAL), ("Some One", ""), ("", NOREPLY), ("a@b.c", NOREPLY),
                            ("Some One", "someone@users.noreply.github.org")):
            with self.assertRaises(ms.Stop, msg=(name, email)):
                self.build(name=name, email=email)
        self.assertFalse(os.path.exists(self.target))                  # nothing was created

    def test_uncommitted_changes_to_tracked_files_are_refused(self):
        self.put("docs/a.md", "edited but not committed\n")
        with self.assertRaises(ms.Stop) as e:
            self.build()
        self.assertIn("uncommitted", str(e.exception))
        self.assertFalse(os.path.exists(self.target))

    def test_a_non_empty_target_is_refused_and_left_alone(self):
        os.makedirs(self.target)
        keep = os.path.join(self.target, "keep.txt")
        with open(keep, "w", encoding="utf-8") as fh:
            fh.write("mine\n")
        with self.assertRaises(ms.Stop):
            self.build()
        self.assertTrue(os.path.exists(keep))                          # it never deletes anything

    def test_an_empty_existing_target_is_fine(self):
        os.makedirs(self.target)
        self.build()
        self.assertTrue(os.path.isdir(os.path.join(self.target, ".git")))

    def test_a_private_term_in_a_tracked_file_stops_before_any_repo_exists(self):
        self.put("docs/leak.md", "here is SECRETWORD\n")
        self.commit("Add a leak")
        with self.assertRaises(ms.Stop) as e:
            self.build(denylist=self.deny)
        self.assertEqual(e.exception.code, 1)
        self.assertIn("docs/leak.md", str(e.exception))
        self.assertFalse(os.path.exists(os.path.join(self.target, ".git")))

    def test_a_missing_or_empty_denylist_refuses_to_publish(self):
        with self.assertRaises(ms.Stop) as e:
            self.build(denylist=os.path.join(self.d, "nope.txt"))
        self.assertIn("no denylist", str(e.exception))
        empty = os.path.join(self.d, "empty.txt")
        with open(empty, "w", encoding="utf-8") as fh:
            fh.write("# nothing\n")
        with self.assertRaises(ms.Stop) as e:
            self.build(denylist=empty)
        self.assertIn("no terms", str(e.exception))
        self.assertFalse(os.path.exists(self.target))

    def test_a_folder_that_is_not_a_repo_is_refused(self):
        with self.assertRaises(ms.Stop):
            ms.build(self.d, self.target, "Some One", NOREPLY, denylist=self.deny)

    # ---- the command line

    def test_main_prints_the_next_steps_and_returns_zero(self):
        code, out = self.run_main("--name", "Some One", "--email", NOREPLY, "--repo-url", URL)
        self.assertEqual(code, 0, out)
        self.assertIn("nothing was pushed", out)
        self.assertIn("git remote add origin", out)
        self.assertIn("git push -u origin main", out)

    def test_main_returns_2_for_a_bad_email_and_1_for_a_leak(self):
        code, out = self.run_main("--name", "Some One", "--email", PERSONAL)
        self.assertEqual((code, out.startswith("CANNOT BUILD")), (2, True))
        self.put("docs/leak.md", "SECRETWORD\n")
        self.commit("Add a leak")
        code, out = self.run_main("--name", "Some One", "--email", NOREPLY)
        self.assertEqual((code, out.startswith("FOUND")), (1, True))

    def test_the_script_itself_holds_no_private_terms_and_no_em_dash(self):
        with open(os.path.join(ROOT, "scripts", "make_public_snapshot.py"), encoding="utf-8") as fh:
            src = fh.read()
        self.assertNotIn("SECRETWORD", src)
        self.assertNotIn(chr(0x2014), src)


if __name__ == "__main__":
    unittest.main()
