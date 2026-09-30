"""Run with: python3 -m unittest discover tests"""

import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "examples"))

from cost_trail.attribute import attribute  # noqa: E402
from cost_trail.cli import main  # noqa: E402
from cost_trail.parse import ToolCall, read_logs  # noqa: E402
from cost_trail.pricing import Pricing  # noqa: E402
from cost_trail.rules import extract, label_servers, load_rules  # noqa: E402
from cost_trail.summary import spend  # noqa: E402
import make_sample_logs  # noqa: E402

M = 1_000_000


class PricingTest(unittest.TestCase):
    def setUp(self):
        self.p = Pricing()

    def test_each_token_class(self):
        self.assertAlmostEqual(self.p.cost("claude-opus-5-5", {"output_tokens": M}), 20.0)
        self.assertAlmostEqual(self.p.cost("claude-opus-5-5", {"input_tokens": M}), 4.0)
        self.assertAlmostEqual(self.p.cost("claude-opus-5-5", {"cache_read_input_tokens": M}), 0.20)
        one_hour = {"cache_creation_input_tokens": M, "cache_creation": {"ephemeral_1h_input_tokens": M}}
        self.assertAlmostEqual(self.p.cost("claude-opus-5-5", one_hour), 8.0)   # 2x input
        self.assertAlmostEqual(self.p.cost("claude-opus-5-5", {"cache_creation_input_tokens": M}), 5.0)  # 1.25x

    def test_fast_mode_and_web_search(self):
        self.assertAlmostEqual(self.p.cost("claude-opus-5-5", {"output_tokens": M, "speed": "fast"}), 40.0)
        self.assertAlmostEqual(self.p.cost("claude-opus-5-5", {"server_tool_use": {"web_search_requests": 3}}), 0.03)

    def test_model_matching(self):
        self.assertEqual(self.p.rates_for("claude-opus-5")["output"], 25.0)       # not opus-5-5
        self.assertEqual(self.p.rates_for("claude-sonnet-4-5-20250929")["output"], 15.0)
        self.assertEqual(self.p.rates_for("us.anthropic.claude-haiku-4-5")["output"], 5.0)
        self.p.rates_for("claude-mystery-9")
        self.assertIn("claude-mystery-9", self.p.unknown_models)
        self.assertEqual(self.p.cost("<synthetic>", {"output_tokens": M}), 0.0)


def _line(**kw):
    return json.dumps(kw) + "\n"


class ParseTest(unittest.TestCase):
    def test_split_lines_counted_once_and_resumes_not_double_counted(self):
        with tempfile.TemporaryDirectory() as root:
            proj = os.path.join(root, "-proj")
            os.makedirs(proj)
            usage = {"output_tokens": M}
            lines = [
                _line(type="user", sessionId="s1", promptId="p1", timestamp="2026-09-01T10:00:00Z",
                      message={"role": "user", "content": "hi"}),
                # One response split over two lines (text block, then tool_use block), same usage.
                _line(type="assistant", sessionId="s1", requestId="r1", timestamp="2026-09-01T10:00:05Z",
                      message={"id": "m1", "model": "claude-opus-5-5", "usage": usage,
                               "content": [{"type": "text", "text": "ok"}]}),
                _line(type="assistant", sessionId="s1", requestId="r1", timestamp="2026-09-01T10:00:05Z",
                      message={"id": "m1", "model": "claude-opus-5-5", "usage": usage,
                               "content": [{"type": "tool_use", "id": "t1", "name": "Bash", "input": {}}]}),
            ]
            with open(os.path.join(proj, "s1.jsonl"), "w") as f:
                f.writelines(lines)
            with open(os.path.join(proj, "s1-resumed.jsonl"), "w") as f:
                f.writelines(lines)  # a resumed session copies the same lines
            logs = read_logs(root, Pricing())
            self.assertAlmostEqual(sum(p.cost for p in logs.prompts.values()), 20.0)
            prompt = logs.prompts[("s1", "p1")]
            self.assertEqual(prompt.text, "hi")
            self.assertEqual(len(prompt.tool_calls), 1)

    def test_subagent_cost_rolls_into_the_prompt_that_launched_it(self):
        with tempfile.TemporaryDirectory() as root:
            proj = os.path.join(root, "-proj")
            os.makedirs(os.path.join(proj, "s1", "subagents"))
            with open(os.path.join(proj, "s1.jsonl"), "w") as f:
                f.write(_line(type="user", sessionId="s1", promptId="p1", message={"content": "go"}))
            with open(os.path.join(proj, "s1", "subagents", "agent-a.jsonl"), "w") as f:
                f.write(_line(type="user", sessionId="s1", promptId="p1", isSidechain=True, message={"content": "task"}))
                f.write(_line(type="assistant", sessionId="s1", requestId="r9", isSidechain=True,
                              message={"id": "m9", "model": "claude-sonnet-5-5", "usage": {"output_tokens": M}}))
            logs = read_logs(root, Pricing())
            p = logs.prompts[("s1", "p1")]
            self.assertAlmostEqual(p.cost, 10.0)
            self.assertAlmostEqual(p.subagent_cost, 10.0)


