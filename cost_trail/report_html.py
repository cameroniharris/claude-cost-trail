"""A single self-contained HTML report: no network, no dependencies, works offline."""

from datetime import date
from html import escape

from . import __version__
from .attribute import MODELS
from .summary import spend

CSS = """
:root { color-scheme: light;
  --bg:#f7f7f5; --surface:#fcfcfb; --border:#e4e3df; --text:#0b0b0b; --text-2:#52514e; --muted:#76746f;
  --accent:#2a78d6; --accent-soft:#d9e7f8; --grid:#ebeae6; }
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) { color-scheme: dark;
  --bg:#111110; --surface:#1a1a19; --border:#2e2d2b; --text:#ffffff; --text-2:#c3c2b7; --muted:#9a998f;
  --accent:#3987e5; --accent-soft:#1f3350; --grid:#2a2a28; } }
:root[data-theme="dark"] { color-scheme: dark;
  --bg:#111110; --surface:#1a1a19; --border:#2e2d2b; --text:#ffffff; --text-2:#c3c2b7; --muted:#9a998f;
  --accent:#3987e5; --accent-soft:#1f3350; --grid:#2a2a28; }
* { box-sizing: border-box; }
body { margin:0; background:var(--bg); color:var(--text); font:15px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", Inter, sans-serif; }
main { max-width: 1040px; margin: 0 auto; padding: 32px 16px 64px; }
h1 { font-size: 24px; margin: 0 0 4px; } h2 { font-size: 18px; margin: 40px 0 4px; }
.sub { color: var(--text-2); margin: 0 0 20px; } .muted { color: var(--muted); }
.card { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 16px 20px; }
.tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 12px; }
.tile .label { color: var(--text-2); font-size: 13px; } .tile .value { font-size: 30px; font-weight: 600; margin: 2px 0; }
.tile.hero .value { font-size: 48px; } .tile .note { color: var(--muted); font-size: 13px; }
.chart { margin-top: 12px; position: relative; } svg { display:block; width:100%; height:auto; }
.tip { position:absolute; pointer-events:none; background:var(--text); color:var(--bg); font-size:12px; padding:4px 8px;
  border-radius:6px; white-space:nowrap; transform:translate(-50%,-110%); opacity:0; transition:opacity .08s; }
.row { display:grid; grid-template-columns: 96px 110px 1fr 70px 70px 80px; gap: 8px; align-items: baseline; padding: 8px 4px; }
.head { color: var(--text-2); font-size: 13px; border-bottom: 1px solid var(--border); }
.num { text-align: right; font-variant-numeric: tabular-nums; }
details.obj { border-bottom: 1px solid var(--border); } details.obj > summary { list-style: none; cursor: pointer; }
details.obj > summary::-webkit-details-marker { display: none; }
details.obj > summary .name::before { content: "▸ "; color: var(--muted); } details.obj[open] > summary .name::before { content: "▾ "; }
.name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.id { color: var(--muted); font-size: 12px; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
.detail { padding: 0 4px 14px 30px; font-size: 14px; }
.detail .child { display:grid; grid-template-columns: 86px 80px 1fr; gap: 8px; padding: 2px 0; }
.bar { height: 6px; border-radius: 3px; background: var(--accent); margin-top: 4px; }
.pill { display:inline-block; font-size:12px; padding:1px 8px; border-radius:999px; background:var(--accent-soft); color:var(--text); }
.chips { display:flex; flex-wrap:wrap; gap:6px; margin: 10px 0 4px; }
.chip { font: inherit; font-size: 13px; padding: 4px 12px; border-radius: 999px; cursor: pointer;
  border: 1px solid var(--border); background: var(--surface); color: var(--text); }
.chip .amt { color: var(--muted); margin-left: 4px; font-variant-numeric: tabular-nums; }
.chip[aria-pressed="true"] { background: var(--accent); border-color: var(--accent); color: #fff; }
.chip[aria-pressed="true"] .amt { color: rgba(255,255,255,.8); }
input[type=search] { width: 100%; max-width: 360px; padding: 8px 12px; border-radius: 8px; border:1px solid var(--border);
  background: var(--surface); color: var(--text); font: inherit; margin: 8px 0 4px; }
table { border-collapse: collapse; width: 100%; font-size: 14px; } td, th { padding: 6px 8px; border-bottom: 1px solid var(--border); text-align: left; }
th { color: var(--text-2); font-weight: 500; }
.mrow { display:grid; grid-template-columns: 110px 1fr 90px 44px 170px; gap: 10px; align-items:center; padding: 3px 0; }
@media (max-width: 640px) { .mrow { grid-template-columns: 90px 1fr 80px 40px; } }
code { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12px; }
.compare td.chosen, .compare th.chosen { background: var(--accent-soft); }
.compare td.name { max-width: 320px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.method p { margin: 6px 0; } .method { color: var(--text-2); font-size: 14px; }
footer { color: var(--muted); font-size: 12px; margin-top: 40px; }
@media (max-width: 640px) { .row { grid-template-columns: 80px 1fr 60px; } .row .hide-sm { display: none; }
  .tile.hero .value { font-size: 40px; } }
"""

