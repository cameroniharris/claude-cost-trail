"""claude-cost-trail: what your Claude Code work cost, traced to the things it touched."""

import argparse
import json
import os
import sys
import webbrowser
from datetime import date, datetime, time, timedelta

from . import __version__
from .attribute import MODELS, attribute
from .parse import read_logs
from .pricing import Pricing
from .rules import load_rules
from .summary import session_titles, spend

DEFAULT_CONFIG = "~/.config/claude-cost-trail/config.json"


def _load_config(path):
    path = os.path.expanduser(path or DEFAULT_CONFIG)
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return {}


def _day(s):
    return datetime.combine(date.fromisoformat(s), time()).astimezone()


def _window(args):
    since = _day(args.since) if args.since else None
    until = _day(args.until) + timedelta(1) if args.until else None
    if args.month:
        y, m = map(int, args.month.split("-"))
        since = datetime(y, m, 1).astimezone()
        until = datetime(y + (m == 12), m % 12 + 1, 1).astimezone()
    if args.days:
        since = datetime.combine(date.today() - timedelta(args.days - 1), time()).astimezone()
    return since, until


def _money(x):
    return f"${x:,.2f}" if abs(x) < 1000 else f"${x:,.0f}"


def _label(o):
    return o.name or o.id


def _load(args, spend_only=False):
    config = _load_config(args.config)
    projects = os.path.expanduser(args.projects or config.get("projects_dir") or "~/.claude/projects")
    if not os.path.isdir(projects):
        sys.exit(f"No Claude Code logs found at {projects} (use --projects to point elsewhere).")
    pricing = Pricing(args.pricing or config.get("pricing"))
    rules = load_rules(extra_path=args.rules or config.get("rules"))
    since, until = _window(args)
    cm = args.claude_model
    all_logs = read_logs(projects, pricing, claude_model=cm)  # spend/forecast always use the full history
    if spend_only:  # the spend view needs only daily totals: one read, no attribution
        return pricing, all_logs, all_logs, None, (since, until)
    logs = all_logs if not (since or until) else read_logs(projects, pricing, since, until, claude_model=cm)
    attr = attribute(logs, rules, config.get("server_names"), args.model or config.get("model") or "linear")
    return pricing, all_logs, logs, attr, (since, until)


def _period_label(window, logs, claude_model=None):
    text = _period_only(window, logs)
    return f"{text}, {claude_model} responses only" if claude_model else text


def _period_only(window, logs):
    since, until = window
    if not since and not until:
        first = min(logs.daily_cost) if logs.daily_cost else date.today()
        return f"all available logs (since {first:%b %-d, %Y})"
    a = since.date() if since else min(logs.daily_cost, default=date.today())
    b = (until - timedelta(1)).date() if until else date.today()
    return f"{a:%b %-d} – {b:%b %-d, %Y}"


# ---------- terminal output ----------

def cmd_spend(args, data=None):
    pricing, all_logs, logs, attr, window = data or _load(args, spend_only=True)
    sp = spend(all_logs.daily_cost, daily_by_model=all_logs.daily_by_model)
    rows = {
        "month_to_date": round(sp.month_to_date, 2),
        "forecast_month_end_at_month_pace": round(sp.forecast_month_pace, 2),
        "forecast_month_end_at_7day_pace": round(sp.forecast_7day_pace, 2),
        "last_month": round(sp.last_month, 2),
        "days_elapsed": sp.days_elapsed,
        "days_in_month": sp.days_in_month,
        "by_claude_model_this_month": {k: round(v, 2) for k, v in sp.by_model_this_month},
        "by_claude_model_last_month": {k: round(v, 2) for k, v in sp.by_model_last_month},
    }
    if args.json:
        print(json.dumps(rows, indent=2))
        return
    only = f", {args.claude_model} only" if args.claude_model else ""
    print(f"Claude Code spend, {sp.today:%B %Y}{only} (API list prices as of {pricing.as_of})")
    print(f"  So far this month   {_money(sp.month_to_date):>10}   ({sp.days_elapsed} of {sp.days_in_month} days)")
    print(f"  Month-end forecast  {_money(sp.forecast_month_pace):>10}   at this month's pace")
    print(f"                      {_money(sp.forecast_7day_pace):>10}   at the last 7 days' pace")
    print(f"  Last month          {_money(sp.last_month):>10}"
          + ("   (partial: logs start " + f"{sp.earliest_log:%b %-d})" if sp.earliest_log.month == (sp.today.replace(day=1) - timedelta(1)).month and sp.earliest_log.day > 1 else ""))
    if sp.by_model_this_month and not args.claude_model:
        print(f"  By Claude model     " + " · ".join(
            f"{k} {_money(v)} ({_pct(v, sp.month_to_date)})" for k, v in sp.by_model_this_month))
    _warn_unknown(pricing)


