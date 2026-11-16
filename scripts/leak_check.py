#!/usr/bin/env python
"""Check that nothing private is about to be published. Standard library only.

    python scripts/leak_check.py                          # the tracked files of this repo
    python scripts/leak_check.py --repo ../public-copy    # another folder or repo
    python scripts/leak_check.py --repo ../public-copy --history   # also every commit message,
                                                                   # author and committed change

The private terms are NOT in this file. They are read, one per line (case-insensitive,
"#" comments allowed), from trader/private/denylist.txt, which is not in git. With no
denylist the check refuses to run (exit 2): a check with nothing to look for must never
look like a pass.

Saved public data is skipped by default (tests/fixtures/ and the official index lists in
trader-scanner/universes/): they hold real company names and news that are public by
construction. --no-default-skips scans them too; --skip PREFIX adds a path prefix.

With --history it also fails on any commit author or committer email that is not a
GitHub noreply address (ID+name@users.noreply.github.com), since a pushed commit
shows its email to everyone.

Exit 0: nothing found. Exit 1: something found (printed). Exit 2: could not check.
"""
import argparse
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DEFAULT_DENYLIST = os.path.join(ROOT, "trader", "private", "denylist.txt")
NOREPLY = re.compile(r"^[^@\s]+@users\.noreply\.github\.com$", re.I)
SKIP_SUFFIXES = (".gz", ".png", ".jpg", ".jpeg", ".gif", ".ico", ".pdf", ".zip")
MAX_SHOWN = 40
DEFAULT_SKIPS = ("tests/fixtures/", "trader-scanner/universes/")


def load_terms(path):
    """The denylist terms, lower-cased. Raises OSError if it cannot be read."""
    terms = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line and not line.startswith("#"):
                terms.append(line.lower())
    return terms


def git(repo, *args):
    p = subprocess.run(["git", "-C", repo] + list(args), capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=300)
    if p.returncode != 0:
        raise RuntimeError("git %s failed: %s" % (" ".join(args), p.stderr.strip()[:200]))
    return p.stdout


def is_git(repo):
    return os.path.isdir(os.path.join(repo, ".git"))


def files_to_scan(repo):
    """Relative paths: the tracked files of a git repo, or every file of a plain folder."""
    if is_git(repo):
        return [f for f in git(repo, "ls-files").splitlines() if f]
    out = []
    for base, dirs, files in os.walk(repo):
        dirs[:] = [d for d in dirs if d != ".git"]
        for f in files:
            out.append(os.path.relpath(os.path.join(base, f), repo).replace(os.sep, "/"))
    return out


def scan_text(label, text, terms, hits):
    for n, line in enumerate(text.splitlines(), 1):
        low = line.lower()
        for t in terms:
            if t in low:
                hits.append("%s:%d: contains %r" % (label, n, t))


def scan_files(repo, terms, skips=()):
    hits = []
    files = [f for f in files_to_scan(repo) if not f.startswith(tuple(skips))]
    for rel in files:
        scan_text("path " + rel, rel, terms, hits)          # a private term in a file NAME
        if rel.lower().endswith(SKIP_SUFFIXES):
            continue
        try:
            with open(os.path.join(repo, rel), "rb") as fh:
                data = fh.read()
        except OSError:
            continue
        scan_text(rel, data.decode("utf-8", "replace"), terms, hits)
    return hits, len(files)


def scan_history(repo, terms, skips=()):
    hits = []
    if not is_git(repo):
        return ["--history needs a git repo, and %s is not one" % repo], 0
    commits = git(repo, "log", "--all", "--format=%H").split()
    for c in commits:
        short = c[:8]
        meta = git(repo, "show", "-s", "--format=%an|%ae|%cn|%ce", c).strip().split("|")
        for email in (meta[1], meta[3]) if len(meta) == 4 else ():
            if not NOREPLY.match(email):
                hits.append("commit %s: author or committer email %r is not a GitHub noreply address" % (short, email))
        scan_text("commit " + short + " message and names", git(repo, "show", "-s", "--format=%an %cn%n%B", c), terms, hits)
    # every added or removed line in every commit, so a term removed later is still found
    patch = git(repo, "log", "--all", "-p", "--format=commit %h")
    cur, cur_file, in_header = "?", "", False
    skips = tuple(skips)
    for line in patch.splitlines():
        if line.startswith("commit "):
            cur, cur_file, in_header = line.split(" ", 1)[1], "", False
        elif line.startswith("diff --git "):
            in_header = True                        # the next lines are file headers, not content
        elif line.startswith("@@"):
            in_header = False
        elif in_header:
            for mark in ("--- a/", "+++ b/"):
                if line.startswith(mark):
                    cur_file = line[len(mark):]     # /dev/null (an add or a delete) keeps the other path
        elif line[:1] in "+-" and not (skips and cur_file.startswith(skips)):
            low = line.lower()
            for t in terms:
                if t in low:
                    hits.append("commit %s change: contains %r" % (cur, t))
    return sorted(set(hits)), len(commits)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Fail if anything private would be published.")
    ap.add_argument("--repo", default=ROOT, help="folder or git repo to check (default: this repo)")
    ap.add_argument("--denylist", default=DEFAULT_DENYLIST, help="private terms file (default trader/private/denylist.txt)")
    ap.add_argument("--history", action="store_true", help="also check every commit (messages, emails, changes)")
    ap.add_argument("--skip", action="append", default=[], metavar="PREFIX", help="skip files under this path prefix")
    ap.add_argument("--no-default-skips", action="store_true", help="also scan tests/fixtures/ and the index lists")
    a = ap.parse_args(argv)
    try:
        terms = load_terms(a.denylist)
    except OSError as e:
        print("CANNOT CHECK: no denylist at %s (%s). Nothing was checked." % (a.denylist, e.strerror or e))
        return 2
    if not terms:
        print("CANNOT CHECK: the denylist %s has no terms. Nothing was checked." % a.denylist)
        return 2
    repo = os.path.abspath(a.repo)
    if not os.path.isdir(repo):
        print("CANNOT CHECK: %s is not a folder." % repo)
        return 2
    try:
        skips = list(a.skip) + ([] if a.no_default_skips else list(DEFAULT_SKIPS))
        hits, n = scan_files(repo, terms, skips)
        commits = 0
        if a.history:
            more, commits = scan_history(repo, terms, skips)
            hits += more
    except (RuntimeError, OSError, subprocess.SubprocessError) as e:
        print("CANNOT CHECK: %s" % e)
        return 2
    if hits:
        print("FOUND %d private item(s) in %s:" % (len(hits), repo))
        for h in hits[:MAX_SHOWN]:
            print("  " + h)
        if len(hits) > MAX_SHOWN:
            print("  ... and %d more" % (len(hits) - MAX_SHOWN))
        return 1
    print("OK: %d term(s) checked in %d file(s)%s. Nothing private found."
          % (len(terms), n, " and %d commit(s)" % commits if a.history else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
