"""Recognize the objects (pages, issues, tables, repos...) that each tool call touched.

Rules are data (rules.json). Three kinds:
- `keys` rules match sibling keys inside one dict of a tool's input, e.g. an
  Airtable call with baseId + tableId.
- `pattern` rules run a regex over every string in the input, so URLs are caught
  whichever tool carried them (WebFetch, a browser, `gh` in Bash...).
- the `generic` fallback turns any ID-looking input of an unrecognized MCP tool
  into an object labeled with its server, so new connectors show up without a rule.

Per call and per system, only the most specific match is kept (an issue beats its
repo) so one call never splits its cost between a parent and its own child.
"""

import json
import os
import re
from dataclasses import dataclass

_HERE = os.path.dirname(os.path.abspath(__file__))
_UUIDISH = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-", re.I)
_NAME_KEYS = ("title", "name", "displayName", "summary", "full_name", "subject")


@dataclass(frozen=True)
class ObjectRef:
    system: str
    type: str
    id: str
    parent_type: str = ""
    parent_id: str = ""

    @property
    def key(self):
        return f"{self.system}:{self.type}:{self.id}"

    @property
    def parent_key(self):
        return f"{self.system}:{self.parent_type}:{self.parent_id}" if self.parent_id else ""


def load_rules(path=None, extra_path=None):
    with open(path or os.path.join(_HERE, "rules.json")) as f:
        rules = json.load(f)
    if extra_path:
        with open(os.path.expanduser(extra_path)) as f:
            extra = json.load(f)
        rules["objects"] = extra.get("objects", []) + rules["objects"]
        rules["server_signatures"].update(extra.get("server_signatures", {}))
        rules["generic"].update(extra.get("generic", {}))
    for r in rules["objects"]:
        r["_keys"] = {k: re.compile(v) for k, v in r.get("keys", {}).items()}
        r["_values"] = {k: re.compile(v) for k, v in r.get("values", {}).items()}
        r["_pattern"] = re.compile(r["pattern"]) if r.get("pattern") else None
        r["_servers"] = re.compile(r["servers"]) if r.get("servers") else None
        r["_tools"] = re.compile(r["tools"]) if r.get("tools") else None
    g = rules["generic"]
    g["_key"] = re.compile(g["key_pattern"])
    g["_exclude"] = re.compile(g["exclude_key_pattern"])
    g["_value"] = re.compile(g["value_pattern"])
    g["_servers"] = re.compile(g["exclude_servers"]) if g.get("exclude_servers") else None
    return rules


def label_servers(tools_by_server, rules, overrides=None):
    """Map each MCP server name to a readable label (e.g. a connector UUID -> 'Airtable')."""
    overrides = overrides or {}
    labels = {}
    for server, tools in tools_by_server.items():
        if server in overrides:
            labels[server] = overrides[server]
            continue
        systems = [n for n in rules["server_signatures"] if not n.startswith("_")]
        # A readable server name is kept (tidied to the known spelling, "github" -> "GitHub").
        label = next((n for n in systems if n.lower() == server.lower()), None)
        if label is None and _UUIDISH.match(server):
            # Connector IDs get a label from the tools they expose.
            label = next((n for n in systems
                          if any(t in tools for t in rules["server_signatures"][n])), None)
            label = label or f"MCP {server[:8]}"
        labels[server] = label or server
    return labels


def _walk(value, key=None, parent_key=None):
    """Yield (dict, key_in_parent) for every dict in a JSON-ish value, and (str, key) for strings."""
    if isinstance(value, dict):
        yield value, key
        for k, v in value.items():
            yield from _walk(v, k, key)
    elif isinstance(value, list):
        for v in value:
            yield from _walk(v, key, parent_key)
    elif isinstance(value, str):
        yield value, key


def _normalize(value, how):
    if how == "hex32":
        return value.replace("-", "").lower()
    return value


def _fill(template, groups):
    try:
        return template.format(**groups)
    except (KeyError, IndexError):
        return None