def cmd_objects(args, data=None):
    pricing, all_logs, logs, attr, window = data or _load(args)
    roots = [o for o in attr.roots if not args.system or o.system.lower() == args.system.lower()]
    if args.json:
        print(json.dumps([_obj_json(o) for o in roots[: args.top]], indent=2, default=str))
        return
    print(f"Cost by object, {_period_label(window, logs, args.claude_model)}")
    print(f"  {_money(attr.total)} total · {_money(attr.attributed)} linked to objects "
          f"({_pct(attr.attributed, attr.total)}) · {_money(attr.unattributed)} unattributed\n")
    print(f"  {'Cost':>9}  {'System':<12} {'Object':<44} {'Prompts':>7} {'Sessions':>8}  Last touched")
    for o in roots[: args.top]:
        _obj_line(o, 0)
        if args.children:
            for c in o.children[: args.children]:
                _obj_line(c, 1)
    if len(roots) > args.top:
        print(f"  … {len(roots) - args.top} more (use --top)")
    _warn_unknown(pricing)


def _obj_line(o, depth):
    name = ("  └ " if depth else "") + f"{_label(o)}"
    kind = o.type if depth else f"{o.system}"
    prompts = len(o.all_prompts)
    last = o.span[1]
    when = f"{last:%b %-d}" if last else ""
    print(f"  {_money(o.total):>9}  {kind[:12]:<12} {name[:44]:<44} {prompts:>7} {len(o.all_sessions):>8}  {when}")


def cmd_show(args, data=None):
    pricing, all_logs, logs, attr, window = data or _load(args)
    q = args.query.lower()
    matches = [o for o in attr.objects.values() if o.total > 0 and (q in o.id.lower() or q in o.name.lower())]
    matches.sort(key=lambda o: -o.total)
    if not matches:
        sys.exit(f'No object matches "{args.query}". Try `objects` to list them.')
    titles = session_titles(logs)
    if args.json:
        print(json.dumps([_obj_json(o, titles) for o in matches[:5]], indent=2, default=str))
        return
    for o in matches[:5]:
        print(f"{_label(o)}  ({o.system} {o.type} {o.id})")
        print(f"  {_money(o.total)} across {len(o.all_sessions)} sessions"
              + (f" · own share {_money(o.cost)}, rest from {len(o.children)} child objects" if o.children else ""))
        first, last = o.span
        if first:
            print(f"  First touched {first:%b %-d}, last {last:%b %-d} · {len(o.all_prompts)} prompts")
        for c in o.children[:10]:
            print(f"    └ {_money(c.total):>9}  {c.type:<8} {_label(c)}")
        sessions = _session_costs(o)
        print("  Top sessions:")
        for sid, dollars in sessions[:10]:
            print(f"    {_money(dollars):>9}  {titles.get(sid, sid[:8])[:70]}")
        print()


def _session_costs(o):
    totals = dict(o.session_cost)
    for c in o.children:
        for sid, v in _session_costs(c):
            totals[sid] = totals.get(sid, 0.0) + v
    return sorted(totals.items(), key=lambda kv: -kv[1])


def _obj_json(o, titles=None):
    d = {"system": o.system, "type": o.type, "id": o.id, "name": o.name, "cost": round(o.total, 4),
         "own_cost": round(o.cost, 4), "prompts": len(o.all_prompts), "tool_calls": o.calls,
         "sessions": len(o.all_sessions), "first_touched": o.span[0], "last_touched": o.span[1],
         "children": [_obj_json(c) for c in o.children]}
    if titles is not None:
        d["top_sessions"] = [{"title": titles.get(s, s), "cost": round(v, 4)} for s, v in _session_costs(o)[:10]]
    return d


