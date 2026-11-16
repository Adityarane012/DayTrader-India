"""scripts/leak_check.py: the check that runs before anything is published.

Every term below is invented (SECRETWORD, plain placeholders): the real private
terms live only in trader/private/denylist.txt, which is not in git. No network.
Git is used for the history tests (a throwaway repo in a temp folder) and those
tests are skipped when git is not installed.
"""
import contextlib
import importlib.util
import io
import os
import shutil
import subprocess
import tempfile
import unittest

from _load import ROOT

spec = importlib.util.spec_from_file_location("leak_check", os.path.join(ROOT, "scripts", "leak_check.py"))
lc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lc)

HAVE_GIT = shutil.which("git") is not None


def run(argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = lc.main(argv)
    return code, out.getvalue()


class Scratch(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="dti-leak-")
        self.addCleanup(shutil.rmtree, self.d, True)
        self.repo = os.path.join(self.d, "repo")
        os.makedirs(self.repo)
        self.deny = os.path.join(self.d, "denylist.txt")
        self.put(self.deny, "# a comment\nSECRETWORD\n\nsecond term\n")

    def put(self, path, text):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)

    def check(self, *extra):
        return run(["--repo", self.repo, "--denylist", self.deny] + list(extra))


class Files(Scratch):
    def test_a_clean_folder_passes(self):
        self.put(os.path.join(self.repo, "a.md"), "nothing here\n")
        code, out = self.check()
        self.assertEqual(code, 0, out)
        self.assertIn("OK: 2 term(s) checked in 1 file(s)", out)

    def test_a_private_term_is_found_with_its_file_and_line_and_is_case_insensitive(self):
        self.put(os.path.join(self.repo, "docs", "n.md"), "line one\nthe secretWORD is here\n")
        code, out = self.check()
        self.assertEqual(code, 1)
        self.assertIn("docs/n.md:2: contains 'secretword'", out)

    def test_a_multi_word_term_is_matched(self):
        self.put(os.path.join(self.repo, "a.md"), "This is the Second Term in a sentence\n")
        self.assertEqual(self.check()[0], 1)

    def test_a_term_in_a_file_name_is_found(self):
        self.put(os.path.join(self.repo, "notes-secretword.md"), "clean text\n")
        code, out = self.check()
        self.assertEqual(code, 1)
        self.assertIn("path notes-secretword.md", out)

    def test_saved_public_data_is_skipped_by_default_and_scanned_on_request(self):
        self.put(os.path.join(self.repo, "tests", "fixtures", "news.xml"), "<t>SECRETWORD</t>\n")
        self.put(os.path.join(self.repo, "trader-scanner", "universes", "list.csv"), "SECRETWORD,EQ\n")
        self.assertEqual(self.check()[0], 0)
        self.assertEqual(self.check("--no-default-skips")[0], 1)
        self.put(os.path.join(self.repo, "other", "x.md"), "SECRETWORD\n")
        self.assertEqual(self.check()[0], 1)                         # not skipped by default
        self.assertEqual(self.check("--skip", "other/")[0], 0)       # skipped by its prefix
        self.put(os.path.join(self.repo, "keep", "y.md"), "SECRETWORD\n")
        self.assertEqual(self.check("--skip", "other/")[0], 1)       # a skip covers only its own prefix

    def test_binary_files_are_not_read(self):
        with open(os.path.join(self.repo, "data.json.gz"), "wb") as fh:
            fh.write(b"\x1f\x8bSECRETWORD")
        self.assertEqual(self.check()[0], 0)

    def test_no_denylist_means_cannot_check_never_a_pass(self):
        code, out = run(["--repo", self.repo, "--denylist", os.path.join(self.d, "missing.txt")])
        self.assertEqual(code, 2)
        self.assertIn("CANNOT CHECK", out)
        self.put(self.deny, "# only comments\n\n")
        code, out = self.check()
        self.assertEqual(code, 2)
        self.assertIn("no terms", out)

    def test_a_missing_repo_folder_cannot_be_checked(self):
        code, out = run(["--repo", os.path.join(self.d, "nope"), "--denylist", self.deny])
        self.assertEqual(code, 2)

    def test_the_script_itself_holds_no_private_terms(self):
        # the terms must come from the private file only, so the tracked script cannot leak them
        with open(os.path.join(ROOT, "scripts", "leak_check.py"), encoding="utf-8") as fh:
            src = fh.read()
        self.assertNotIn("SECRETWORD", src)
        self.assertIn("trader", src)                                    # it points at the private file by path
        self.assertNotIn(chr(0x2014), src)                              # no em dash (a repo rule)


