---
name: cost-trail
description: Answer questions about what Claude Code work cost, from the local session logs. Month-to-date spend and a month-end forecast, and cost traced to the specific objects the work touched (Confluence pages, Jira and Linear issues, Airtable bases and tables, GitHub repos and PRs, Notion pages, and any other MCP connector's IDs). Use when the user asks "what did X cost", "how much have I spent this month", "am I on track this month", "which spec / ticket / table / repo is most expensive", "cost per page / issue / project", or wants a cost report.
---

# cost-trail

A local, read-only command reads `~/.claude/projects` and prices every response at
API list prices. The engine lives two levels above this skill's base directory:

```bash
python3 "<this skill's base directory>/../../bin/cost-trail" <command> [options]
```

Use the absolute path shown as this skill's base directory. Python 3.9+, no packages.

## Pick the command from the question

| The user asks | Run |
|---|---|
| "How much have I spent this month?" / "Am I on track?" / "by model" | `spend` (includes spend per Claude model) |
| "What did Fable / Opus / Sonnet cost?" / "only count Sonnet work" | any command with `--claude-model fable` (or `opus 5.5`, `sonnet`…) |
| "What did the checkout PRD cost?" / any one named thing | `show "<part of its name or ID>"` |
| "What's most expensive?" / "cost by page/ticket/table" | `objects` (add `--system Confluence` etc. to narrow) |
| "What did this repo / project / folder cost?" | `projects` (all spend by working folder, with its top objects) |
| "How sure is that number?" / "what if we counted it differently?" | `compare` (four attribution models side by side) |
| A general overview | `summary` (the default) |
| "Make me a report" / wants to browse | `report --out <path> --open` (self-contained HTML) |

Period options (put them after the command): `--days 7`, `--month 2026-09`,
`--since 2026-09-01 --until 2026-09-15`. Add `--json` when you need to compute
something further from the numbers. `--model first|last|carry` changes how a
prompt's cost is credited (default `linear`: split evenly across what it touched).

## How to answer

- Lead with the dollar figure, then the one or two drivers (top child objects or
  sessions from `show`). Round sensibly.
- Say once that these are **API list-price estimates**: on a Pro or Max plan the
  user isn't billed per token, so it means "what this would cost on the API".
- If `show` finds several matches, say which one you used or list them.
- If an object the user expects is missing, explain the rule: objects come from IDs
  and links in tool calls. Work done by reading a local file, or through a tool
  with no recognizable ID, counts as unattributed. Point to `docs/rules.md` in the
  plugin folder for adding a rule.
- Unattributed spend is normal (plain coding and chat touch no object);
  `projects` shows it by working folder. For a repo's total cost, use `projects`,
  not `objects`.
- When a number is contested, run `compare` and report the range across models,
  saying linear is the default and why (it doesn't credit follow-up prompts that
  touched nothing).
- The logs only go back as far as Claude Code keeps them (`cleanupPeriodDays`,
  default 30 days), so all-time numbers mean "all available logs".
