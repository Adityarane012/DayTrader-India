import json
import os
import re
import unittest

from _load import ROOT

# the India fork: upstream's eleven minus the two US-only skills (analyst, pelosi)
SKILLS = ["trader-scanner", "trader-news", "trader-entry", "trader-exit", "trader-timemachine",
          "trader-risk", "trader-budget", "trader-broker", "trader-alerts"]
ABOUT = ("9 Claude skills for day trading on the NSE: scan the Nifty charts, track breaking news, "
         "time every entry and exit, and replay every outcome before you risk a rupee.")
# skills on the way to an order carry the safety block
ORDER_PATH = ["trader-scanner", "trader-entry", "trader-exit", "trader-timemachine", "trader-budget",
              "trader-risk", "trader-broker", "trader-alerts"]
V1_ONLY = ["trader-copycat", "trader-screener", "trader-tax", "trader-rebalance"]
US_ONLY = ["trader-analyst", "trader-pelosi"]


def frontmatter(path):
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    return (m.group(1) if m else ""), text


def every_text_file():
    for base, dirs, files in os.walk(ROOT):
        # .claude/worktrees/ holds whole copies of the repo while parallel agents work (git-ignored)
        dirs[:] = [d for d in dirs if d not in (".git", "__pycache__")
                   and not (d == "worktrees" and os.path.basename(base) == ".claude")]
        for f in files:
            if f.endswith((".md", ".py", ".json", ".csv", ".txt", ".xml")) or f == "LICENSE":
                yield os.path.join(base, f)


