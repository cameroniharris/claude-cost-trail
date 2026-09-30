#!/usr/bin/env python3
"""Write a fake ~/.claude/projects folder for demos and tests.

A made-up product team ("Northwind") ships a checkout redesign: specs in
Confluence, tickets in Jira, code in GitHub, a launch tracker in Airtable, notes
in Notion, plus plenty of plain coding that touches no object. Everything is
synthetic; the log shape matches real Claude Code 2.1.x logs.

    python3 examples/make_sample_logs.py /tmp/sample-projects [--today 2026-09-29]
"""

import argparse
import json
import os
import random
import uuid
from datetime import date, datetime, timedelta, timezone

ATLASSIAN = "c0ffee00-1234-4abc-9def-00000000a71a"   # a connector ID, as claude.ai connectors appear
AIRTABLE = "a17ab1e0-5678-4abc-9def-000000000001"
SITE = "northwind.atlassian.net"

PAGES = {"884211": "Checkout redesign: PRD", "884390": "Payments API v2: technical spec",
         "885002": "Q4 growth roadmap", "885117": "Checkout A/B test readout"}
ISSUES = {"CHK-142": "Saved cards fail on Safari", "CHK-150": "Add Apple Pay to checkout",
          "CHK-163": "Tax calculation off by one cent", "GRO-41": "Instrument checkout funnel events"}
BASE = ("appNorthwind00001", "Launch tracker")
TABLES = {"tblLaunchItems001": "Launch items", "tblRisks000000001": "Risks", "tblStakeholders01": "Stakeholders"}
NOTION = {"3f2a9c1e7b6d4e5f8a9b0c1d2e3f4a5b": "Design review notes"}
REPO = ("northwind", "storefront")

WORK = [
    # (weight, cwd, title, prompt, list of tool-call makers)
    (6, "storefront", "Draft PRD for checkout redesign", "Read the checkout PRD and tighten the success metrics",
     ["page:884211", "page:884211", "page:885002"]),
    (5, "storefront", "Payments API spec review", "Review the payments spec against the PRD and flag gaps",
     ["page:884390", "page:884211"]),
    (5, "storefront", "Fix Safari saved cards", "CHK-142 is back, find the cause and open a PR",
     ["issue:CHK-142", "gh:pr:318", "gh:repo"]),
    (4, "storefront", "Apple Pay integration", "Pick up CHK-150 and implement Apple Pay behind a flag",
     ["issue:CHK-150", "page:884390", "gh:pr:325"]),
    (3, "storefront", "Tax rounding bug", "Look at CHK-163 and add a regression test",
     ["issue:CHK-163", "gh:repo"]),
    (4, "analytics", "Funnel instrumentation", "Spec the checkout funnel events for GRO-41",
     ["issue:GRO-41", "page:885117"]),
    (4, "launch", "Update launch tracker", "Update the launch tracker with this week's status and risks",
     ["at:tblLaunchItems001", "at:tblRisks000000001", "at:tblLaunchItems001"]),
    (2, "launch", "Stakeholder list cleanup", "Dedupe the stakeholder table",
     ["at:tblStakeholders01"]),
    (2, "storefront", "Design review follow-ups", "Summarize the design review notes into tickets",
     ["notion:3f2a9c1e7b6d4e5f8a9b0c1d2e3f4a5b", "issue:CHK-150"]),
    (9, "storefront", "Refactor cart state", "Refactor the cart store to remove the legacy reducer", []),
    (6, "storefront", "Flaky e2e tests", "Why is the checkout e2e suite flaky?", []),
    (4, "analytics", "SQL for weekly conversion", "Write the weekly conversion query", []),
]


def call_for(spec):
    kind, _, arg = spec.partition(":")
    if kind == "page":
        name = f"mcp__{ATLASSIAN}__getConfluencePage"
        return name, {"cloudId": "b7e1-site", "pageId": arg}, {"id": arg, "title": PAGES[arg], "status": "current"}
    if kind == "issue":
        name = f"mcp__{ATLASSIAN}__getJiraIssue"
        return name, {"cloudId": "b7e1-site", "issueIdOrKey": arg}, {"key": arg, "fields": {"summary": ISSUES[arg]}}
    if kind == "at":
        name = f"mcp__{AIRTABLE}__list_records_for_table"
        return name, {"baseId": BASE[0], "tableId": arg, "pageSize": 50}, {"records": []}
    if kind == "notion":
        return "mcp__notion__notion-fetch", {"id": arg}, {"title": NOTION[arg], "content": "..."}
    if kind == "gh":
        sub, _, num = arg.partition(":")
        if sub == "pr":
            return ("mcp__github__pull_request_read", {"owner": REPO[0], "repo": REPO[1], "pullNumber": int(num)},
                    {"title": f"Fix for #{num}", "number": int(num)})
        return "Bash", {"command": f"gh pr list --repo {REPO[0]}/{REPO[1]} --state open"}, None
    raise ValueError(spec)


def usage(rng, scale=1.0):
    return {
        "input_tokens": rng.randint(2, 40),
        "cache_creation_input_tokens": int(rng.randint(800, 9000) * scale),
        "cache_read_input_tokens": int(rng.randint(40_000, 140_000) * scale),
        "output_tokens": int(rng.randint(300, 2500) * scale),
        "cache_creation": {"ephemeral_5m_input_tokens": 0, "ephemeral_1h_input_tokens": int(rng.randint(800, 9000) * scale)},
        "service_tier": "standard", "speed": "standard",
    }