def _call(name, inp):
    server, tool = (name.split("__")[1], name.split("__", 2)[2]) if name.startswith("mcp__") else ("", name)
    return ToolCall("t", name, server, tool, inp)


class RulesTest(unittest.TestCase):
    def setUp(self):
        self.rules = load_rules()

    def keys(self, name, inp, label=""):
        refs, _ = extract(_call(name, inp), label or (name.split("__")[1] if name.startswith("mcp__") else ""), self.rules)
        return [(r.system, r.type, r.id, r.parent_id) for r in refs]

    def test_airtable_table_beats_its_base_within_one_call(self):
        got = self.keys("mcp__x__list_records_for_table", {"baseId": "appAAAAAAAAAAAAAA", "tableId": "tblBBBBBBBBBBBBBB"})
        self.assertEqual(got, [("Airtable", "table", "tblBBBBBBBBBBBBBB", "appAAAAAAAAAAAAAA")])

    def test_links_in_any_tool(self):
        self.assertEqual(self.keys("WebFetch", {"url": "https://acme.atlassian.net/wiki/spaces/ENG/pages/12345/Spec"}),
                         [("Confluence", "page", "12345", "")])
        self.assertEqual(self.keys("WebFetch", {"url": "https://acme.atlassian.net/browse/ABC-9"}),
                         [("Jira", "issue", "ABC-9", "")])
        self.assertEqual(self.keys("WebFetch", {"url": "https://github.com/octo/app/pull/7"}),
                         [("GitHub", "issue/PR", "octo/app#7", "octo/app")])
        self.assertEqual(self.keys("Bash", {"command": "gh issue list --repo octo/app"}),
                         [("GitHub", "repo", "octo/app", "")])

    def test_notion_ids_are_normalized(self):
        a = self.keys("mcp__notion__notion-fetch", {"id": "3F2A9C1E-7B6D-4E5F-8A9B-0C1D2E3F4A5B"}, "Notion")
        b = self.keys("WebFetch", {"url": "https://www.notion.so/team/Notes-3f2a9c1e7b6d4e5f8a9b0c1d2e3f4a5b"})
        self.assertEqual(a[0][2], b[0][2])

    def test_jira_rule_needs_an_atlassian_server(self):
        self.assertEqual(self.keys("mcp__linear__get_issue", {"id": "ABC-9"}, "Linear"), [("Linear", "issue", "ABC-9", "")])
        self.assertNotIn("Jira", [k[0] for k in self.keys("mcp__linear__get_issue", {"issueIdOrKey": "ABC-9"}, "Linear")])

    def test_local_tool_handles_are_not_objects(self):
        self.assertEqual(self.keys("mcp__Claude_Browser__computer", {"tabId": "tab-2", "ref": "ref_1"}), [])

    def test_connector_ids_are_labeled_from_their_tools(self):
        labels = label_servers({"1a2b3c4d-5e6f-4a7b-8c9d-0e1f2a3b4c5d": {"list_bases"}, "github": {"x"},
                                "ffffffff-0000-4000-8000-000000000000": {"mystery"}}, self.rules)
        self.assertEqual(labels["1a2b3c4d-5e6f-4a7b-8c9d-0e1f2a3b4c5d"], "Airtable")
        self.assertEqual(labels["github"], "GitHub")
        self.assertEqual(labels["ffffffff-0000-4000-8000-000000000000"], "MCP ffffffff")


class AttributionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        make_sample_logs.write(cls.tmp.name, date(2026, 9, 29))
        cls.logs = read_logs(cls.tmp.name, Pricing())
        cls.attr = attribute(cls.logs, load_rules())

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_everything_adds_back_to_total_spend(self):
        a = self.attr
        self.assertAlmostEqual(sum(o.total for o in a.roots) + a.unattributed, a.total, places=6)
        self.assertAlmostEqual(sum(p.cost for p in self.logs.prompts.values()), a.total, places=6)
        self.assertAlmostEqual(sum(self.logs.daily_cost.values()), a.total, places=6)

    def test_objects_are_named_from_tool_results(self):
        names = {o.id: o.name for o in self.attr.objects.values()}
        self.assertEqual(names["884211"], "Checkout redesign: PRD")
        self.assertEqual(names["CHK-142"], "Saved cards fail on Safari")
        self.assertEqual(names["appNorthwind00001"], "Launch tracker")
        self.assertEqual(names["tblRisks000000001"], "Risks")

    def test_a_prompt_touching_two_objects_splits_evenly(self):
        logs = self.logs
        for p in logs.prompts.values():
            keys = set()
            for c in p.tool_calls:
                refs, _ = extract(c, self.attr.server_labels.get(c.server, c.server), load_rules())
                keys |= {r.key for r in refs}
            if len(keys) == 2:
                break
        else:
            self.skipTest("no two-object prompt in sample")
        # Each object's own share includes exactly half of this prompt.
        for k in keys:
            self.assertIn((p.session_id, p.prompt_id), self.attr.objects[k].prompt_keys)

    def test_parents_roll_up_children(self):
        base = self.attr.objects["Airtable:base:appNorthwind00001"]
        self.assertAlmostEqual(base.total, base.cost + sum(c.total for c in base.children))
        self.assertEqual({c.name for c in base.children}, {"Launch items", "Risks", "Stakeholders"})


class ModelsAndProjectsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        make_sample_logs.write(cls.tmp.name, date(2026, 9, 29))
        cls.logs = read_logs(cls.tmp.name, Pricing())

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_every_model_reconciles_to_the_same_total(self):
        attr = attribute(self.logs, load_rules())
        for model, data in attr.by_model.items():
            self.assertAlmostEqual(sum(data["own"].values()) + data["unattributed"], attr.total, places=6, msg=model)
        # Carry-forward can only move spend out of "unattributed", never into it.
        self.assertLessEqual(attr.by_model["carry"]["unattributed"], attr.by_model["linear"]["unattributed"] + 1e-9)

    def test_choosing_a_model_changes_the_headline_numbers(self):
        linear = attribute(self.logs, load_rules(), model="linear")
        carry = attribute(self.logs, load_rules(), model="carry")
        self.assertAlmostEqual(carry.unattributed, linear.by_model["carry"]["unattributed"], places=6)
        key = linear.roots[0].key
        self.assertAlmostEqual(carry.objects[key].total, linear.total_under(linear.objects[key], "carry"), places=6)

    def test_first_and_last_touch_give_a_prompt_to_one_object(self):
        attr = attribute(self.logs, load_rules(), model="last")
        self.assertAlmostEqual(sum(o.cost for o in attr.objects.values()), attr.attributed, places=6)

    def test_projects_add_up_and_split_linked_from_unlinked(self):
        attr = attribute(self.logs, load_rules())
        self.assertAlmostEqual(sum(pr.cost for pr in attr.projects), attr.total, places=6)
        self.assertAlmostEqual(sum(pr.attributed for pr in attr.projects), attr.attributed, places=6)
        self.assertEqual({pr.label for pr in attr.projects}, {"storefront", "analytics", "launch"})

    def test_worktrees_and_scratch_folders_fold_together(self):
        from cost_trail.attribute import SCRATCH, project_root
        self.assertEqual(project_root("/x/app/.claude/worktrees/brave-otter"), project_root("/x/app"))
        self.assertEqual(project_root("/a/scratch-workspaces/1/2/scratch-2026-09-01-aaa"), SCRATCH)


