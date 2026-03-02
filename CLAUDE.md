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
```

## Schema Version Mapping

- `v2.0.76/` → CLI ≤ 2.0.x
- `v2.1.1/` → CLI 2.1.0–2.1.1 (adds `toolUseResult`, `sourceToolAssistantUUID`)
- `v2.1.59/` → CLI 2.1.2+ (golden schema: `progress` messages, 12 new tools, `pr-link`, subagent support)

Version auto-detection in `validate.py` uses the `version` field in session lines, falls back to presence of `progress` messages.

## Architecture

Pure data repo — `jsonschema` for validation, `datamodel-code-generator`/`quicktype` for codegen. Each schema is a self-contained JSON Schema Draft 2020-12 file with `$defs` for all message types, tool inputs, and content blocks.

`validate.py` is the single entry point: reads JSONL → detects version → picks schema → validates each line via `Draft202012Validator`.

## Schema Conventions

- `additionalProperties: true` everywhere for forward compatibility
- Schemas describe observed data, not official spec
- Each schema includes `$id`, `title`, `description`, `x-generated-date`
- Version by CLI version, not schema revision