def write(root, today, seed=7, days=45):
    rng = random.Random(seed)
    tz = timezone(timedelta(hours=-4))
    weights = [w for w, *_ in WORK]
    start = today - timedelta(days=days - 1)
    # Name the bases and tables once, as a "list" call would.
    naming_done = False
    for day_i in range(days):
        day = start + timedelta(day_i)
        if day.weekday() >= 5 and rng.random() < 0.7:
            continue
        for _ in range(rng.randint(2, 5)):
            _, folder, title, prompt, specs = rng.choices(WORK, weights)[0]
            cwd = f"/Users/demo/code/{folder}"
            proj = os.path.join(root, cwd.replace("/", "-"))
            os.makedirs(proj, exist_ok=True)
            sid = str(uuid.UUID(int=rng.getrandbits(128)))
            t = datetime.combine(day, datetime.min.time(), tz) + timedelta(hours=rng.randint(8, 18), minutes=rng.randint(0, 59))
            lines = [{"type": "custom-title", "customTitle": title, "sessionId": sid}]
            for turn in range(rng.randint(1, 3)):
                pid = str(uuid.UUID(int=rng.getrandbits(128)))
                text = prompt if turn == 0 else rng.choice(["Keep going", "Now update the tests", "Summarize what changed"])
                lines.append(_user(sid, pid, t, cwd, text))
                # Follow-ups often just edit code or talk, touching nothing (what carry-forward would credit).
                calls = list(specs) if turn == 0 else (rng.sample(specs, min(len(specs), 1)) if rng.random() < 0.4 else [])
                if not naming_done and any(s.startswith("at:") for s in calls):
                    lines += _named_list_call(sid, pid, t, cwd)
                    naming_done = True
                for spec in calls:
                    t += timedelta(seconds=rng.randint(10, 90))
                    name, inp, result = call_for(spec)
                    tid = "toolu_" + uuid.UUID(int=rng.getrandbits(128)).hex[:24]
                    lines.append(_assistant(sid, t, cwd, rng, [{"type": "tool_use", "id": tid, "name": name, "input": inp}]))
                    lines.append(_tool_result(sid, pid, t, cwd, tid, json.dumps(result) if result else "ok"))
                for _ in range(rng.randint(8, 30)):
                    t += timedelta(seconds=rng.randint(10, 120))
                    lines.append(_assistant(sid, t, cwd, rng, [{"type": "text", "text": "..."}]))
                if specs and turn == 0 and rng.random() < 0.3:
                    _subagent(proj, sid, pid, t, cwd, rng)
            with open(os.path.join(proj, f"{sid}.jsonl"), "w") as f:
                for line in lines:
                    f.write(json.dumps(line) + "\n")
    return root


def _named_list_call(sid, pid, t, cwd):
    tid = "toolu_listtables000000000001"
    result = {"tables": [{"id": k, "name": v} for k, v in TABLES.items()]}
    bases = {"bases": [{"id": BASE[0], "name": BASE[1]}]}
    return [
        _assistant(sid, t, cwd, random.Random(1), [{"type": "tool_use", "id": "toolu_searchbases00000000001",
                                                   "name": f"mcp__{AIRTABLE}__list_bases", "input": {}}]),
        _tool_result(sid, pid, t, cwd, "toolu_searchbases00000000001", json.dumps(bases)),
        _assistant(sid, t, cwd, random.Random(2), [{"type": "tool_use", "id": tid,
                                                   "name": f"mcp__{AIRTABLE}__list_tables_for_base",
                                                   "input": {"baseId": BASE[0]}}]),
        _tool_result(sid, pid, t, cwd, tid, json.dumps(result)),
    ]


def _subagent(proj, sid, pid, t, cwd, rng):
    folder = os.path.join(proj, sid, "subagents")
    os.makedirs(folder, exist_ok=True)
    aid = "a" + uuid.UUID(int=rng.getrandbits(128)).hex[:16]
    lines = [dict(_user(sid, pid, t, cwd, "Research task"), isSidechain=True, agentId=aid)]
    for _ in range(rng.randint(4, 10)):
        t += timedelta(seconds=20)
        lines.append(dict(_assistant(sid, t, cwd, rng, [{"type": "text", "text": "..."}], model="claude-sonnet-5-5"),
                          isSidechain=True, agentId=aid))
    with open(os.path.join(folder, f"agent-{aid}.jsonl"), "w") as f:
        for line in lines:
            f.write(json.dumps(line) + "\n")
    with open(os.path.join(folder, f"agent-{aid}.meta.json"), "w") as f:
        json.dump({"agentType": "general-purpose", "description": "Research task"}, f)


def _user(sid, pid, t, cwd, text):
    return {"type": "user", "sessionId": sid, "promptId": pid, "uuid": str(uuid.uuid4()), "cwd": cwd,
            "timestamp": t.isoformat(), "message": {"role": "user", "content": text}}


def _tool_result(sid, pid, t, cwd, tid, text):
    return {"type": "user", "sessionId": sid, "promptId": pid, "uuid": str(uuid.uuid4()), "cwd": cwd,
            "timestamp": t.isoformat(),
            "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": tid,
                                                      "content": [{"type": "text", "text": text}]}]}}


def _assistant(sid, t, cwd, rng, content, model="claude-opus-5-5"):
    return {"type": "assistant", "sessionId": sid, "uuid": str(uuid.uuid4()), "cwd": cwd, "timestamp": t.isoformat(),
            "requestId": "req_" + uuid.UUID(int=rng.getrandbits(128)).hex[:20],
            "message": {"id": "msg_" + uuid.UUID(int=rng.getrandbits(128)).hex[:24], "role": "assistant",
                        "model": model, "content": content, "usage": usage(rng)}}


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("out")
    ap.add_argument("--today", default=date.today().isoformat())
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args()
    write(a.out, date.fromisoformat(a.today), a.seed)
    print(f"Wrote sample logs to {a.out}")
