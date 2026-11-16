#!/usr/bin/env python
"""Build a clean, publishable copy of this repo as a brand-new git repo. Standard library + git.

    python scripts/make_public_snapshot.py ../day-trader-india-public \\
        --name "Your Name" --email "12345+yourname@users.noreply.github.com" \\
        --repo-url https://github.com/yourname/day-trader-india

What it does, in order (it stops at the first problem and says why):

  1. Checks the author: a non-empty name that is not an email, and a GitHub noreply email
     (ID+name@users.noreply.github.com), so no personal address is ever published.
  2. Checks this repo has no uncommitted changes to tracked files (the snapshot is of the last
     commit, HEAD, and would silently leave changes out).
  3. Exports HEAD (tracked files only: never trader/, CLAUDE.local.md or .claude/, which are
     not in git) into TARGET, which must not exist or must be empty.
  4. With --repo-url, points the plugin manifests' homepage and repository at your new repo.
  5. Runs scripts/leak_check.py on the exported files, with the private denylist from
     trader/private/denylist.txt. Any hit stops everything BEFORE a repo exists.
  6. Creates a new git repo in TARGET with ONE commit authored and committed by you.
  7. Runs the leak check again over that repo's history, messages and author emails.

It never adds a remote, never pushes, and never changes this (private) repo. This repo keeps
its full history on your computer and must not be pushed; push the TARGET repo instead.

Exit 0: the snapshot is ready. Exit 1: the leak check found something. Exit 2: could not build.
"""
import argparse
import io
import json
import os
import subprocess
import sys
import tarfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import leak_check  # noqa: E402  (the sibling script)

MANIFESTS = (os.path.join(".claude-plugin", "plugin.json"), os.path.join(".claude-plugin", "marketplace.json"))
DEFAULT_MESSAGE = "Day Trader India: public snapshot"


class Stop(Exception):
    def __init__(self, message, code=2):
        Exception.__init__(self, message)
        self.code = code


def git(repo, *args, **kw):
    env = dict(os.environ, **kw.get("env", {}))
    p = subprocess.run(["git", "-C", repo] + list(args), capture_output=True, env=env,
                       timeout=300, input=kw.get("input"))
    if p.returncode != 0:
        raise Stop("git %s failed: %s" % (" ".join(args), p.stderr.decode("utf-8", "replace").strip()[:200]))
    return p.stdout


def check_author(name, email):
    name = (name or "").strip()
    email = (email or "").strip()
    if not name or "@" in name:
        raise Stop("--name must be your name as it should appear on the commits (not an email address).")
    if not leak_check.NOREPLY.match(email):
        raise Stop("--email must be a GitHub noreply address like 12345+yourname@users.noreply.github.com "
                   "(GitHub: Settings, Emails), so no personal address is published. Got %r." % email)
    return name, email


def check_source(source):
    if not os.path.isdir(os.path.join(source, ".git")):
        raise Stop("%s is not a git repo." % source)
    dirty = git(source, "status", "--porcelain", "--untracked-files=no").decode("utf-8", "replace").strip()
    if dirty:
        raise Stop("this repo has uncommitted changes to tracked files:\n%s\nThe snapshot is of the last commit. "
                   "Commit them (or discard them) first." % dirty[:400])


def check_target(target):
    if os.path.exists(target) and (not os.path.isdir(target) or os.listdir(target)):
        raise Stop("%s exists and is not empty. Pick a new folder, or empty it yourself first (this script never "
                   "deletes anything)." % target)


def export_head(source, target):
    data = git(source, "archive", "--format=tar", "HEAD")
    os.makedirs(target, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(data)) as tf:
        try:
            tf.extractall(target, filter="data")
        except TypeError:                       # Python before 3.12 has no filter argument
            tf.extractall(target)


