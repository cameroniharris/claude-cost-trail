# claude-cost-trail — notes for Claude

Traces Claude Code spend (from local session logs) to the objects it touched. The README is written as a case study
in attribution terms; keep that framing when it changes. Standard library only, read-only, no network.

## Layout
- `cost_trail/parse.py` reads `~/.claude/projects/*/*.jsonl` + `*/<session>/subagents/*.jsonl` into `Prompt`s keyed by
  (sessionId, promptId). Assistant lines inherit the latest user line's promptId in the same file; subagent user lines
  carry the parent's promptId. Usage dedupe key = (message.id, requestId), global, files oldest-first. Large MCP results
  spill to `tool-results/*.txt`; `_spilled` follows the pointer so names can still be read.
- `pricing.py` + `pricing.json`: `model_label` ("Opus 5.5") and `model_matches` (for `--claude-model`, which filters
  whole assistant lines, tool calls included, at parse time; `daily_by_model` feeds the per-model spend card);
  longest-prefix model match; 5m/1h cache-write multipliers; fast multiplier per model.
  Prices from the claude-api skill's model table (cached 2026-09-25). Update `as_of` when changing.
- `rules.py` + `rules.json`: key rules, pattern rules, generic fallback, server labeling (UUID connectors labeled by
  tool signatures; readable names kept). Per call, per system, only the highest `rank` survives.
- `attribute.py`: per-prompt credit under four models (linear default, first, last, carry-forward within a session);
  all four computed every run into `by_model` for `compare`; `total_under(obj, model)` rolls up children. Projects:
  cwd → nearest ancestor with `.git` (worktrees folded, scratch sessions merged), label collisions get the parent name.
  Non-dollar object stats (prompts, sessions, dates) always count direct touches only.
- `cli.py` (argparse; shared options use SUPPRESS so they work before or after the subcommand), `report_html.py`
  (self-contained, light/dark tokens, `#query` deep link), `summary.py` (forecast, folder labels, session titles).
- Plugin: `.claude-plugin/{plugin,marketplace}.json`, `skills/cost-trail/SKILL.md` (runs `../../bin/cost-trail`).
- `examples/make_sample_logs.py`: synthetic "Northwind" dataset used by tests and README screenshots.

## Invariants (tests check them)
- sum(root totals) + unattributed == total == sum(daily_cost), to the cent, under every model.
- sum(project costs) == total; carry-forward unattributed <= linear unattributed.
- Never write to `~/.claude`, never touch the network.

## Checks before commit
- `python3 -m unittest discover tests`
- `claude plugin validate .` and `claude plugin validate .claude-plugin/plugin.json`
- Screenshots: regenerate sample (`--today` fixed), `report`, then headless Chrome with
  `--blink-settings=preferredColorScheme=1` (light), 2x scale; crop with `sips`.

## Ideas not built
- Weighting the split by tool calls instead of even (a fifth model).
- Persisting history past Claude Code's 30-day log cleanup (toktrack does this).