def cmd_summary(args):
    data = _load(args)
    cmd_spend(args, data)
    print()
    args.top = min(args.top, 10)
    cmd_objects(args, data)
    pricing, all_logs, logs, attr, window = data
    if not args.json:
        print()
        args.top = 5
        args.objects = 0
        cmd_projects(args, data)


def cmd_projects(args, data=None):
    pricing, all_logs, logs, attr, window = data or _load(args)
    projects = [pr for pr in attr.projects if pr.cost > 0]
    if args.json:
        print(json.dumps([{"folder": pr.label, "path": pr.path, "cost": round(pr.cost, 4),
                           "linked_to_objects": round(pr.attributed, 4), "unattributed": round(pr.unattributed, 4),
                           "sessions": len(pr.sessions), "prompts": pr.prompts, "last_active": pr.last,
                           "top_objects": [{"object": _label(attr.objects[k]), "cost": round(v, 4)}
                                           for k, v in sorted(pr.object_cost.items(), key=lambda kv: -kv[1])[:5]]}
                          for pr in projects[: args.top]], indent=2, default=str))
        return
    print(f"Cost by project folder, {_period_label(window, logs, args.claude_model)}")
    print(f"  {'Cost':>9}  {'Folder':<34} {'Linked':>7} {'Sessions':>8}  Last active")
    for pr in projects[: args.top]:
        when = f"{pr.last:%b %-d}" if pr.last else ""
        print(f"  {_money(pr.cost):>9}  {pr.label[:34]:<34} {_pct(pr.attributed, pr.cost):>7} {len(pr.sessions):>8}  {when}")
        for key, dollars in sorted(pr.object_cost.items(), key=lambda kv: -kv[1])[: args.objects]:
            o = attr.objects[key]
            print(f"  {'':>9}    └ {_money(dollars):>8}  {_label(o)[:40]} ({o.system})")
    if len(projects) > args.top:
        print(f"  … {len(projects) - args.top} more (use --top)")
    print("  'Linked' is the share of a folder's spend that touched a specific object.")


def cmd_compare(args, data=None):
    pricing, all_logs, logs, attr, window = data or _load(args)
    models = list(MODELS)
    rows = [(o, [attr.total_under(o, m) for m in models]) for o in attr.roots[: args.top]]
    unattr = [attr.by_model[m]["unattributed"] for m in models]
    if args.json:
        print(json.dumps({"models": models,
                          "objects": [{"object": _label(o), "system": o.system,
                                       **{m: round(v, 4) for m, v in zip(models, vals)}} for o, vals in rows],
                          "unattributed": {m: round(v, 4) for m, v in zip(models, unattr)}}, indent=2))
        return
    print(f"Cost by object under four attribution models, {_period_label(window, logs, args.claude_model)}")
    print("  Same spend, split four ways. Each column adds up to the same total.\n")
    head = "".join(f"{MODELS[m]:>14}" for m in models)
    print(f"  {'Object':<38}{head}")
    for o, vals in rows:
        print(f"  {_label(o)[:37]:<38}" + "".join(f"{_money(v):>14}" for v in vals))
    print(f"  {'(unattributed)':<38}" + "".join(f"{_money(v):>14}" for v in unattr))
    swings = sorted(rows, key=lambda r: -(max(r[1]) - min(r[1])))[:3]
    if swings and max(swings[0][1]) - min(swings[0][1]) > 0.005:
        print("\n  Biggest disagreements:")
        for o, vals in swings:
            lo, hi = min(vals), max(vals)
            print(f"    {_label(o)[:40]}: {_money(lo)} ({MODELS[models[vals.index(lo)]]}) "
                  f"to {_money(hi)} ({MODELS[models[vals.index(hi)]]})")
    print("\n  Linear: split evenly across what a prompt touched.  First/Last touch: all to the first/last thing"
          "\n  touched.  Carry-forward: prompts that touched nothing inherit the session's previous objects.")