JS = """
const tip = document.querySelector('.tip');
document.querySelectorAll('rect[data-tip]').forEach(r => {
  r.addEventListener('mouseenter', e => { tip.textContent = r.dataset.tip; tip.style.opacity = 1; });
  r.addEventListener('mousemove', e => { const b = r.closest('.chart').getBoundingClientRect();
    tip.style.left = (e.clientX - b.left) + 'px'; tip.style.top = (e.clientY - b.top) + 'px'; });
  r.addEventListener('mouseleave', () => tip.style.opacity = 0);
});
const q = document.getElementById('filter');
let system = '';
function applyFilter() {
  const v = q ? q.value.toLowerCase() : '';
  let shown = 0;
  document.querySelectorAll('details.obj:not(.proj)').forEach(d => {
    const ok = d.dataset.search.includes(v) && (!system || d.dataset.system === system);
    d.style.display = ok ? '' : 'none'; if (ok) shown++;
  });
  const empty = document.getElementById('no-match'); if (empty) empty.style.display = shown ? 'none' : '';
  // Scale the cost bars to the largest row still showing.
  const rows = [...document.querySelectorAll('details.obj:not(.proj)')].filter(d => d.style.display !== 'none');
  const top = Math.max(...rows.map(d => +d.dataset.cost), 0) || 1;
  rows.forEach(d => { const b = d.querySelector('.bar'); if (b) b.style.width = Math.max(2, d.dataset.cost / top * 100) + '%'; });
}
if (q) q.addEventListener('input', applyFilter);
document.querySelectorAll('.chip').forEach(c => c.addEventListener('click', () => {
  system = c.dataset.system;
  document.querySelectorAll('.chip').forEach(o => o.setAttribute('aria-pressed', o === c ? 'true' : 'false'));
  applyFilter();
}));
// report.html#checkout opens the first object whose name or ID contains "checkout".
const h = decodeURIComponent(location.hash.slice(1)).toLowerCase();
if (h) { const d = [...document.querySelectorAll('details.obj')].find(d => d.dataset.search.includes(h));
  if (d) { d.open = true; d.scrollIntoView({block: 'start'}); } }
"""


def _m(x):
    if x >= 1000:
        return f"${x:,.0f}"
    return f"${x:,.2f}"


