"""Split each prompt's cost across the objects it touched, under a choice of models.

The unit is a prompt: one message you typed plus everything done in response,
subagents included. Models (the names come from marketing attribution):

- linear (default): split the prompt's cost evenly across the distinct objects
  it touched. A prompt that touched nothing is unattributed.
- first / last touch: give the whole prompt to the first / last object it
  touched, in time order.
- carry: linear, but a prompt that touched nothing inherits the objects of the
  session's previous prompt that did. This is how Claude Code's own /usage
  attribution worked before v2.1.222, when it was dropped for overstating
  the tool's share. It's here for comparison.

Under every model, object totals plus unattributed add back up to total spend.
Object stats that aren't dollars (prompts, sessions, dates) always count direct
touches only, so they don't change with the model.
"""

import os
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime

from .rules import extract, label_servers, names_from_result
from .summary import folder_label

MODELS = {"linear": "Linear", "first": "First touch", "last": "Last touch", "carry": "Carry-forward"}
_NEVER = datetime.max.replace(tzinfo=None)


@dataclass
class ObjectStats:
    key: str
    system: str
    type: str
    id: str
    parent_key: str = ""
    name: str = ""
    cost: float = 0.0          # this object's own share under the chosen model
    calls: int = 0
    prompts: int = 0
    sessions: set = field(default_factory=set)
    prompt_keys: set = field(default_factory=set)
    first: object = None
    last: object = None
    children: list = field(default_factory=list)
    session_cost: dict = field(default_factory=lambda: defaultdict(float))

    @property
    def total(self):
        """Own share plus everything attributed to child objects."""
        return self.cost + sum(c.total for c in self.children)

    @property
    def span(self):
        """(first, last) time touched, children included."""
        firsts = [x for x in [self.first] + [c.span[0] for c in self.children] if x]
        lasts = [x for x in [self.last] + [c.span[1] for c in self.children] if x]
        return (min(firsts) if firsts else None, max(lasts) if lasts else None)

    @property
    def all_prompts(self):
        s = set(self.prompt_keys)
        for c in self.children:
            s |= c.all_prompts
        return s

    @property
    def all_sessions(self):
        s = set(self.sessions)
        for c in self.children:
            s |= c.all_sessions
        return s


@dataclass
class Project:
    """All spend in one working folder (git worktrees fold into their repo)."""
    path: str
    label: str
    cost: float = 0.0
    attributed: float = 0.0
    prompts: int = 0
    sessions: set = field(default_factory=set)
    last: object = None
    object_cost: dict = field(default_factory=lambda: defaultdict(float))
    session_cost: dict = field(default_factory=lambda: defaultdict(float))

    @property
    def unattributed(self):
        return self.cost - self.attributed


@dataclass
class Attribution:
    objects: dict                 # key -> ObjectStats (every level)
    roots: list                   # top-level ObjectStats, biggest first
    total: float
    attributed: float
    unattributed: float
    prompts_total: int
    prompts_attributed: int
    server_labels: dict
    model: str = "linear"
    projects: list = field(default_factory=list)    # Project, biggest first
    by_model: dict = field(default_factory=dict)    # model -> {"own": {key: $}, "unattributed": $}

    def total_under(self, obj, model):
        """An object's total (children included) under another model."""
        own = self.by_model[model]["own"]
        return own.get(obj.key, 0.0) + sum(self.total_under(c, model) for c in obj.children)