def cmd_report(args):
    from .report_html import render
    data = _load(args)
    pricing, all_logs, logs, attr, window = data
    out = os.path.expanduser(args.out)
    html = render(pricing, all_logs, logs, attr, _period_label(window, logs, args.claude_model), session_titles(logs),
                  args.claude_model)
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with open(out, "w") as f:
        f.write(html)
    print(f"Wrote {out}")
    if args.open:
        webbrowser.open("file://" + os.path.abspath(out))


def _pct(a, b):
    return f"{a / b:.0%}" if b else "0%"


def _warn_unknown(pricing):
    unknown = sorted(m for m in pricing.unknown_models if m)
    if unknown:
        print(f"\n  Note: no price listed for {', '.join(unknown)}; priced as {pricing.fallback}. "
              "Add them to pricing.json.", file=sys.stderr)


def main(argv=None):
    # Shared options work before or after the command; SUPPRESS stops a subcommand's
    # unset copy from overwriting a value given before it.
    common = argparse.ArgumentParser(add_help=False, argument_default=argparse.SUPPRESS)
    common.add_argument("--projects", help="Claude Code projects folder (default ~/.claude/projects)")
    common.add_argument("--config", help=f"config file (default {DEFAULT_CONFIG})")
    common.add_argument("--rules", help="extra object rules (JSON), added before the built-in ones")
    common.add_argument("--pricing", help="replacement pricing.json")
    common.add_argument("--since", help="start date YYYY-MM-DD")
    common.add_argument("--until", help="end date YYYY-MM-DD (inclusive)")
    common.add_argument("--month", help="a calendar month, YYYY-MM")
    common.add_argument("--days", type=int, help="the last N days")
    common.add_argument("--json", action="store_true", help="machine-readable output")
    common.add_argument("--claude-model", dest="claude_model",
                        help='only count responses from this Claude model, e.g. "fable", "opus 5.5", "sonnet"')
    common.add_argument("--model", choices=list(MODELS),
                        help="attribution model: linear (default), first, last, carry")

    ap = argparse.ArgumentParser(prog="cost-trail", description=__doc__, parents=[common])
    ap.add_argument("--version", action="version", version=f"claude-cost-trail {__version__}")
    sub = ap.add_subparsers(dest="cmd")
    p = sub.add_parser("summary", parents=[common], help="spend, forecast, and top objects (default)")
    p.add_argument("--top", type=int, default=10)
    p.add_argument("--system")
    p.add_argument("--children", type=int, default=0)
    sub.add_parser("spend", parents=[common], help="month-to-date spend and month-end forecast")
    p = sub.add_parser("objects", parents=[common], help="cost per object (page, issue, table, repo...)")
    p.add_argument("--top", type=int, default=25)
    p.add_argument("--system", help="only this system, e.g. Confluence")
    p.add_argument("--children", type=int, default=3, help="child objects to list under each (0 to hide)")
    p = sub.add_parser("projects", parents=[common], help="cost per working folder / repo, with its top objects")
    p.add_argument("--top", type=int, default=15)
    p.add_argument("--objects", type=int, default=3, help="top objects to list under each folder (0 to hide)")
    p = sub.add_parser("compare", parents=[common], help="object costs under four attribution models, side by side")
    p.add_argument("--top", type=int, default=15)
    p = sub.add_parser("show", parents=[common], help="one object's cost, children, and sessions")
    p.add_argument("query", help="part of an object's name or ID")
    p = sub.add_parser("report", parents=[common], help="write a self-contained HTML report")
    p.add_argument("--out", default="cost-trail-report.html")
    p.add_argument("--open", action="store_true", help="open it in your browser")

    args = ap.parse_args(argv)
    for k in ("projects", "config", "rules", "pricing", "since", "until", "month", "days", "system", "model", "claude_model"):
        if not hasattr(args, k):
            setattr(args, k, None)
    args.json = getattr(args, "json", False)
    if args.cmd in (None, "summary"):
        args.top = getattr(args, "top", 10)
        args.children = getattr(args, "children", 0)
        cmd_summary(args)
    else:
        {"spend": cmd_spend, "objects": cmd_objects, "show": cmd_show, "report": cmd_report,
         "projects": cmd_projects, "compare": cmd_compare}[args.cmd](args)


if __name__ == "__main__":
    main()