class Repo(unittest.TestCase):
    def test_nine_skill_folders_at_the_root(self):
        found = sorted(d for d in os.listdir(ROOT)
                       if os.path.isfile(os.path.join(ROOT, d, "SKILL.md")))
        self.assertEqual(found, sorted(SKILLS))

    def test_root_holds_only_the_pack(self):
        root = sorted(d for d in os.listdir(ROOT)
                      if not d.startswith(".git") and d not in (".claude", "trader", "CLAUDE.local.md"))
        self.assertEqual(root, sorted([".claude-plugin", "CLAUDE.md", "LICENSE", "PIPELINE.md", "README.md",
                                       "UPSTREAM.md", "docs", "plan.md", "scripts", "tests"] + SKILLS))

    def test_frontmatter_name_and_description(self):
        for s in SKILLS:
            fm, text = frontmatter(os.path.join(ROOT, s, "SKILL.md"))
            self.assertIn("name: %s\n" % s, fm + "\n", s)
            self.assertRegex(fm, r"description: ", s)
            self.assertGreater(len(fm), 200, "%s description is too thin" % s)
            self.assertGreater(len(text.splitlines()), 60, s)

    def test_order_path_skills_carry_the_safety_rule(self):
        for s in ORDER_PATH:
            _, text = frontmatter(os.path.join(ROOT, s, "SKILL.md"))
            low = " ".join(text.lower().split())
            self.assertIn("not financial advice", low, s)
            self.assertIn("yes", low, s)

    def test_every_skill_has_the_same_india_safety_block(self):
        blocks = {}
        for s in SKILLS:
            _, text = frontmatter(os.path.join(ROOT, s, "SKILL.md"))
            blocks[s] = text[text.index("## Safety"):]
        self.assertEqual(len(set(blocks.values())), 1, sorted(blocks))
        low = " ".join(next(iter(blocks.values())).lower().split())
        for must in ("nothing in this pack places an order", "places it themselves", "explicit yes",
                     "not financial advice", "never go in the chat"):
            self.assertIn(must, low)
        for never in ("alpaca", "allow once", "needs approval"):
            self.assertNotIn(never, low)

    def test_every_tool_identifies_as_the_fork(self):
        # one plain user agent: no personal details, and not upstream's name
        for s in SKILLS:
            folder = os.path.join(ROOT, s)
            for f in os.listdir(folder):
                if f.endswith(".py"):
                    with open(os.path.join(folder, f), encoding="utf-8") as fh:
                        src = fh.read()
                    self.assertNotIn("day-trader-skill/2.0", src, "%s/%s" % (s, f))
                    for m in re.findall(r'(?m)^UA = "(.*)"$', src):
                        self.assertEqual(m, "Mozilla/5.0 (compatible; day-trader-india/0.1)", "%s/%s" % (s, f))

    def test_installed_skill_copies_match_the_repo(self):
        # .claude/skills/ (kept out of git) is what Claude Code loads; a stale copy would run old code
        inst = os.path.join(ROOT, ".claude", "skills")
        if not os.path.isdir(inst):
            self.skipTest("skills not installed in .claude/skills")
        for s in SKILLS:
            src = os.path.join(ROOT, s)
            for base, dirs, files in os.walk(src):
                dirs[:] = [d for d in dirs if d != "__pycache__"]
                for f in files:
                    if f.endswith(".pyc"):
                        continue
                    a = os.path.join(base, f)
                    b = os.path.join(inst, os.path.relpath(a, ROOT))
                    self.assertTrue(os.path.exists(b), "missing %s: re-copy the skills (README, Quick start)" % b)
                    with open(a, "rb") as x, open(b, "rb") as y:
                        self.assertEqual(x.read(), y.read(),
                                         "%s is stale: re-copy the skills (README, Quick start)" % os.path.relpath(b, ROOT))

    def test_plugin_manifest_points_at_the_root_skills(self):
        with open(os.path.join(ROOT, ".claude-plugin", "plugin.json")) as fh:
            plugin = json.load(fh)
        self.assertEqual(plugin["name"], "day-trader-india")
        self.assertEqual(plugin["skills"], "./")
        self.assertEqual(plugin["description"], ABOUT)
        with open(os.path.join(ROOT, ".claude-plugin", "marketplace.json")) as fh:
            market = json.load(fh)
        self.assertEqual(market["name"], "day-trader-india")
        self.assertEqual(market["plugins"][0]["name"], "day-trader-india")

    def test_readme_names_the_pack_and_its_upstream(self):
        with open(os.path.join(ROOT, "README.md"), encoding="utf-8") as fh:
            readme = " ".join(fh.read().split())
        self.assertTrue(readme.startswith("# Day Trader India"))
        for line in (ABOUT,
                     "https://github.com/Jakeschincariol/day-trader-skill",
                     "## Fine print"):
            self.assertIn(line, readme)
        for s in SKILLS:
            self.assertIn("/" + s, readme, s)

    def test_no_em_dashes_and_no_personal_email(self):
        for path in every_text_file():
            with open(path, encoding="utf-8", errors="replace") as fh:
                text = fh.read()
            rel = os.path.relpath(path, ROOT)
            if not rel.startswith(os.path.join("tests", "fixtures")):  # fixtures are real data, kept as published
                self.assertNotIn("\u2014", text, rel)
            self.assertNotIn("jakeschincariol" + "@" + "gmail.com", text, rel)  # built, so this file passes too

    def test_no_v1_only_skill_is_left_behind(self):
        for path in every_text_file():
            rel = os.path.relpath(path, ROOT)
            if rel.startswith("tests" + os.sep) or rel in ("README.md", "UPSTREAM.md", "plan.md"):
                continue  # these name the removed skills on purpose
            with open(path, encoding="utf-8", errors="replace") as fh:
                text = fh.read()
            for old in V1_ONLY + US_ONLY:
                self.assertNotIn(old, text, rel)

    def test_every_tool_runs_on_python_3_8(self):
        # no 3.9+ only modules or syntax in the tools (the README promises 3.8)
        for s in SKILLS:
            folder = os.path.join(ROOT, s)
            for f in os.listdir(folder):
                if not f.endswith(".py"):
                    continue
                with open(os.path.join(folder, f), encoding="utf-8") as fh:
                    src = fh.read()
                for bad in ("import zoneinfo", "from zoneinfo", ".removeprefix(", ".removesuffix(",
                            "match ", "list[", "dict[", "tuple["):
                    if bad == "match ":
                        self.assertNotRegex(src, r"(?m)^\s+match \w+.*:$", "%s/%s" % (s, f))
                    elif bad.endswith("["):
                        self.assertNotRegex(src, r"(?<![\w.])%s" % re.escape(bad), "%s/%s" % (s, f))
                    else:
                        self.assertNotIn(bad, src, "%s/%s" % (s, f))

    def test_day_trading_limits_ship_in_the_example_config(self):
        with open(os.path.join(ROOT, "trader-budget", "config.example.json")) as fh:
            cfg = json.load(fh)
        for k in ("max_loss_per_trade_inr", "max_daily_loss_inr", "max_trades_per_day",
                  "min_reward_risk", "require_stop", "no_entries_after", "flat_by"):
            self.assertIn(k, cfg, k)
        self.assertFalse([k for k in cfg if k.endswith("_usd")])
        self.assertEqual((cfg["no_entries_before"], cfg["no_entries_after"], cfg["flat_by"]),
                         ("09:30", "15:00", "15:15"))
        self.assertIs(cfg["require_stop"], True)
        self.assertIs(cfg.get("allow_short", False), False)
        self.assertIs(cfg.get("allow_margin", False), False)

    def test_paper_trading_is_the_default(self):
        with open(os.path.join(ROOT, "trader-budget", "config.example.json")) as fh:
            cfg = json.load(fh)
        self.assertIs(cfg["paper"], True)
        self.assertIs(cfg.get("allow_options", False), False)


if __name__ == "__main__":
    unittest.main()