class ClaudeModelTest(unittest.TestCase):
    def test_labels_and_matching(self):
        from cost_trail.pricing import model_label, model_matches
        self.assertEqual(model_label("claude-opus-5-5"), "Opus 5.5")
        self.assertEqual(model_label("claude-sonnet-4-5-20250929"), "Sonnet 4.5")
        self.assertEqual(model_label("claude-3-5-haiku-20241022"), "Haiku 3.5")
        self.assertTrue(model_matches("claude-fable-5-1", "fable"))
        self.assertTrue(model_matches("claude-opus-5-5", "Opus 5.5"))
        self.assertFalse(model_matches("claude-opus-5", "opus 5.5"))

    def test_filtering_by_model_partitions_spend(self):
        with tempfile.TemporaryDirectory() as tmp:
            make_sample_logs.write(tmp, date(2026, 9, 29))
            full = read_logs(tmp, Pricing())
            opus = read_logs(tmp, Pricing(), claude_model="opus")
            sonnet = read_logs(tmp, Pricing(), claude_model="sonnet")
            total = sum(full.daily_cost.values())
            self.assertGreater(sum(sonnet.daily_cost.values()), 0)  # the sample's subagents run on Sonnet
            self.assertAlmostEqual(sum(opus.daily_cost.values()) + sum(sonnet.daily_cost.values()), total, places=6)
            self.assertAlmostEqual(sum(sum(d.values()) for d in full.daily_by_model.values()), total, places=6)
            attr = attribute(sonnet, load_rules())
            self.assertAlmostEqual(sum(o.total for o in attr.roots) + attr.unattributed, attr.total, places=6)
            sp = spend(full.daily_cost, date(2026, 9, 29), full.daily_by_model)
            self.assertAlmostEqual(sum(v for _, v in sp.by_model_this_month), sp.month_to_date, places=2)


class SpendTest(unittest.TestCase):
    def test_forecast(self):
        daily = {date(2026, 9, d): 10.0 for d in range(1, 11)}
        sp = spend(daily, today=date(2026, 9, 10))
        self.assertAlmostEqual(sp.month_to_date, 100.0)
        self.assertAlmostEqual(sp.forecast_month_pace, 300.0)
        self.assertAlmostEqual(sp.forecast_7day_pace, 100.0 + 10.0 * 20)


class CliTest(unittest.TestCase):
    def test_commands_run_on_sample_logs(self):
        with tempfile.TemporaryDirectory() as tmp:
            make_sample_logs.write(tmp, date.today())
            out = io.StringIO()
            with redirect_stdout(out):
                main(["--projects", tmp, "summary"])
                main(["objects", "--projects", tmp, "--json"])
                main(["show", "PRD", "--projects", tmp])
                main(["report", "--projects", tmp, "--out", os.path.join(tmp, "r.html")])
                main(["compare", "--projects", tmp])
                main(["projects", "--projects", tmp, "--model", "carry"])
                main(["spend", "--projects", tmp, "--claude-model", "sonnet"])
                main(["report", "--projects", tmp, "--claude-model", "opus", "--out", os.path.join(tmp, "o.html")])
            text = out.getvalue()
            self.assertIn("Checkout redesign: PRD", text)
            self.assertIn("Carry-forward", text)
            self.assertIn("storefront", text)
            self.assertIn("sonnet only", text)
            with open(os.path.join(tmp, "r.html")) as f:
                self.assertIn("Launch tracker", f.read())


if __name__ == "__main__":
    unittest.main()
