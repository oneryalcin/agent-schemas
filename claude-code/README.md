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
| `v2.1.59/session.schema.json` | Session schema for CLI 2.1.2–2.1.62 |
| `v2.1.63/session.schema.json` | Session schema for CLI 2.1.63 |
| `v2.1.72/session.schema.json` | Session schema for CLI 2.1.64–2.1.96 |
| `v2.1.144/session.schema.json` | Session schema for CLI 2.1.97+ |
| `history.schema.json` | Schema for `~/.claude/history.jsonl` |
| `validate.py` | Validation script (auto-detects version) |
| `capture_tools.py` | Capture tool schemas + system prompt from API |
| `mine_binary.py` | Mine attachment subtypes + property shapes from the CLI binary |
| `mine_tools.py` | Mine tool input schemas from the CLI binary (catches conditional tools that don't appear in the default capture) |
| `drift_scan.py` | Detect undeclared keys in a JSONL corpus vs the schema's declared properties (use to discover new fields before each schema bump) |

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
| `agent-name` | 2.1.64+ | Agent/session display name |
| `custom-title` | 2.1.64+ | Session title updates |
| `last-prompt` | 2.1.64+ | Last user prompt for resumption |
| `attachment` | 2.1.97+ | Out-of-band context records (25 subtypes: hook results, file/dir mounts, queued commands, plan-mode/auto-mode toggles, deferred-tools deltas, skill listings, goal status, budget, etc.) |
| `permission-mode` | 2.1.97+ | Permission-mode change record (`auto` mode added here) |
| `ai-title` | 2.1.97+ | AI-generated session title |
| `agent-setting` | 2.1.97+ | Active agent setting for the session |
| `bridge-session` | 2.1.97+ | Linkage to a remote-control bridge session |
| `worktree-state` | 2.1.97+ | Worktree session metadata (`--worktree`/EnterWorktree) |

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
- `UserMessage`: `permissionMode` (enum: default, acceptEdits, bypassPermissions, dontAsk, plan), `isVisibleInTranscriptOnly`, `imagePasteIds`
- `UserMessage`/`AssistantMessage`/`SystemMessage`: `teamName`
- `ToolUseBlock`: `caller` (e.g., `{"type": "direct"}`)
- `UsageInfo`: `inference_geo`, `iterations`, `speed` (all nullable)
- `SystemMessage`: `bridge_status` subtype with `url` field; `error` as structured object on `api_error`; retry metadata (`cause` as object, `retryInMs` as number, `retryAttempt`, `maxRetries`)
- `ProgressMessage`: `agentId` (in subagent session files)
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
- v2.1.59: Golden schema — validated against 51,025 JSONL lines (including subagent files) with 100% pass rate and zero undocumented fields. Mined from 248+ files across 2 days of real CLI 2.1.59 usage.
- v2.1.63: Agent tool (renamed from Task), microcompact_boundary system subtype.
- v2.1.72: Tool schemas validated against canonical API definitions captured via `capture_tools.py`. Validated 100% on 54 files / 19,657 lines (CLI 2.1.68–2.1.72).
- v2.1.144: Tool schemas re-aligned against canonical capture (drift in `Agent`, `CronCreate`, `CronList`, `EnterWorktree`, `Grep`, `SendMessage` since v2.1.72). Validated 100% on 660 files / 102,488 lines spanning CLI 2.1.97–2.1.144. The v2.1.72→v2.1.144 boundary is set at 2.1.97 because that is the earliest CLI version with observed schema-breaking session lines in our corpus; CLI 2.1.75–2.1.96 were not sampled and are routed to v2.1.72, which they should continue to satisfy.
- v2.1.144 (binary-mined pass): 13 additional attachment subtypes recovered from the CLI 2.1.144 binary via `mine_binary.py` — `agent_mention`, `hook_additional_context`, `hook_deferred_tool`, `hook_error_during_execution`, `hook_permission_decision`, `hook_stopped_continuation`, `hook_system_message`, `plan_file_reference`, `plan_mode` (distinct from `plan_mode_exit`), `plan_mode_reentry`, `relevant_memories`, `structured_output`, `task_status`. These do not appear in the 660-file observational corpus but are constructed via the `A9()` attachment wrapper in the bundled TypeScript source, so they are canonical even when unobserved.
- v2.1.144 (tool-mining pass): 3 conditionally-enabled tools recovered via `mine_tools.py` — `PowerShell` (Windows-only / `CLAUDE_CODE_USE_POWERSHELL_TOOL=1`), `RemoteTrigger` (claude.ai bridge / `tengu_surreal_dali` flag), `SendUserFile` (remote-environment sessions). These never appear in a macOS no-remote default capture; their canonical Zod schemas were extracted from the binary's tool-registration call sites.

### v2.1.72 (covers 2.1.64+)

**New message types:**
- `agent-name` — session/agent display name assignment
- `custom-title` — session title updates
- `last-prompt` — last user prompt for session resumption

**New built-in tools (4):**
`CronCreate`, `CronDelete`, `CronList`, `ExitWorktree`

**New fields on existing types:**
- `SystemMessage`: `compactMetadata` (`{trigger, preTokens}`), `logicalParentUuid`
- `UserMessage`: `planContent` (plan mode markdown)
- `Agent` tool: `auto` permission mode; `subagent_type` now optional; `max_turns` removed
- `ExitPlanMode` tool: restructured with `allowedPrompts` array
- `ExitWorktree` tool: `action` (keep/remove), `discard_changes`

### v2.1.144 (covers 2.1.97+)

**New message types:**
- `attachment` — wrapper for 38 out-of-band context record subtypes (see below)
- `permission-mode`, `ai-title`, `agent-setting`, `bridge-session`, `worktree-state`

**Attachment subtypes (observational, 25):** `output_style`, `hook_success`, `hook_non_blocking_error`, `hook_blocking_error`, `hook_cancelled`, `task_reminder`, `todo_reminder`, `queued_command`, `deferred_tools_delta`, `mcp_instructions_delta`, `skill_listing`, `invoked_skills`, `edited_text_file`, `auto_mode`, `auto_mode_exit`, `plan_mode_exit`, `nested_memory`, `command_permissions`, `file`, `compact_file_reference`, `directory`, `date_change`, `goal_status`, `budget_usd`, `max_turns_reached`.

**Attachment subtypes (binary-canonical, 13):** `agent_mention`, `hook_additional_context`, `hook_deferred_tool`, `hook_error_during_execution`, `hook_permission_decision`, `hook_stopped_continuation`, `hook_system_message`, `plan_file_reference`, `plan_mode`, `plan_mode_reentry`, `relevant_memories`, `structured_output`, `task_status`.

**New built-in tools (9):**
`Monitor`, `PushNotification`, `ScheduleWakeup`, `ShareOnboardingGuide`, `WaitForMcpServers`, `RemoteTrigger`, `PowerShell`, `SendUserFile` — the latter three were added via `mine_tools.py` after PR #2/#6 because they're conditionally enabled and absent from default captures.

**New content blocks:**
- `server_tool_use` — server-side tool invocation (advisor, etc.)
- `advisor_tool_result` — advisor result, paired with `server_tool_use`

**New fields on existing types:**
- `UserMessage`: `auto` permission mode, `origin` (`{kind: "task-notification"|"channel"}`), `promptId`, `sessionKind`, `mcpMeta`, `sourceToolUseID`, `sidechainParentUuid`
- `AssistantMessage`: `advisorModel`, `attributionAgent/Plugin/Skill`, `error` (string|object), `errorDetails` (string|object), `apiErrorStatus`, `origin`, `agentId`, `slug`, `sessionKind`, `sidechainParentUuid`
- `SystemMessage.subtype`: adds `away_summary`, `scheduled_task_fire`, `informational`; `level` adds `"warning"`
- `UsageInfo.iterations[]`: typed entries (`type: "message" | "advisor_message"`); advisor entries include `model`
- `MCPToolName` pattern: trailing `__<tool>` segment is now optional (model occasionally hallucinates `mcp__<server>` alone)
- `ToolResultContentItem`: switched `oneOf` → `anyOf` to accept MCP resource descriptors alongside structured shapes

### v2.1.63

**Changes from v2.1.59:**
- `Agent` tool added (renamed from `Task`)
- `microcompact_boundary` system subtype

## How Binary Mining Works

Claude Code 2.1.140+ ships as a Bun-compiled native binary (`~/.local/share/claude/versions/<ver>`). The JS source survives as printable strings — `strings <binary>` extracts ~24MB of bundled JavaScript with minified variable names but intact string literals.

Every attachment line in a session JSONL is built via a single wrapper function:

```js
function A9(payload) {
    return {attachment: payload, type: "attachment", uuid: ..., timestamp: ...};
}
```

`mine_binary.py` triangulates the canonical attachment-subtype enum from three sources:

1. **Writer sites:** `A9({type:"X", ...})` direct call sites — proves X is constructed.
2. **Reader sites:** `attachment.type === "X"` comparisons — proves X is dispatched on.
3. **Schema:** subtypes already documented in `v2.1.144/session.schema.json` from observation.

The union is the canonical set. For each subtype, the script scans every `{type:"X", ...}` literal in the binary and unions the property keys it finds — recovering writer-side fields even when minification has mangled the surrounding code.

Run:

```bash
python claude-code/mine_binary.py
# Optional: target a specific binary
python claude-code/mine_binary.py --binary ~/.local/share/claude/versions/2.1.145
```

Output is saved to `captured/binary_attachments_<ver>.json` for downstream tools.

Limitations: minification preserves string literals and bareword property keys but mangles function/variable identifiers, so property shapes are key-only (no types). The reader/writer triangulation is best-effort — a subtype built via a helper function whose `A9()` call uses a variable instead of an object literal won't be detected as a writer site (8 of the 25 observation-derived subtypes fall into this bucket; they're still in the schema because the observation corpus saw them).

