# Prior art (surveyed September 2026)

Before building this I looked for a tool that already traces Claude Code cost to individual objects. I searched the
web, Reddit and GitHub (about 25 tools in all) and didn't find one. Here is what exists, grouped by what it attributes
cost to.

| Attributes cost to | Tools |
|---|---|
| Day, month, session; spend forecasts | [ccusage](https://github.com/ccusage/ccusage) (the most-used), [claudetop](https://github.com/liorwn/claudetop), [toktrack](https://github.com/mag123c/toktrack), [claudecounter](https://github.com/jverhoeks/claudecounter), and many smaller trackers |
| MCP server, skill, subagent | Claude Code's built-in `/usage` attribution; [agent-cost-mcp](https://github.com/vk0dev/agent-cost-mcp) (per tool, subagent tree, branch); [claude-cost-attribution](https://github.com/bengodgart/claude-cost-attribution) (per skill and subagent, with a "span" heuristic similar in spirit to this tool's per-prompt split); [ccblame](https://github.com/rupaut98/ccblame) |
| Git branch or feature | [mission-control](https://github.com/ALJAZEERAPLUS/mission-control) (from branch names); claudetop session tags (set by hand) |
| Merged PR or shipped feature | [tuneloop](https://github.com/tuneloop/tuneloop); Anthropic's admin analytics "cost per commit" (Team and Enterprise plans) |
| **An object followed across sessions by its ID** (page, ticket, table, record) | **none found**, which is this tool's reason to exist |

The PR-level tools come closest. The difference is scope: most knowledge work done through Claude Code never becomes a
PR (a spec drafted in Confluence, a ticket triaged in Jira, a tracker updated in Airtable), but it still leaves an ID
in the logs.
