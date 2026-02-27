# Claude Code

Session schemas for [Claude Code](https://github.com/anthropics/claude-code) CLI.

## Session Location

```
~/.claude/projects/<project-path>/*.jsonl
~/.claude/projects/<project-path>/<session-id>/subagents/*.jsonl
~/.claude/history.jsonl
```

The `<project-path>` is the absolute path with `/` replaced by `-`:
- `/Users/alice/myapp` → `-Users-alice-myapp`

## Files

| File | Description |
|------|-------------|
| `v2.0.76/session.schema.json` | Session schema for CLI ≤ 2.0.x |
| `v2.1.1/session.schema.json` | Session schema for CLI 2.1.0–2.1.1 |
| `v2.1.59/session.schema.json` | Session schema for CLI 2.1.2–2.1.59+ |
| `history.schema.json` | Schema for `~/.claude/history.jsonl` |
| `validate.py` | Validation script (auto-detects version) |

## Message Types

| Type | Since | Description |
|------|-------|-------------|
| `user` | 2.0.x | User input |
| `assistant` | 2.0.x | Claude's response |
| `system` | 2.0.x | System events (commands, errors, hooks) |
| `summary` | 2.0.x | Conversation summary |
| `file-history-snapshot` | 2.0.x | File backup tracking |
| `queue-operation` | 2.0.x | Message queue operations |
| `progress` | 2.1.2+ | Streaming progress events (~44% of JSONL lines) |
| `pr-link` | 2.1.x | Pull request link record |

## Version Differences

### v2.1.59 (covers 2.1.2+)

**New message types:**
- `progress` — 7 subtypes: `mcp_progress`, `bash_progress`, `hook_progress`, `agent_progress`, `waiting_for_task`, `query_update`, `search_results_received`
- `pr-link` — lightweight PR link with `prNumber`, `prUrl`, `prRepository`

**New built-in tools (12):**
`ToolSearch`, `SendMessage`, `TaskCreate`, `TaskUpdate`, `TaskList`, `TaskGet`, `TeamCreate`, `TeamDelete`, `TaskStop`, `EnterWorktree`, `ListMcpResourcesTool`, `ReadMcpResourceTool`

**New content block:**
- `tool_reference` — compact tool reference with `tool_name` (returned by ToolSearch)

**New fields on existing types:**
- `UserMessage`: `permissionMode` (enum: default, acceptEdits, bypassPermissions, dontAsk, plan)
- `UserMessage`/`AssistantMessage`: `teamName`
- `ToolUseBlock`: `caller` (e.g., `{"type": "direct"}`)
- `UsageInfo`: `inference_geo`, `iterations`, `speed`
- `SystemMessage`: `bridge_status` subtype with `url` field
- `Task` tool: `name`, `team_name`, `mode`, `max_turns`, `isolation`
- `ExitPlanMode` tool: `allowedPrompts`
- `Grep` tool: `context` (alias for `-C`)
- `Read` tool: `pages` (PDF page ranges)

**New file infrastructure:**
- `<session-id>/subagents/` — subagent session JSONL files
- `<session-id>/tool-results/` — externalized large tool outputs

### v2.1.1

Adds to UserMessage:
- `toolUseResult` — Tool result metadata
- `sourceToolAssistantUUID` — UUID of assistant message that triggered tool

## Validation

```bash
# Validate session files (auto-detects CLI version from content)
python validate.py ~/.claude/projects/<your-project>/

# Validate a single file
python validate.py ~/.claude/projects/<your-project>/session.jsonl

# Verbose mode (show data snippets)
python validate.py ~/.claude/projects/<your-project>/ -v
```

Requires: `pip install jsonschema`

## Data Sources

- v2.0.76 / v2.1.1: Original schema, tested against 52,057 messages across 480 session files (100% pass rate)
- v2.1.59: Mined from 248 JSONL files (~15,938+ lines) of real CLI 2.1.59 usage across 2 days. See [DES-5006](https://linear.app/desia/issue/DES-5006) and [DES-5062](https://linear.app/desia/issue/DES-5062) for full audit trail.