def attribute(logs, rules, server_names=None, model="linear"):
    if model not in MODELS:
        raise ValueError(f"unknown model {model!r}; choose from {', '.join(MODELS)}")
    tools_by_server = defaultdict(set)
    for p in logs.prompts.values():
        for c in p.tool_calls:
            if c.server:
                tools_by_server[c.server].add(c.tool)
    labels = label_servers(tools_by_server, rules, server_names)

    objects = {}
    to_name = []        # (tool result text, the one object a "get" call was about, or None)
    touches = []        # (prompt, [ObjectRef in time order]) for every priced prompt

    def stats_for(ref, parent=False):
        key = ref.parent_key if parent else ref.key
        if key not in objects:
            if parent:
                objects[key] = ObjectStats(key, ref.system, ref.parent_type, ref.parent_id)
            else:
                objects[key] = ObjectStats(key, ref.system, ref.type, ref.id, ref.parent_key)
        return objects[key]

    for p in logs.prompts.values():
        if p.cost <= 0:
            continue  # nothing billed in this window (or for this Claude model)
        touched = {}
        for call in sorted(p.tool_calls, key=lambda c: c.ts.replace(tzinfo=None) if c.ts else _NEVER):
            refs, single = extract(call, labels.get(call.server, call.server), rules)
            for ref in refs:
                touched.setdefault(ref.key, ref)
                stats_for(ref).calls += 1
                if ref.parent_key:
                    stats_for(ref, parent=True)
            if call.id in logs.tool_results:
                # Any MCP result may name objects (a "search bases" call names the base others use).
                to_name.append((logs.tool_results[call.id], single[0] if len(single) == 1 else None))
        touches.append((p, list(touched.values())))
        for ref in touched.values():
            o = objects[ref.key]
            o.prompts += 1
            o.prompt_keys.add((p.session_id, p.prompt_id))
            o.sessions.add(p.session_id)
            if p.start:
                o.first = min(o.first, p.start) if o.first else p.start
                o.last = max(o.last, p.end or p.start) if o.last else (p.end or p.start)

    # Dollars under every model (for the comparison), then apply the chosen one.
    by_model = {}
    credits = None
    for m in MODELS:
        m_credits = _allocate(touches, m)
        own = defaultdict(float)
        for _, split in m_credits:
            for key, dollars in split.items():
                own[key] += dollars
        total = sum(p.cost for p, _ in touches)
        by_model[m] = {"own": dict(own), "unattributed": total - sum(own.values())}
        if m == model:
            credits = m_credits

    projects = {}
    total = attributed = 0.0
    n_attr = 0
    for p, split in credits:
        total += p.cost
        session = logs.sessions.get(p.session_id)
        root = project_root(p.cwd or (session.cwd if session else ""))
        proj = projects.get(root) or projects.setdefault(root, Project(root, folder_label(root)))
        proj.cost += p.cost
        proj.prompts += 1
        proj.sessions.add(p.session_id)
        proj.session_cost[p.session_id] += p.cost
        if p.end or p.start:
            proj.last = max(proj.last, p.end or p.start) if proj.last else (p.end or p.start)
        if not split:
            continue
        n_attr += 1
        attributed += p.cost
        proj.attributed += p.cost
        for key, dollars in split.items():
            objects[key].cost += dollars
            objects[key].session_cost[p.session_id] += dollars
            proj.object_cost[key] += dollars

    _name_objects(objects, to_name)
    for o in objects.values():
        if o.parent_key and o.parent_key in objects:
            objects[o.parent_key].children.append(o)
    for o in objects.values():
        o.children.sort(key=lambda c: -c.total)
    roots = sorted((o for o in objects.values() if not o.parent_key or o.parent_key not in objects),
                   key=lambda o: -o.total)
    roots = [o for o in roots if o.total > 0]

    project_list = sorted(projects.values(), key=lambda pr: -pr.cost)
    _disambiguate(project_list)
    return Attribution(objects, roots, total, attributed, total - attributed, len(touches), n_attr,
                       labels, model, project_list, by_model)


def _allocate(touches, model):
    """[(prompt, {object_key: dollars})] under one model; an empty dict means unattributed."""
    out = []
    if model == "carry":
        by_session = defaultdict(list)
        for p, refs in touches:
            by_session[p.session_id].append((p, refs))
        for items in by_session.values():
            items.sort(key=lambda it: _when(it[0]))
            inherited = []
            for p, refs in items:
                keys = [r.key for r in refs] or inherited
                if refs:
                    inherited = keys
                out.append((p, {k: p.cost / len(keys) for k in keys} if keys else {}))
        return out
    for p, refs in touches:
        keys = [r.key for r in refs]
        if not keys:
            out.append((p, {}))
        elif model == "first":
            out.append((p, {keys[0]: p.cost}))
        elif model == "last":
            out.append((p, {keys[-1]: p.cost}))
        else:
            out.append((p, {k: p.cost / len(keys) for k in keys}))
    return out


def _when(p):
    t = p.start or p.end
    return t.replace(tzinfo=None) if t else _NEVER


def _name_objects(objects, to_name):
    """Exact {"id": X, "name": Y} matches in any tool result beat a "get" call's title."""
    all_ids = {o.id for o in objects.values()}
    exact, single_names = {}, {}
    for text, single in to_name:
        for oid, name in names_from_result(text, all_ids, single).items():
            if single is not None and oid == single.id:
                single_names.setdefault(oid, name)
            else:
                exact.setdefault(oid, name)
    for o in objects.values():
        o.name = exact.get(o.id) or single_names.get(o.id) or ""


_ROOT_CACHE = {}
SCRATCH = "(no folder: scratch sessions)"


def project_root(cwd):
    """The folder a session belongs to: the enclosing git repo if there is one, worktrees folded in."""
    if not cwd:
        return ""
    if cwd in _ROOT_CACHE:
        return _ROOT_CACHE[cwd]
    path = cwd
    for marker in ("/.claude/worktrees/", "/.worktrees/"):
        if marker in path:
            path = path.split(marker)[0]
    if "scratch-workspaces" in path:
        _ROOT_CACHE[cwd] = SCRATCH
        return SCRATCH
    root = path
    home = os.path.expanduser("~")
    probe = path
    while probe and probe not in ("/", home):
        if os.path.exists(os.path.join(probe, ".git")):
            root = probe
            break
        probe = os.path.dirname(probe)
    _ROOT_CACHE[cwd] = root
    return root


def _disambiguate(projects):
    """Two folders with the same name get their parent folder added: "Work/notes" vs "Home/notes"."""
    counts = defaultdict(int)
    for pr in projects:
        counts[pr.label] += 1
    for pr in projects:
        if counts[pr.label] > 1 and pr.path and not pr.label.startswith(("(", "~")):
            parent = os.path.basename(os.path.dirname(pr.path.rstrip("/")))
            pr.label = f"{parent}/{pr.label}"