## How Drift Detection Works

The session schemas use `additionalProperties: true` on every message-wrapper `$def` for forward compatibility — a new CLI ships a new field and the validator stays green. The downside: codegen consumers drop the new field silently and never see it.

`drift_scan.py` walks a JSONL corpus and reports every observed key the schema doesn't declare in `properties`:

```bash
python claude-code/drift_scan.py ~/.claude/projects/
python claude-code/drift_scan.py session.jsonl
python claude-code/drift_scan.py ~/.claude/projects/ --version 2.1.144   # force version
python claude-code/drift_scan.py ~/.claude/projects/ --top 5             # only top 5 per bucket
```

Output groups findings by (schema version, message bucket), where a bucket is something like `user`, `assistant.message`, `attachment.hook_success`, `system[turn_duration]` — discriminated by both the top-level `type` and (when relevant) `attachment.type` or `system.subtype`. For each undeclared key it prints the count and an example `file:line`.

Exit code is nonzero if any drift is found — usable as a CI tripwire against a current capture corpus.

The script auto-detects the schema version per file using the same logic as `validate.py`. Lines below the minimum supported version are silently skipped.

The first drift run against my corpus (103k lines across CLI 2.1.97-2.1.144) surfaced ~10 missing fields the observational PR #2 walk had missed: `entrypoint` on User/Assistant/SystemMessage; `sessionKind` on Attachment/SystemMessage; `messageCount` on `system[turn_duration]`; `stop_details`, `diagnostics`, `context_management`, `container` on `assistant.message`; `displayPath` on AttachmentFile/AttachmentNestedMemory; `leafUuid` on LastPromptMessage; `promptId` on the v2.1.72 UserMessage. All of these were added to the schema in the same PR that introduced `drift_scan.py`.

