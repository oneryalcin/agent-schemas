# Agent Schemas

> **Note**: This is a community project, not affiliated with Anthropic.

JSON Schema definitions for AI coding agent session formats.

## Why This Repo Exists

To build apps on top of coding agents, you need to parse and load their session messages.

The [Claude Agent SDK](https://github.com/anthropics/claude-agent-sdk-python) doesn't yet provide programmatic access to session history or type definitions for the JSONL format ([#109](https://github.com/anthropics/claude-agent-sdk-python/issues/109)). This repo fills that gap with reverse-engineered JSON schemas, enabling:

- Type-safe parsing for building UIs and tools
- Session data validation
- Type generation for any language

## Supported Agents

| Agent                         | Versions        | Status   |
| ----------------------------- | --------------- | -------- |
| [Claude Code](./claude-code/) | v2.0.76, v2.1.1, v2.1.59 | Complete |

## Quick Start

### Generate Types

```bash
# TypeScript
npx json-schema-to-typescript \
  claude-code/v2.1.59/session.schema.json \
  -o claude-code.d.ts

# Python
npx quicktype \
  --src claude-code/v2.1.59/session.schema.json \
  --src-lang schema \
  --lang python \
  -o claude_code_types.py
```

### Validate Session Files

```bash
# Clone the repo
git clone https://github.com/moru-ai/agent-schemas.git
cd agent-schemas

# Setup (one-time)
python3 -m venv .venv
source .venv/bin/activate
pip install jsonschema

# Validate Claude Code sessions
python claude-code/validate.py ~/.claude/projects/<your-project>/
```

### Use in Code

```python
import json
import requests
from jsonschema import Draft202012Validator

# Fetch schema from GitHub
schema_url = "https://raw.githubusercontent.com/moru-ai/agent-schemas/main/claude-code/v2.1.59/session.schema.json"
schema = requests.get(schema_url).json()
validator = Draft202012Validator(schema)

# Validate a session file
with open("session.jsonl") as f:
    for line_num, line in enumerate(f, 1):
        data = json.loads(line)
        errors = list(validator.iter_errors(data))
        if errors:
            print(f"Line {line_num}: {errors[0].message}")
```

```typescript
// TypeScript with Ajv
import Ajv from 'ajv';

const ajv = new Ajv({ loadSchema: async uri => (await fetch(uri)).json() });
const validate = await ajv.compileAsync({
  $ref: 'https://raw.githubusercontent.com/moru-ai/agent-schemas/main/claude-code/v2.1.59/session.schema.json',
});

const isValid = validate(messageData);
```

## How We Made This

The schemas are **reverse-engineered** from actual session data, not official documentation.

### Process

1. **Data Collection**: Gathered session files from real Claude Code usage
2. **Field Discovery**: Analyzed all unique fields, types, and patterns via parallel mining agents
3. **Schema Writing**: Created JSON Schema Draft 2020-12 definitions covering all message types, tool inputs, and content blocks
4. **Iterative Validation**: Ran validation against all session data, fixing schema issues until 100% pass rate with zero undocumented fields
5. **Version Differentiation**: Identified version-specific fields (e.g., `toolUseResult` in v2.1.1, `progress` messages in v2.1.2+)

### Validation Results

| Agent       | Schema  | Files | Messages | Pass Rate |
| ----------- | ------- | ----- | -------- | --------- |
| Claude Code | v2.0.76 | 480   | 52,057   | 100%      |
| Claude Code | v2.1.59 | 248+  | 51,025   | 100%      |

### Limitations

- Schemas describe observed data, not official spec
- Undiscovered message types may exist
- Future CLI versions may introduce breaking changes
- `additionalProperties: true` allows forward compatibility

## Repository Structure

```
agent-schemas/
├── README.md                 # This file
└── claude-code/
    ├── README.md             # Claude Code specific docs
    ├── validate.py           # Validation script (auto-detects version)
    ├── history.schema.json   # ~/.claude/history.jsonl schema
    ├── v2.0.76/
    │   └── session.schema.json   # CLI ≤ 2.0.x
    ├── v2.1.1/
    │   └── session.schema.json   # CLI 2.1.0–2.1.1
    └── v2.1.59/
        └── session.schema.json   # CLI 2.1.2–2.1.59+ (golden)
```

## Contributing

We welcome contributions for schema improvements.

### Improving Existing Schemas

1. Find a message that fails validation
2. Add the missing field/type to the schema
3. Run validation to confirm fix
4. Submit PR with:
   - Schema change
   - Example of the previously-failing message (anonymized)

### Guidelines

- Use JSON Schema Draft 2020-12
- Include `$id`, `title`, `description`, `x-generated-date`
- Set `additionalProperties: true` for forward compatibility
- Version schemas by CLI version
- Validate against real data before submitting

## License

MIT

## Links

- [JSON Schema](https://json-schema.org/)
- [Claude Code](https://github.com/anthropics/claude-code)
- [json-schema-to-typescript](https://github.com/bcherny/json-schema-to-typescript)
- [quicktype](https://github.com/glideapps/quicktype)