@unittest.skipUnless(HAVE_GIT, "git is not installed")
class History(Scratch):
    def git(self, *args, **env):
        e = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_SYSTEM=os.devnull, **env)
        subprocess.run(["git", "-C", self.repo] + list(args), check=True, capture_output=True, env=e)

    def commit(self, message, email="1234+someone@users.noreply.github.com", name="Some One"):
        env = {"GIT_AUTHOR_NAME": name, "GIT_AUTHOR_EMAIL": email,
               "GIT_COMMITTER_NAME": name, "GIT_COMMITTER_EMAIL": email}
        self.git("add", "-A", **env)
        self.git("commit", "-q", "-m", message, **env)

    def setUp(self):
        super(History, self).setUp()
        self.git("init", "-q")

    def test_a_clean_history_with_noreply_authors_passes(self):
        self.put(os.path.join(self.repo, "a.md"), "clean\n")
        self.commit("Add a file")
        code, out = self.check("--history")
        self.assertEqual(code, 0, out)
        self.assertIn("and 1 commit(s)", out)

    def test_a_private_term_in_a_commit_message_is_found(self):
        self.put(os.path.join(self.repo, "a.md"), "clean\n")
        self.commit("Fix the thing after the SECRETWORD incident")
        code, out = self.check("--history")
        self.assertEqual(code, 1)
        self.assertIn("message", out)

    def test_a_term_added_and_later_removed_is_still_found_in_the_history(self):
        self.put(os.path.join(self.repo, "a.md"), "SECRETWORD\n")
        self.commit("First")
        self.put(os.path.join(self.repo, "a.md"), "clean now\n")
        self.commit("Second")
        self.assertEqual(self.check()[0], 0)                         # the working tree is clean...
        code, out = self.check("--history")                          # ...but the history is not
        self.assertEqual(code, 1)
        self.assertIn("change: contains 'secretword'", out)

    def test_history_skips_saved_public_data_like_the_file_scan_does(self):
        self.put(os.path.join(self.repo, "tests", "fixtures", "news.xml"), "<t>SECRETWORD</t>\n")
        self.put(os.path.join(self.repo, "a.md"), "clean\n")
        self.commit("Add fixtures")
        self.assertEqual(self.check("--history")[0], 0)
        code, out = self.check("--history", "--no-default-skips")
        self.assertEqual(code, 1)
        self.assertIn("change: contains 'secretword'", out)
        self.put(os.path.join(self.repo, "a.md"), "SECRETWORD in a normal file\n")     # still caught elsewhere
        self.commit("Leak")
        self.assertEqual(self.check("--history")[0], 1)

    def test_a_removed_line_that_looks_like_a_header_is_still_scanned(self):
        self.put(os.path.join(self.repo, "a.md"), "-- SECRETWORD\nkeep\n")
        self.commit("First")
        self.put(os.path.join(self.repo, "a.md"), "keep\n")
        self.commit("Remove it")
        self.assertEqual(self.check("--history")[0], 1)

    def test_a_non_noreply_author_email_is_found(self):
        self.put(os.path.join(self.repo, "a.md"), "clean\n")
        self.commit("Add a file", email="someone@example.com")
        code, out = self.check("--history")
        self.assertEqual(code, 1)
        self.assertIn("is not a GitHub noreply address", out)
        self.assertIn("someone@example.com", out)

    def test_history_on_a_folder_that_is_not_a_repo_is_reported(self):
        self.put(os.path.join(self.d, "plain", "a.md"), "clean\n")
        code, out = run(["--repo", os.path.join(self.d, "plain"), "--denylist", self.deny, "--history"])
        self.assertEqual(code, 1)
        self.assertIn("not one", out)


if __name__ == "__main__":
    unittest.main()
