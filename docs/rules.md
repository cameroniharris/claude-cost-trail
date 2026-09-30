# Object rules

Objects are recognized by rules in [`cost_trail/rules.json`](../cost_trail/rules.json). To add your own, write a
JSON file with the same shape and pass it with `--rules my-rules.json`, or set `"rules": "~/path/my-rules.json"` in
`~/.config/claude-cost-trail/config.json`. Your rules are checked before the built-in ones.

## Two kinds of rule

**Key rules** match sibling keys inside one object of a tool call's input:

```json
{"system": "Airtable", "type": "table", "rank": 2,
 "keys":   {"base": "^baseId$", "table": "^(tableId|table)$"},
 "values": {"base": "^app[A-Za-z0-9]{14}$", "table": "^tbl[A-Za-z0-9]{14}$"},
 "id": "{table}",
 "parent": {"type": "base", "id": "{base}"}}
```

Every name in `keys` must match a key in the same dict (regex on the key name), and `values` optionally checks each
value. The captured values fill the `id` and `parent.id` templates.

**Pattern rules** run a regex with named groups over every string in the input, so links are caught whichever tool
carried them:

```json
{"system": "Jira", "type": "issue", "rank": 2,
 "pattern": "[A-Za-z0-9-]+\\.atlassian\\.net/browse/(?P<issue>[A-Z][A-Z0-9]+-\\d+)",
 "id": "{issue}"}
```

## Optional fields

| Field | Meaning |
|---|---|
| `servers` | Regex on the MCP server's label. Key rules need it when the key name is generic (`id`). |
| `tools` | Regex on the full tool name, e.g. `"^Bash$"` for rules that read shell commands. |
| `rank` | Specificity. Within one call, only the highest-ranked match per system counts (the issue, not also its repo). |
| `parent` | Makes this object a child. The parent's total includes it. |
| `normalize` | `{"group": "hex32"}` strips dashes and lowercases, so two spellings of the same ID merge. |
| `name_from_result` | For "get one thing" tools: use the result's top-level `title`/`name`/`summary` as the name. |

## Server labels

`server_signatures` maps a label to tool names. A connector that appears under a random ID gets the label of the first
signature it matches. Names you set in `server_names` in the config file always win.

## The generic fallback

For MCP servers no rule recognizes, any input whose key looks like an ID (`id`, `…Id`, `…_id`, `slug`) becomes an
object labeled with the server. Tune it or turn it off under `generic`. Local tools (browsers, simulators, the desktop
app) are excluded by `exclude_servers`, since their tab and build handles aren't shared objects.
