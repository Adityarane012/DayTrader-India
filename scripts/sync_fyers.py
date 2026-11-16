#!/usr/bin/env python
"""Copy the master fyers.py over its copies. Standard library only.

    python scripts/sync_fyers.py            # copy trader-alerts/fyers.py over the others
    python scripts/sync_fyers.py --check    # only report: exit 1 if any copy differs (writes nothing)

fyers.py (the Fyers login, quotes, candles and request pacing) exists as identical copies so
that every skill folder works on its own:

    trader-alerts/fyers.py    the MASTER: edit this one
    trader-entry/fyers.py     copy
    trader-scanner/fyers.py   copy

and, when the skills are installed project-locally, the same file inside
.claude/skills/trader-alerts, trader-entry and trader-scanner (copied too when that folder
exists, so the installed copy is never stale). A test fails if any copy differs. This script
is the one step after editing the master. It never edits the master, never touches the
token or ~/.day-trader-india/, and makes no network call.

Exit 0: all copies match (or were just copied). Exit 1: --check found a difference.
Exit 2: the master is missing.
"""
import argparse
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
MASTER = os.path.join("trader-alerts", "fyers.py")
COPIES = (os.path.join("trader-entry", "fyers.py"), os.path.join("trader-scanner", "fyers.py"))
INSTALLED = os.path.join(".claude", "skills")


def read(path):
    try:
        with open(path, "rb") as fh:
            return fh.read()
    except OSError:
        return None


def targets(root):
    """Every copy to keep in step, as paths relative to root."""
    out = list(COPIES)
    skills = os.path.join(root, INSTALLED)
    if os.path.isdir(skills):
        for folder in ("trader-alerts", "trader-entry", "trader-scanner"):
            if os.path.isdir(os.path.join(skills, folder)):
                out.append(os.path.join(INSTALLED, folder, "fyers.py"))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="Copy the master fyers.py over its copies.")
    ap.add_argument("--check", action="store_true", help="report only; exit 1 if a copy differs")
    ap.add_argument("--root", default=ROOT, help="the repo folder (default: this repo)")
    a = ap.parse_args(argv)
    root = os.path.abspath(a.root)
    master = read(os.path.join(root, MASTER))
    if master is None:
        print("CANNOT SYNC: the master %s is missing." % MASTER)
        return 2
    differing, copied = [], []
    for rel in targets(root):
        path = os.path.join(root, rel)
        if read(path) == master:
            continue
        differing.append(rel)
        if not a.check:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            shutil.copyfile(os.path.join(root, MASTER), path)
            copied.append(rel)
    if a.check:
        if differing:
            print("DIFFERS from %s: %s" % (MASTER, ", ".join(differing)))
            print("Run: python scripts/sync_fyers.py")
            return 1
        print("OK: every copy of fyers.py matches %s." % MASTER)
        return 0
    if copied:
        print("Copied %s over: %s" % (MASTER, ", ".join(copied)))
    else:
        print("OK: every copy of fyers.py already matches %s." % MASTER)
    return 0


if __name__ == "__main__":
    sys.exit(main())