def _make(rule, groups):
    groups = {k: _normalize(str(v), rule.get("normalize", {}).get(k, "")) for k, v in groups.items() if v is not None}
    oid = _fill(rule["id"], groups)
    if not oid:
        return None
    parent = rule.get("parent") or {}
    pid = _fill(parent["id"], groups) if parent else ""
    return ObjectRef(rule["system"], rule["type"], oid, parent.get("type", ""), pid or "")


def extract(call, server_label, rules):
    """Objects touched by one tool call, and which of them a result title can name."""
    found = []  # (rank, ObjectRef, rule)
    items = list(_walk(call.input))
    for rule in rules["objects"]:
        if rule["_tools"] and not rule["_tools"].search(call.name):
            continue
        if rule["_servers"] and not (call.server and rule["_servers"].search(server_label)):
            continue
        if rule["_pattern"]:
            for item, _ in items:
                if isinstance(item, str):
                    for m in rule["_pattern"].finditer(item):
                        ref = _make(rule, m.groupdict())
                        if ref:
                            found.append((rule.get("rank", 1), ref, rule))
        elif rule["_keys"] and call.server:
            for item, _ in items:
                if not isinstance(item, dict):
                    continue
                groups = {}
                for name, key_re in rule["_keys"].items():
                    for k, v in item.items():
                        if isinstance(v, (str, int)) and not isinstance(v, bool) and key_re.search(k):
                            vre = rule["_values"].get(name)
                            if vre is None or vre.search(str(v)):
                                groups[name] = v
                                break
                if len(groups) == len(rule["_keys"]):
                    ref = _make(rule, groups)
                    if ref:
                        found.append((rule.get("rank", 1), ref, rule))

    g = rules["generic"]
    if (not found and call.server and g.get("enabled")
            and not (g["_servers"] and g["_servers"].search(call.server))):
        for item, key in items:
            if not isinstance(item, dict):
                continue
            for k, v in item.items():
                if not isinstance(v, str) or not g["_key"].search(k) or g["_exclude"].search(k):
                    continue
                if not g["_value"].search(v) or v.isdigit() and len(v) < 5:
                    continue
                kind = key if k == "id" and key else re.sub(r"(_?id|ID|_?slug)$", "", k) or k
                found.append((0, ObjectRef(server_label, kind, v), None))

    # Keep only the most specific match per system for this call.
    best = {}
    for rank, ref, rule in found:
        best.setdefault(ref.system, []).append((rank, ref, rule))
    refs, name_from_result = [], []
    for system, matches in best.items():
        top = max(m[0] for m in matches)
        for rank, ref, rule in matches:
            if rank == top and ref not in refs:
                refs.append(ref)
                if rule and rule.get("name_from_result"):
                    name_from_result.append(ref)
    return refs, name_from_result


def names_from_result(text, wanted_ids, single_ref=None):
    """Find human names for known object IDs in a tool result.

    Exact matches ({"id": X, "name": Y} anywhere in the JSON) are returned for any
    wanted ID. `single_ref` names the one object a "get this page/issue" call was
    about, from the result's top-level title.
    """
    out = {}
    if not text or len(text) > 3_000_000:
        return out
    stripped = text.lstrip()
    if not stripped.startswith(("{", "[")):
        return out
    try:
        data = json.loads(stripped)
    except ValueError:
        return out
    for item, _ in _walk(data):
        if not isinstance(item, dict):
            continue
        name = next((item[k] for k in _NAME_KEYS if isinstance(item.get(k), str) and item[k].strip()), None)
        if name is None and isinstance(item.get("fields"), dict):
            name = item["fields"].get("summary")
        if not name:
            continue
        # Only the object's own ID counts: {"id": X, "name": Y}, not {"baseId": X, "name": <a record>}.
        for k in ("id", "key"):
            v = item.get(k)
            if isinstance(v, str) and v in wanted_ids:
                out.setdefault(v, name)
    if single_ref is not None and isinstance(data, dict):
        name = next((data[k] for k in _NAME_KEYS if isinstance(data.get(k), str)), None)
        if name is None and isinstance(data.get("fields"), dict):
            name = data["fields"].get("summary")
        if name:
            out.setdefault(single_ref.id, name)
    return out
