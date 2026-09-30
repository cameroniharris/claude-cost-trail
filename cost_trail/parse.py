"""Read Claude Code's local session logs (~/.claude/projects) into priced prompts.

The unit of work is a *prompt*: one message you typed plus everything Claude did
in response to it, including any subagents it launched. Claude Code stamps every
user-side log line with a `promptId`, and subagent logs carry the ID of the
prompt that spawned them, so grouping is read from the data rather than guessed.

Log facts this relies on (checked against Claude Code 2.1.x logs):
- A response is split across several lines (one per content block), each
  repeating the same `usage`. Usage is counted once per (message.id, requestId).
- Resumed or forked sessions copy earlier lines into new files. The same key
  dedupes those, so nothing is counted twice.
- Assistant lines carry no promptId; they belong to the latest prompt seen above
  them in the same file.
"""

import glob
import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime

from .pricing import model_label, model_matches


@dataclass
class ToolCall:
    id: str
    name: str      # full tool name, e.g. mcp__atlassian__getConfluencePage
    server: str    # MCP server name ("" for built-in tools like Bash)
    tool: str      # tool name without the mcp__server__ prefix
    input: dict
    ts: datetime = None


@dataclass
class Prompt:
    session_id: str
    prompt_id: str
    cwd: str = ""
    text: str = ""
    start: datetime = None
    end: datetime = None
    cost: float = 0.0
    subagent_cost: float = 0.0
    responses: int = 0
    tool_calls: list = field(default_factory=list)


@dataclass
class Session:
    id: str
    title: str = ""
    cwd: str = ""
    start: datetime = None
    end: datetime = None


@dataclass
class Logs:
    prompts: dict           # (session_id, prompt_id) -> Prompt
    sessions: dict          # session_id -> Session
    tool_results: dict      # tool_use_id -> result text (MCP tools only, for naming objects)
    files_read: int = 0
    daily_cost: dict = field(default_factory=dict)  # date -> dollars, every response counted
    daily_by_model: dict = field(default_factory=dict)  # "Opus 5.5" -> {date -> dollars}


def _ts(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone()
    except ValueError:
        return None


def _split_tool_name(name):
    if name.startswith("mcp__"):
        parts = name.split("__")
        if len(parts) >= 3:
            return parts[1], "__".join(parts[2:])
    return "", name


def _result_text(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(c.get("text", "") for c in content if isinstance(c, dict))
    return ""


_SPILL = re.compile(r"Output has been saved to (\S+?\.(?:txt|json))")


def _spilled(text):
    """Large tool results are written to a side file; the log only keeps a pointer to it."""
    m = _SPILL.search(text[:2000]) if text.startswith("Error: result") else None
    if m and os.path.exists(m.group(1)) and os.path.getsize(m.group(1)) < 3_000_000:
        with open(m.group(1), encoding="utf-8", errors="replace") as f:
            return f.read()
    return text


def find_log_files(root):
    """Main session files first (oldest first, so originals win over resumed copies), then subagents."""
    main = glob.glob(os.path.join(root, "*", "*.jsonl"))
    subs = glob.glob(os.path.join(root, "*", "*", "subagents", "*.jsonl"))
    main.sort(key=os.path.getmtime)
    subs.sort(key=os.path.getmtime)
    return main + subs


def read_logs(root, pricing, since=None, until=None, claude_model=None):
    """Parse every log under `root`.

    `since`/`until` are aware datetimes bounding response time. `claude_model` keeps only
    responses from matching models ("fable", "opus 5.5"...); their tool calls go with them.
    """
    prompts, sessions, tool_results, daily, by_model = {}, {}, {}, {}, {}
    seen_responses, seen_tools = set(), set()
    mcp_tool_ids = set()
    files = find_log_files(root)
    since_epoch = since.timestamp() if since else None

    for path in files:
        if since_epoch and os.path.getmtime(path) < since_epoch:
            continue  # nothing in a file last written before the window can fall inside it
        is_subagent = os.sep + "subagents" + os.sep in path
        current = None  # promptId of the latest user line in this file
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                if '"assistant"' not in line and '"user"' not in line and '"custom-title"' not in line:
                    continue
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                kind = d.get("type")
                sid = d.get("sessionId")
                if not sid:
                    continue
                s = sessions.get(sid) or sessions.setdefault(sid, Session(sid))
                if kind == "custom-title":
                    s.title = d.get("customTitle") or s.title
                    continue
                if kind not in ("user", "assistant"):
                    continue
                if not s.cwd and d.get("cwd"):
                    s.cwd = d["cwd"]
                msg = d.get("message") if isinstance(d.get("message"), dict) else {}
                ts = _ts(d.get("timestamp"))

                if kind == "user":
                    current = d.get("promptId") or current
                    content = msg.get("content")
                    if isinstance(content, list):
                        for block in content:
                            if isinstance(block, dict) and block.get("type") == "tool_result":
                                tid = block.get("tool_use_id")
                                if tid in mcp_tool_ids and tid not in tool_results:
                                    tool_results[tid] = _spilled(_result_text(block.get("content")))
                    if not current:
                        continue
                    p = _prompt(prompts, sid, current, d)
                    if not is_subagent and not p.text and not d.get("isMeta"):
                        text = content if isinstance(content, str) else ""
                        if isinstance(content, list) and not any(
                                isinstance(b, dict) and b.get("type") == "tool_result" for b in content):
                            text = _result_text(content)
                        if text and not text.lstrip().startswith("<"):
                            p.text = text.strip()[:300]
                    continue

                # assistant line
                if ts and ((since and ts < since) or (until and ts >= until)):
                    continue
                if claude_model and not model_matches(msg.get("model"), claude_model):
                    continue
                p = _prompt(prompts, sid, current or f"no-prompt:{os.path.basename(path)}", d)
                usage = msg.get("usage")
                key = (msg.get("id"), d.get("requestId"))
                if usage and key not in seen_responses:
                    seen_responses.add(key)
                    dollars = pricing.cost(msg.get("model"), usage)
                    p.cost += dollars
                    p.responses += 1
                    if is_subagent:
                        p.subagent_cost += dollars
                    if ts:
                        day = ts.date()
                        daily[day] = daily.get(day, 0.0) + dollars
                        per = by_model.setdefault(model_label(msg.get("model")), {})
                        per[day] = per.get(day, 0.0) + dollars
                if ts:
                    p.start = min(p.start, ts) if p.start else ts
                    p.end = max(p.end, ts) if p.end else ts
                    s.start = min(s.start, ts) if s.start else ts
                    s.end = max(s.end, ts) if s.end else ts
                for block in msg.get("content") or []:
                    if not (isinstance(block, dict) and block.get("type") == "tool_use"):
                        continue
                    tid = block.get("id")
                    if tid in seen_tools:
                        continue
                    seen_tools.add(tid)
                    server, tool = _split_tool_name(block.get("name", ""))
                    if server:
                        mcp_tool_ids.add(tid)
                    p.tool_calls.append(ToolCall(tid, block.get("name", ""), server, tool,
                                                 block.get("input") or {}, ts))

    return Logs(prompts, sessions, tool_results, len(files), daily, by_model)


def _prompt(prompts, sid, pid, d):
    key = (sid, pid)
    p = prompts.get(key)
    if p is None:
        p = prompts[key] = Prompt(sid, pid, cwd=d.get("cwd", ""))
    return p