def _chart(sp):
    days = sp.days_in_month
    values = dict(sp.daily_this_month)
    peak = max([v for v in values.values()] + [1.0])
    step = _nice_step(peak / 3)
    top = step * max(1, -(-peak // step))
    w, h, left, bottom, pad = 720, 220, 48, 24, 8
    plot_w, plot_h = w - left - pad, h - bottom - pad
    bw = plot_w / days
    parts = [f'<svg viewBox="0 0 {w} {h}" role="img" aria-label="Daily spend this month">']
    t = 0.0
    while t <= top + 1e-9:
        y = pad + plot_h - t / top * plot_h
        parts.append(f'<line x1="{left}" x2="{w - pad}" y1="{y:.1f}" y2="{y:.1f}" stroke="var(--grid)" stroke-width="1"/>')
        parts.append(f'<text x="{left - 6}" y="{y + 4:.1f}" text-anchor="end" font-size="11" fill="var(--muted)">${t:,.0f}</text>')
        t += step
    first = sp.today.replace(day=1)
    for i in range(days):
        d = first.replace(day=i + 1)
        x = left + i * bw + 1
        if d in values:
            v = values[d]
            bh = max(v / top * plot_h, 0.5 if v > 0 else 0)
            y = pad + plot_h - bh
            r = min(4, bw / 2 - 1, bh)
            parts.append(_bar(x, y, bw - 2, bh, r))
            parts.append(f'<rect x="{left + i * bw:.1f}" y="{pad}" width="{bw:.1f}" height="{plot_h}" fill="transparent" '
                         f'data-tip="{d:%a %b %-d}: {_m(v)}"/>')
        if (i + 1) in (1, 8, 15, 22, days):
            parts.append(f'<text x="{x + (bw - 2) / 2:.1f}" y="{h - 6}" text-anchor="middle" font-size="11" '
                         f'fill="var(--muted)">{d:%b %-d}</text>')
    parts.append(f'<line x1="{left}" x2="{w - pad}" y1="{pad + plot_h}" y2="{pad + plot_h}" stroke="var(--border)"/>')
    parts.append("</svg>")
    return "".join(parts)


def _bar(x, y, w, h, r):
    """A bar with rounded top corners, square at the baseline."""
    if h <= 0:
        return ""
    r = max(0.0, r)
    return (f'<path d="M{x:.1f},{y + h:.1f} L{x:.1f},{y + r:.1f} Q{x:.1f},{y:.1f} {x + r:.1f},{y:.1f} '
            f'L{x + w - r:.1f},{y:.1f} Q{x + w:.1f},{y:.1f} {x + w:.1f},{y + r:.1f} L{x + w:.1f},{y + h:.1f} Z" '
            f'fill="var(--accent)"/>')


def _nice_step(raw):
    for s in (1, 2, 5, 10, 20, 25, 50, 100, 200, 250, 500, 1000, 2000, 5000):
        if s >= raw:
            return s
    return 10000


def _session_costs(o):
    totals = dict(o.session_cost)
    for c in o.children:
        for sid, v in _session_costs(c):
            totals[sid] = totals.get(sid, 0.0) + v
    return sorted(totals.items(), key=lambda kv: -kv[1])


def _objects(attr, titles, limit=200):
    if not attr.roots:
        return '<p class="muted">No objects found in this period.</p>'
    top = attr.roots[0].total or 1
    out = ['<div class="row head"><span class="num">Cost</span><span>System</span><span>Object</span>'
           '<span class="num hide-sm">Prompts</span><span class="num">Sessions</span><span class="hide-sm">Last touched</span></div>']
    for o in attr.roots[:limit]:
        first, last = o.span
        label = o.name or o.id
        search = escape(f"{o.system} {o.type} {label} {o.id} " + " ".join(f"{c.name} {c.id}" for c in o.children).lower()).lower()
        detail = []
        detail.append(f'<div class="id">{escape(o.system)} {escape(o.type)} · {escape(o.id)}'
                      + (f' · first touched {first:%b %-d}' if first else "") + "</div>")
        if o.children:
            detail.append(f'<div style="margin-top:8px"><b>Inside it</b> <span class="muted">(own share {_m(o.cost)})</span></div>')
            for c in o.children[:12]:
                detail.append(f'<div class="child"><span class="num">{_m(c.total)}</span><span class="muted">{escape(c.type)}</span>'
                              f'<span class="name">{escape(c.name or c.id)}</span></div>')
            if len(o.children) > 12:
                detail.append(f'<div class="muted">…and {len(o.children) - 12} more</div>')
        detail.append('<div style="margin-top:8px"><b>Top sessions</b></div>')
        for sid, v in _session_costs(o)[:8]:
            detail.append(f'<div class="child"><span class="num">{_m(v)}</span><span></span>'
                          f'<span class="name">{escape(titles.get(sid, sid[:8]))}</span></div>')
        out.append(
            f'<details class="obj" data-search="{search}" data-system="{escape(o.system)}" data-cost="{o.total:.4f}"><summary class="row">'
            f'<span class="num">{_m(o.total)}<div class="bar" style="width:{max(2, o.total / top * 100):.0f}%"></div></span>'
            f'<span><span class="pill">{escape(o.system)}</span></span>'
            f'<span class="name" title="{escape(label)}">{escape(label)} <span class="muted">{escape(o.type)}</span></span>'
            f'<span class="num hide-sm">{len(o.all_prompts)}</span><span class="num">{len(o.all_sessions)}</span>'
            f'<span class="hide-sm">{f"{last:%b %-d}" if last else ""}</span></summary>'
            f'<div class="detail">{"".join(detail)}</div></details>')
    out.append('<p id="no-match" class="muted" style="display:none;padding:8px 4px">No objects match this filter.</p>')
    if len(attr.roots) > limit:
        out.append(f'<p class="muted">…{len(attr.roots) - limit} smaller objects not shown. Use the command line for the full list.</p>')
    return "".join(out)


def _projects(attr, titles, limit=40):
    projects = [pr for pr in attr.projects if pr.cost > 0]
    if not projects:
        return '<p class="muted">No spend in this period.</p>'
    top = projects[0].cost or 1
    out = ['<div class="row head"><span class="num">Cost</span><span>Linked</span><span>Folder</span>'
           '<span class="num hide-sm">Prompts</span><span class="num">Sessions</span><span class="hide-sm">Last active</span></div>']
    for pr in projects[:limit]:
        linked = pr.attributed / pr.cost if pr.cost else 0
        detail = [f'<div class="id">{escape(pr.path) if pr.path and not pr.path.startswith("(") else escape(pr.label)}</div>']
        objs = sorted(pr.object_cost.items(), key=lambda kv: -kv[1])[:6]
        if objs:
            detail.append('<div style="margin-top:8px"><b>Top objects</b></div>')
            for key, dollars in objs:
                o = attr.objects[key]
                detail.append(f'<div class="child"><span class="num">{_m(dollars)}</span><span class="muted">{escape(o.system)}</span>'
                              f'<span class="name">{escape(o.name or o.id)}</span></div>')
        detail.append(f'<div style="margin-top:8px"><b>Top sessions</b> <span class="muted">(unattributed {_m(pr.unattributed)})</span></div>')
        for sid, dollars in sorted(pr.session_cost.items(), key=lambda kv: -kv[1])[:6]:
            detail.append(f'<div class="child"><span class="num">{_m(dollars)}</span><span></span>'
                          f'<span class="name">{escape(titles.get(sid, sid[:8]))}</span></div>')
        when = f"{pr.last:%b %-d}" if pr.last else ""
        out.append(
            f'<details class="obj proj" data-search="{escape(pr.label.lower())}" data-system="" data-cost="{pr.cost:.4f}">'
            f'<summary class="row"><span class="num">{_m(pr.cost)}<div class="bar" style="width:{max(2, pr.cost / top * 100):.0f}%"></div></span>'
            f'<span class="muted">{linked:.0%}</span><span class="name">{escape(pr.label)}</span>'
            f'<span class="num hide-sm">{pr.prompts}</span><span class="num">{len(pr.sessions)}</span>'
            f'<span class="hide-sm">{when}</span></summary><div class="detail">{"".join(detail)}</div></details>')
    if len(projects) > limit:
        out.append(f'<p class="muted">…{len(projects) - limit} smaller folders not shown.</p>')
    return "".join(out)


def _compare(attr, limit=12):
    models = list(MODELS)
    rows = [(o, [attr.total_under(o, m) for m in models]) for o in attr.roots[:limit]]
    if not rows:
        return '<p class="muted">No objects to compare.</p>'
    head = "".join(f'<th class="num{" chosen" if m == attr.model else ""}">{escape(MODELS[m])}</th>' for m in models)
    body = []
    for o, vals in rows:
        cells = "".join(f'<td class="num{" chosen" if m == attr.model else ""}">{_m(v)}</td>' for m, v in zip(models, vals))
        body.append(f'<tr><td class="name">{escape(o.name or o.id)} <span class="muted">{escape(o.system)}</span></td>{cells}</tr>')
    un = "".join(f'<td class="num{" chosen" if m == attr.model else ""}">{_m(attr.by_model[m]["unattributed"])}</td>' for m in models)
    body.append(f'<tr class="muted"><td>Unattributed</td>{un}</tr>')
    o, vals = max(rows, key=lambda r: max(r[1]) - min(r[1]))
    lo, hi = min(vals), max(vals)
    note = ""
    if hi - lo > 0.005:
        note = (f'<p class="muted" style="margin:10px 0 0;font-size:14px">The models disagree most on '
                f'<b>{escape(o.name or o.id)}</b>: {_m(lo)} under {escape(MODELS[models[vals.index(lo)]])} to '
                f'{_m(hi)} under {escape(MODELS[models[vals.index(hi)]])}.</p>')
    legend = ('<p class="muted" style="margin:10px 0 0;font-size:13px"><b>Linear</b>: split evenly across what a prompt touched. '
              '<b>First / Last touch</b>: all of a prompt to the first / last thing it touched. '
              '<b>Carry-forward</b>: prompts that touched nothing inherit the session\'s previous objects '
              '(how Claude Code\'s own /usage worked before v2.1.222).</p>')
    return f'<table class="compare"><tr><th>Object</th>{head}</tr>{"".join(body)}</table>{note}{legend}'


def _chips(attr):
    """One button per system, biggest first, plus All."""
    totals = {}
    for o in attr.roots:
        totals[o.system] = totals.get(o.system, 0.0) + o.total
    if len(totals) < 2:
        return ""
    chips = [f'<button class="chip" data-system="" aria-pressed="true">All<span class="amt">{_m(attr.attributed)}</span></button>']
    for system, dollars in sorted(totals.items(), key=lambda kv: -kv[1]):
        chips.append(f'<button class="chip" data-system="{escape(system)}" aria-pressed="false">{escape(system)}'
                     f'<span class="amt">{_m(dollars)}</span></button>')
    return f'<div class="chips" role="group" aria-label="Filter by system">{"".join(chips)}</div>'


def _models_card(sp, claude_model):
    if claude_model:
        return (f'<div class="card" style="margin-top:12px"><div class="label muted" style="font-size:13px">'
                f'Showing only <b>{escape(claude_model)}</b> responses. Every number on this page is filtered.</div></div>')
    rows = sp.by_model_this_month
    if not rows:
        return ""
    last = dict(sp.by_model_last_month)
    top = rows[0][1] or 1
    items = []
    for label, dollars in rows:
        share = dollars / sp.month_to_date if sp.month_to_date else 0
        prev = f'last month {_m(last[label])}' if label in last else ""
        items.append(f'<div class="mrow"><span class="name">{escape(label)}</span>'
                     f'<span><div class="bar" style="width:{max(1, dollars / top * 100):.0f}%;margin:0"></div></span>'
                     f'<span class="num">{_m(dollars)}</span><span class="muted num">{share:.0%}</span>'
                     f'<span class="muted hide-sm" style="font-size:13px">{prev}</span></div>')
    return (f'<div class="card" style="margin-top:12px"><div class="label muted" style="font-size:13px;margin-bottom:6px">'
            f'By Claude model, {sp.today:%B}</div>{"".join(items)}'
            f'<div class="muted" style="font-size:13px;margin-top:6px">To filter every number to one model, run the report '
            f'with <code>--claude-model fable</code> (or opus, sonnet, haiku).</div></div>')


def render(pricing, all_logs, logs, attr, period_text, titles, claude_model=None):
    sp = spend(all_logs.daily_cost, daily_by_model=all_logs.daily_by_model)
    share = attr.attributed / attr.total if attr.total else 0
    daily_rows = "".join(f"<tr><td>{d:%a %b %-d}</td><td class='num'>{_m(v)}</td></tr>" for d, v in sp.daily_this_month)
    unknown = sorted(m for m in pricing.unknown_models if m)

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Claude Code cost trail</title><style>{CSS}</style></head>
<body><main>
<h1>Claude Code cost trail</h1>
<p class="sub">Estimated at API list prices (as of {escape(pricing.as_of)}). On a Pro or Max plan you aren't billed per token;
read these as what the work would cost on the API. Generated {date.today():%b %-d, %Y}.</p>

<div class="tiles">
  <div class="card tile hero"><div class="label">So far in {sp.today:%B}</div><div class="value">{_m(sp.month_to_date)}</div>
    <div class="note">{sp.days_elapsed} of {sp.days_in_month} days · last month {_m(sp.last_month)}</div></div>
  <div class="card tile"><div class="label">Month-end forecast</div><div class="value">{_m(sp.forecast_month_pace)}</div>
    <div class="note">at this month's pace · {_m(sp.forecast_7day_pace)} at the last 7 days' pace</div></div>
  <div class="card tile"><div class="label">Linked to a specific object</div><div class="value">{share:.0%}</div>
    <div class="note">{_m(attr.attributed)} of {_m(attr.total)}, {escape(period_text)}</div></div>
</div>

<div class="card chart" style="margin-top:12px"><div class="label muted" style="font-size:13px">Daily spend, {sp.today:%B %Y}</div>
{_chart(sp)}<div class="tip"></div>
<details><summary class="muted" style="font-size:13px;cursor:pointer">Show as table</summary><table><tr><th>Day</th><th class="num">Spend</th></tr>{daily_rows}</table></details>
</div>

{_models_card(sp, claude_model)}

<h2>Cost by object</h2>
<p class="sub">Pages, issues, tables, repos and other things your prompts touched, {escape(period_text)}.
Click a row for what's inside it and which sessions drove it.</p>
{_chips(attr)}
<input type="search" id="filter" placeholder="Filter by name, ID or system">
<div class="card" style="padding:4px 12px">{_objects(attr, titles)}</div>

<h2>Cost by project folder</h2>
<p class="sub">All spend by working folder (git worktrees fold into their repo). "Linked" is the share that touched a
specific object; the rest is mostly coding and chat. Click a folder for its top objects and sessions.</p>
<div class="card" style="padding:4px 12px">{_projects(attr, titles)}</div>

<h2>Compare attribution models</h2>
<p class="sub">The same spend split four ways. Every column adds up to the same total; what changes is who gets the credit.
This report uses <b>{escape(MODELS[attr.model])}</b>.</p>
<div class="card" style="overflow-x:auto">{_compare(attr)}</div>

<h2>How this is counted</h2>
<div class="card method">
<p><b>The unit is a prompt:</b> one message you typed plus everything Claude did in response, subagents included.</p>
<p><b>{"Each prompt's cost is split evenly" if attr.model == "linear" else "Each prompt's cost is credited by the " + escape(MODELS[attr.model]) + " model"}</b>
across the objects its tool calls touched (see the comparison above). A prompt that touched nothing counts as
unattributed. Object totals plus unattributed add up to the total under every model.</p>
<p><b>Parents include their children:</b> an Airtable base's total includes its tables; a repo's includes its issues and PRs.</p>
<p><b>Objects come from tool inputs:</b> IDs in MCP calls (base and table IDs, page IDs, issue keys) and links anywhere in a
tool call. Names come from what those tools returned.</p>
{f'<p><b>Unpriced models</b> (priced as {escape(pricing.fallback)}): {escape(", ".join(unknown))}</p>' if unknown else ''}
</div>
<footer>claude-cost-trail {__version__} · {attr.prompts_total:,} prompts · {len(logs.sessions):,} sessions · {all_logs.files_read:,} log files read locally; nothing left this machine.</footer>
</main><script>{JS}</script></body></html>"""
