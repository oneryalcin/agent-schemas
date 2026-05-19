# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Repo Is

Reverse-engineered JSON Schema definitions (Draft 2020-12) for AI coding agent session formats. Currently covers Claude Code CLI session JSONL files across three schema versions. Community project, not affiliated with Anthropic.

## Key Commands

```bash
# Generate typed code (outputs to generated/)
make python        # Pydantic v2 models
make typescript    # TypeScript interfaces
make go            # Go structs (quicktype)
make rust          # Rust structs (quicktype)
make               # python + typescript

# Validate session files (requires: pip install jsonschema)
python claude-code/validate.py ~/.claude/projects/<project-path>/
python claude-code/validate.py <single-file>.jsonl
python claude-code/validate.py <directory> -v  # verbose

# Capture tool schemas + system prompt from live API
python claude-code/capture_tools.py                # uses haiku, outputs to captured/
python claude-code/capture_tools.py --model sonnet  # use sonnet

# Mine attachment subtypes + property shapes from the CLI binary
python claude-code/mine_binary.py                  # uses 2.1.144, outputs to captured/
python claude-code/mine_binary.py --binary ~/.local/share/claude/versions/2.1.145

# Mine tool input schemas from the CLI binary (catches platform-conditional tools)
python claude-code/mine_tools.py
```

## Schema Version Mapping

- `v2.0.76/` → CLI ≤ 2.0.x
- `v2.1.1/` → CLI 2.1.0–2.1.1 (adds `toolUseResult`, `sourceToolAssistantUUID`)
- `v2.1.59/` → CLI 2.1.2+ (golden schema: `progress` messages, 12 new tools, `pr-link`, subagent support)
- `v2.1.63/` → CLI 2.1.63 (Agent tool renamed from Task, microcompact_boundary)
- `v2.1.72/` → CLI 2.1.64–2.1.96 (agent-name/custom-title/last-prompt messages, compactMetadata, CronCreate/CronDelete/CronList, ExitWorktree, planContent)
- `v2.1.144/` → CLI 2.1.97+ (AttachmentMessage with 38 subtypes — 25 observation-derived + 13 binary-mined from `~/.local/share/claude/versions/2.1.144`, permission-mode/ai-title/agent-setting/bridge-session/worktree-state top-level types, advisor server_tool_use & advisor_tool_result content blocks, Monitor/PushNotification/ScheduleWakeup/ShareOnboardingGuide/WaitForMcpServers tools, `auto` permission mode, away_summary/scheduled_task_fire/informational system subtypes)

Version auto-detection in `validate.py` uses the `version` field in session lines, falls back to presence of `progress` messages.

## Architecture

Pure data repo — `jsonschema` for validation, `datamodel-code-generator`/`quicktype` for codegen. Each schema is a self-contained JSON Schema Draft 2020-12 file with `$defs` for all message types, tool inputs, and content blocks.

`validate.py` is the single entry point: reads JSONL → detects version → picks schema → validates each line via `Draft202012Validator`.

`capture_tools.py` intercepts Claude API requests via a local proxy to extract canonical tool schemas and system prompt. Tool schemas are passed in the API `tools` parameter (not in JSONL session logs).

`mine_binary.py` extracts attachment subtypes and their property keys from the Bun-compiled CLI binary by running `strings` over it and finding `A9()` wrapper call sites (writers), `attachment.type === "X"` comparisons (readers), and union'ing recovered keys from every `{type:"X", ...}` literal. Output is `captured/binary_attachments_<ver>.json`.

`mine_tools.py` extracts tool input schemas from the binary by locating `P9({name:<var>, ...})` tool-registration calls, walking their `get inputSchema()` accessors through delegate/ternary patterns to the underlying `y.strictObject({...})` Zod schema, and translating the Zod chain to JSON Schema. Catches platform-conditional tools (PowerShell, SendUserFile, RemoteTrigger) that `capture_tools.py` skips because their `isEnabled()` returns false on the capture host. Output is `captured/binary_tools_<ver>.json`.

## Schema Conventions

- `additionalProperties: true` everywhere for forward compatibility
- Tool input schemas validated against canonical API definitions (via `capture_tools.py`)
- Schemas describe observed data, not official spec
- Each schema includes `$id`, `title`, `description`, `x-generated-date`
- Version by CLI version, not schema revision
