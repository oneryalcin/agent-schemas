# Claude Code

Session schemas for [Claude Code](https://github.com/anthropics/claude-code) CLI.

## Session Location

```
~/.claude/projects/<project-path>/*.jsonl
~/.claude/history.jsonl
```

The `<project-path>` is the absolute path with `/` replaced by `-`:
- `/Users/alice/myapp` → `-Users-alice-myapp`

## Files

| File | Description |
|------|-------------|
| `v2.0.76/session.schema.json` | Session schema for CLI v2.0.76 |
| `v2.1.1/session.schema.json` | Session schema for CLI v2.1.1 |
| `history.schema.json` | Schema for `~/.claude/history.jsonl` |
| `validate.py` | Validation script |

## Message Types

| Type | Description |
|------|-------------|
| `user` | User input |
| `assistant` | Claude's response |
| `system` | System events (commands, errors, hooks) |
| `summary` | Conversation summary |
| `file-history-snapshot` | File backup tracking |
| `queue-operation` | Message queue operations |

## Version Differences

v2.1.1 adds to UserMessage:
- `toolUseResult` - Tool result metadata
- `sourceToolAssistantUUID` - UUID of assistant message that triggered tool

## Validation

```bash
python validate.py ~/.claude/projects/<your-project>/
```

Tested against 52,057 messages across 480 session files with 100% pass rate.