## How Tool Mining Works

`capture_tools.py` only captures tools whose `isEnabled()` returns true under the capture host's environment. On macOS without remote control or claude.ai bridge, the `PowerShell` / `SendUserFile` / `RemoteTrigger` tools are skipped — they ship in the binary but never make it into the API request body.

`mine_tools.py` recovers them by:

1. Running `strings` on the binary to extract the bundled JS.
2. Finding every `<var>="<ToolName>"` constant assignment to build a name → minified-var map.
3. Finding each `P9({name:<var>, ...})` tool-registration call.
4. Extracting the `get inputSchema(){return <fn>()}` accessor and walking it through delegate / ternary patterns to the underlying `y.strictObject({...})` Zod schema.
5. Translating the Zod chain to JSON Schema (primitive types, enums, arrays, min/max, defaults, regex patterns, optional-ness).

The script is fail-soft: when a Zod expression is too tangled, it skips that tool rather than emitting an incorrect schema. In CLI 2.1.144 it recovers 30 of 39 mapped tools (failures are mostly tools with no `get inputSchema()` accessor — they use a different registration shape).

Run:

```bash
python claude-code/mine_tools.py
# Outputs captured/binary_tools_<ver>.json with the schemas of every recovered tool
# and a `binary_only_tools` list of the ones missing from the live capture.
```

## How Tool Definitions Work

Tool schemas (Bash, Read, Edit, etc.) are **not** stored in session JSONL files. They are passed in the `tools` parameter of each API request to Anthropic and never persisted to disk. Use `capture_tools.py` to intercept and extract them via a local proxy.

Claude Code implements a client-side version of Anthropic's [Tool Search](https://platform.claude.com/docs/en/agents-and-tools/tool-use/tool-search-tool) pattern:

- **Always-loaded tools** (Bash, Read, Edit, Glob, Grep, Write, Agent, Skill, ToolSearch): full JSON schemas sent in every API request via `body.tools`
- **Deferred tools** (AskUserQuestion, CronCreate, etc.): listed by name in `<available-deferred-tools>`, schemas fetched on-demand via the `ToolSearch` tool which returns `tool_reference` content blocks

The API also supports server-side tool search (`tool_search_tool_regex_20251119`, `tool_search_tool_bm25_20251119`) with `defer_loading: true` on tool definitions and `server_tool_use` / `tool_search_tool_result` response blocks. Claude Code uses its own client-side implementation instead, so these server-side block types do not appear in CLI session JSONL.

Additional API-level features ([Advanced Tool Use](https://www.anthropic.com/engineering/advanced-tool-use), [Tool Search docs](https://platform.claude.com/docs/en/agents-and-tools/tool-use/tool-search-tool)) not currently observed in CLI sessions:
- **Programmatic Tool Calling** (`code_execution_20250825`): Claude orchestrates tools via Python code; adds `allowed_callers` on tool defs, `caller.type: "code_execution_20250825"` on `tool_use` blocks, `server_tool_use` and `code_execution_tool_result` content blocks
- **Tool Use Examples** (`input_examples`): Sample tool calls on tool definitions for teaching usage patterns
- Our `ToolUseCaller` schema currently only documents `"type": "direct"` — if Claude Code adopts programmatic tool calling, the caller type enum will need updating