def point_manifests_at(target, repo_url):
    for rel in MANIFESTS:
        path = os.path.join(target, rel)
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
        if "homepage" in doc:
            doc["homepage"] = repo_url
        if "repository" in doc:
            doc["repository"] = repo_url
        for plugin in doc.get("plugins", []):
            if "homepage" in plugin:
                plugin["homepage"] = repo_url
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(doc, fh, indent=2)
            fh.write("\n")


def build(source, target, name, email, repo_url=None, message=DEFAULT_MESSAGE, denylist=None):
    """Make the snapshot. Returns a list of lines to print. Raises Stop on a problem."""
    name, email = check_author(name, email)
    source, target = os.path.abspath(source), os.path.abspath(target)
    deny = denylist or os.path.join(source, "trader", "private", "denylist.txt")
    check_source(source)
    check_target(target)
    try:
        terms = leak_check.load_terms(deny)
    except OSError as e:
        raise Stop("no denylist at %s (%s). Refusing to publish with nothing to check against." % (deny, e.strerror or e))
    if not terms:
        raise Stop("the denylist %s has no terms. Refusing to publish with nothing to check against." % deny)

    export_head(source, target)
    if repo_url:
        point_manifests_at(target, repo_url)
    hits, count = leak_check.scan_files(target, terms, list(leak_check.DEFAULT_SKIPS))
    if hits:
        raise Stop("the export holds private terms, so no repo was created. Delete %s, fix this repo, commit and "
                   "run again:\n  %s" % (target, "\n  ".join(hits[:20])), code=1)

    author = {"GIT_AUTHOR_NAME": name, "GIT_AUTHOR_EMAIL": email,
              "GIT_COMMITTER_NAME": name, "GIT_COMMITTER_EMAIL": email}
    git(target, "init", "-q")
    git(target, "symbolic-ref", "HEAD", "refs/heads/main")
    git(target, "config", "user.name", name)
    git(target, "config", "user.email", email)
    git(target, "add", "-A")
    git(target, "-c", "commit.gpgsign=false", "commit", "-q", "-m", message, env=author)
    more, commits = leak_check.scan_history(target, terms, list(leak_check.DEFAULT_SKIPS))
    if more:
        raise Stop("the new repo's history holds private items, which should not happen. Do not push %s:\n  %s"
                   % (target, "\n  ".join(more[:20])), code=1)
    return ["Snapshot ready: %s" % target,
            "  %d files checked against %d private terms; %d commit by %s <%s>" % (count, len(terms), commits, name, email),
            "  no remote is set and nothing was pushed."]


def main(argv=None):
    ap = argparse.ArgumentParser(description="Build a clean public copy of this repo as a new git repo.")
    ap.add_argument("target", help="the new folder for the public repo (must not exist or be empty)")
    ap.add_argument("--name", required=True, help="the author name for the commit")
    ap.add_argument("--email", required=True, help="a GitHub noreply email: ID+name@users.noreply.github.com")
    ap.add_argument("--repo-url", help="your new GitHub repo URL, written into the plugin manifests")
    ap.add_argument("--message", default=DEFAULT_MESSAGE, help="the commit message")
    ap.add_argument("--denylist", help="private terms file (default trader/private/denylist.txt)")
    ap.add_argument("--source", default=ROOT, help="the repo to snapshot (default: this repo)")
    a = ap.parse_args(argv)
    try:
        lines = build(a.source, a.target, a.name, a.email, a.repo_url, a.message, a.denylist)
    except Stop as e:
        print("%s: %s" % ("FOUND" if e.code == 1 else "CANNOT BUILD", e))
        return e.code
    except (OSError, subprocess.SubprocessError) as e:
        print("CANNOT BUILD: %s" % e)
        return 2
    for line in lines:
        print(line)
    print("Next: cd %s, create an EMPTY repo on GitHub, then:" % os.path.abspath(a.target))
    print("  git remote add origin <your-repo-url>")
    print("  git push -u origin main")
    return 0


if __name__ == "__main__":
    sys.exit(main())
