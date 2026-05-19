# Adding a New Schema Version

How to bump this repo when Claude Code ships a CLI version whose JSONL output the current schema no longer covers. Numbered runbook with the exact commands, decision points, and the gotchas hit in the four PRs (#2, #6, #7, #8) that established this workflow.

The runbook assumes you have:

- The new CLI installed at `~/.local/share/claude/versions/<ver>`
- A real corpus of sessions in `~/.claude/projects/` covering both the old and new versions
- Python with `uv` available

If you only have a single session file, several steps still work but binary mining and drift scanning are most useful against a multi-version corpus.

---

## Phase 0 — Decide whether to bump

The repo already has five schema versions: `v2.0.76`, `v2.1.1`, `v2.1.59`, `v2.1.63`, `v2.1.72`, `v2.1.144`. Each new CLI release does **not** automatically need a new schema — `additionalProperties: true` keeps the validator green when only new fields land.

Bump when **any** of these is true:

1. The validator starts failing on current sessions (`python claude-code/validate.py ~/.claude/projects/`).
2. `drift_scan.py` (Phase 9) reports drift on more than a handful of fields.
3. A new top-level message `type` literal appears (those break `oneOf` and validation always fails).
4. A new tool name appears in the API request body.
5. A new attachment subtype appears.

Otherwise stay on the existing schema and let `additionalProperties: true` carry the new fields.

---

## Phase 1 — Find the version boundary

Don't gate the new schema at the latest CLI version; gate it at the **first version that breaks the previous schema**. The v2.1.72 → v2.1.144 boundary was 2.1.97, not 2.1.144 — CLI 2.1.74-2.1.96 still passed v2.1.72.

```bash
# 1. List recent JSONL files
find ~/.claude/projects/ -name "*.jsonl" -size +1c > /tmp/recent_sessions.txt

# 2. Bucket validation failures by CLI version
cat > /tmp/gate_check.py <<'PY'
import json, collections, sys
sys.path.insert(0, 'claude-code')
from jsonschema import Draft202012Validator
prev_schema = json.load(open('claude-code/v<PREV>/session.schema.json'))
v = Draft202012Validator(prev_schema)
by_ver_pass, by_ver_fail = collections.Counter(), collections.Counter()
for p in [l.strip() for l in open('/tmp/recent_sessions.txt')]:
    for line in open(p):
        try: data = json.loads(line)
        except: continue
        ver = data.get('version', '')
        if not ver: continue
        (by_ver_fail if list(v.iter_errors(data)) else by_ver_pass)[ver] += 1
for ver in sorted(set(list(by_ver_pass) + list(by_ver_fail)), key=lambda s: tuple(int(x) for x in s.split('.'))):
    p, f = by_ver_pass[ver], by_ver_fail[ver]
    total = p + f
    print(f'{ver:10}  pass {p:6}  fail {f:6}  {100*f/total if total else 0:6.2f}% fail')
PY
uv run --with jsonschema python /tmp/gate_check.py
```

Pick the lowest CLI version where the fail rate goes non-zero. That's your boundary.

**Decision point:** if you have no data for CLI versions between the last covered and the new break point, route those to the previous schema and note it in the README. v2.1.75-2.1.96 were unsampled and noted that way.

---

## Phase 2 — Capture canonical tool schemas

The Anthropic API tool definitions are the only canonical source for tool input shapes. Capture them via the local proxy before touching the schema.

```bash
python claude-code/capture_tools.py
# → claude-code/captured/tools_<new-ver>.json
# → claude-code/captured/system_<new-ver>.json
```

`capture_tools.py` auto-sanitizes OS username and `git user.name` before writing — but verify before committing:

```bash
grep -ic "$(whoami)\|$(git config user.name)" claude-code/captured/*.json
```

The expected output is `0` for each file. If anything other than zero, the sanitizer missed a substitution — extend `capture_tools.sanitize()`.

**Gotcha:** the captured set only includes tools whose `isEnabled()` returns true on the capture host. On macOS without remote-control / claude.ai bridge / `CLAUDE_CODE_USE_POWERSHELL_TOOL`, you'll miss `PowerShell`, `RemoteTrigger`, `SendUserFile`. Phase 8 recovers those from the binary.

---

## Phase 3 — Inventory new patterns from observation

Run the previous schema against the new corpus, bucket failures by `(top-level type, attachment.type, system.subtype)`:

```bash
cat > /tmp/scan_breaks.py <<'PY'
import json, sys, collections
sys.path.insert(0, 'claude-code')
from jsonschema import Draft202012Validator
schema = json.load(open('claude-code/v<PREV>/session.schema.json'))
v = Draft202012Validator(schema)
sigs, examples = collections.Counter(), {}
for p in [l.strip() for l in open('/tmp/recent_sessions.txt')]:
    for ln, line in enumerate(open(p), 1):
        try: data = json.loads(line)
        except: continue
        ver = data.get('version', '')
        if ver and tuple(int(x) for x in ver.split('.')) < (<BOUNDARY>): continue
        if not list(v.iter_errors(data)): continue
        top = data.get('type', '')
        sub = ''
        if top == 'attachment': sub = (data.get('attachment') or {}).get('type', '')
        elif top == 'system': sub = data.get('subtype', '')
        sigs[f'{top}::{sub}'] += 1
        examples.setdefault(f'{top}::{sub}', (p, ln, line[:1500]))
for k, c in sigs.most_common(30): print(f'{c:6}  {k}')
PY
uv run --with jsonschema python /tmp/scan_breaks.py
```

This produces the list of new patterns. For each one, look at the example payload to see what fields it carries. Save full examples to a scratch file — you'll want them while authoring the schema.

---

## Phase 4 — Author the new schema (programmatically)

Don't hand-edit a 70+KB JSON Schema. Write a Python script that loads the previous version as a base and applies additive mutations.

Skeleton:

```python
# /tmp/build_schema.py
import json
from pathlib import Path

ROOT = Path('claude-code')
SRC = ROOT / 'v<PREV>/session.schema.json'
DST = ROOT / 'v<NEW>/session.schema.json'

s = json.loads(SRC.read_text())
defs = s['$defs']

# Metadata
s['$id'] = f'https://github.com/oneryalcin/agent-schemas/claude-code/v<NEW>/session.schema.json'
s['title'] = 'Claude Code Session Schema (v<NEW>)'
s['x-cli-version'] = '<NEW>'
s['x-generated-date'] = '<YYYY-MM-DD>'
s['x-data-source'] = 'Extended from v<PREV>. ...'

# Add tool names to BuiltInToolName.enum
defs['BuiltInToolName']['enum'].extend(['NewTool1', 'NewTool2'])

# Add new $defs
defs['NewTopLevelMessage'] = {...}
defs['AttachmentNewSubtype'] = {...}
defs['NewToolInput'] = {...}

# Wire new root branches into s['oneOf']
# Wire new attachment subtypes into defs['AttachmentMessage'].properties.attachment.oneOf
# Wire new tool inputs into defs['ToolInput'].oneOf

DST.parent.mkdir(parents=True, exist_ok=True)
DST.write_text(json.dumps(s, indent=2) + '\n')
```

**Idioms to preserve:**

- `additionalProperties: true` on every message-wrapper `$def` (UserMessage, AssistantMessage, SystemMessage, AttachmentMessage, all attachment subtypes, etc.). Forward compatibility — drift will be caught by `drift_scan.py` rather than by validation failure.
- `additionalProperties: false` on tool input `$defs` (BashInput, ReadInput, etc.) and structured content blocks (TextBlock, ToolUseBlock, ImageBlock, etc.). These match the canonical API; unknowns should be errors.
- Every top-level message branch has `type` in `required` and a unique `const`. That's the discriminator.

---

## Phase 5 — Wire into validate.py

Add the new schema and gate it at the boundary you found in Phase 1.

```python
# claude-code/validate.py
SCHEMA_V<NEW> = SCRIPT_DIR / 'v<NEW>' / 'session.schema.json'

def detect_version(lines):
    for line in lines:
        if 'version' in line and line['version']:
            major, minor, patch = parse_semver(line['version'])
            if (major, minor, patch) >= (<BOUNDARY>): return 'v<NEW>', line['version']
            if (major, minor, patch) >= (<PREV-BOUNDARY>): return '<PREV>', line['version']
            # ... existing branches
            ...

def get_schema_for_version(version):
    if version == '<NEW>': return load_schema(SCHEMA_V<NEW>)
    ...
```

---

## Phase 6 — Iterate to 100%

```bash
uv run --with jsonschema python claude-code/validate.py ~/.claude/projects/
```

Each failure type is a missing `$def`, missing field, or wrong constraint. Fix them in the build_schema.py script, regenerate, re-validate. Don't stop until 100%.

### Common gotchas

| Symptom | Cause | Fix |
|---|---|---|
| `permissionMode: 'auto'` is not in enum | Enum forgot to include `auto` (added 2.1.97+) | Extend the enum |
| `'mcp__claude-in-chrome'` doesn't match `MCPToolName` pattern | Model hallucinates MCP names with only `mcp__<server>` (no `__<tool>` suffix) | Loosen pattern to make the `__<tool>` segment optional |
| `tool_reference` matches multiple `oneOf` branches | `ToolResultContentItem` uses `oneOf` and an open-object fallback collides with structured branches | Switch to `anyOf` |
| Many lines fail with confusing `user::message.role` errors | Validator picks the deepest error from the wrong `oneOf` branch — real cause is elsewhere | Run the validator against a single branch (`$defs/UserMessage`) directly to surface the real error |
| Synthetic assistant messages fail | `error: 'invalid_request'` is a string in some cases | Make `error` accept `string | object` |

---

## Phase 7 — Audit tool inputs against canonical capture

`additionalProperties: false` on tool inputs catches schema drift at the leaf level — but only if the leaf `$defs` actually match the captured tool schemas. The Anthropic API tool schemas changed under v2.1.72 → v2.1.144 (SendMessage rewrite, CronCreate.durable, EnterWorktree.path, Grep.-o, Agent.resume removal).

```python
# /tmp/drift_check.py
import json
captured = {t['name']: t['input_schema'] for t in json.load(open('claude-code/captured/tools_<NEW>.json'))}
schema = json.load(open('claude-code/v<NEW>/session.schema.json'))
defs = schema['$defs']
NAME_TO_DEF = {'Bash': 'BashInput', 'Read': 'ReadInput', ...}  # extend as needed
for name, cap in captured.items():
    if name.startswith('mcp__'): continue
    d = defs.get(NAME_TO_DEF.get(name, ''))
    if not d: continue
    cap_props = set((cap.get('properties') or {}).keys())
    own_props = set((d.get('properties') or {}).keys())
    if cap_props != own_props:
        print(f'DRIFT {name}: +{cap_props - own_props}  -{own_props - cap_props}')
```

Loop until `All tool input $defs in sync`. **This is the failure mode the repo has hit before — commit `914e439 fix(v2.1.72): align tool schemas` landed *after* v2.1.72 shipped because this step got skipped.**

---

## Phase 8 — Mine the binary for canonical subtypes and conditional tools

Observational coverage is incomplete by definition — the corpus only contains subtypes/tools that the capture host triggers. The binary contains the full canonical set.

```bash
# Canonical attachment subtypes from A9() wrapper call sites + attachment.type comparisons
python claude-code/mine_binary.py
# → captured/binary_attachments_<NEW>.json — diff against schema, add missing subtypes

# Canonical tool input schemas from P9() registration sites + Zod
python claude-code/mine_tools.py
# → captured/binary_tools_<NEW>.json — adds PowerShell/SendUserFile/RemoteTrigger or similar
```

Both scripts print a `[BINARY-ONLY]` or `MISSING FROM SCHEMA` list — those go into the schema as `additionalProperties: true` subtypes / tool input `$defs`. Document each as binary-canonical even when no JSONL line in the corpus exercises it.

**Gotcha:** `mine_tools.py` recovers ~30 of ~39 tools in 2.1.144 — the rest use a tool-registration shape without a `get inputSchema()` accessor and need pattern handling. Treat 100% coverage as aspirational.

---

## Phase 9 — Drift-scan the schema against the corpus

`drift_scan.py` finds fields the schema doesn't declare but the corpus contains. `additionalProperties: true` allows them but codegen consumers drop them silently.

```bash
python claude-code/drift_scan.py ~/.claude/projects/
```

Exit code is nonzero on any drift. For each `(type, sub-discriminator)` bucket with `[+]` undeclared keys, add the field to the relevant `$def`. Re-run until `NO DRIFT`.

First-run findings in #8 surfaced 10 fields the observational pass had missed: `entrypoint` on User/Assistant/SystemMessage, `sessionKind` on Attachment/SystemMessage, `stop_details`/`diagnostics`/`context_management`/`container` on `assistant.message`, `displayPath` on AttachmentFile/AttachmentNestedMemory, `leafUuid` on LastPromptMessage. The drift scan is non-optional — it's the only step that catches these gaps.

---

## Phase 10 — Codegen smoke test

Codegen consumers are the actual end-users of this repo. Verify what they'll get:

```bash
rm -rf generated
make python typescript
uv run --with pydantic python -c "import sys; sys.path.insert(0,'generated'); import claude_code_types; print('OK', len(dir(claude_code_types)), 'symbols')"
```

`make python` should report `Generated generated/claude_code_types.py` and the Pydantic types should import without errors. `make typescript` should regenerate the `.d.ts` without errors.

The symbol count should grow vs the previous version. If it shrinks, something got dropped — investigate.

**Don't forget:** update `Makefile` to point `SCHEMA := claude-code/v<NEW>/session.schema.json` so codegen consumers default to the latest.

---

## Phase 11 — Document, commit, PR

Document in this order:

1. `claude-code/README.md` — version mapping table, new message types section, validation results row, "How X Works" updates if you added new mining tooling.
2. Root `README.md` — bump the version row in the "Supported Agents" table, add a row in "Validation Results".
3. `CLAUDE.md` — version mapping bullets, "Key Commands" if you added a new script.

Stage selectively (per CLAUDE.md: no `git add -A`):

```bash
git checkout -b feat/v<NEW>-schema
git add CLAUDE.md README.md \
  claude-code/README.md \
  claude-code/validate.py \
  claude-code/v<NEW>/session.schema.json \
  claude-code/captured/tools_<NEW>.json \
  claude-code/captured/system_<NEW>.json \
  claude-code/captured/binary_attachments_<NEW>.json \
  claude-code/captured/binary_tools_<NEW>.json
git commit -m "feat(v<NEW>): new schema version for CLI <BOUNDARY>+"
git push -u origin feat/v<NEW>-schema
gh pr create --repo oneryalcin/agent-schemas --base main \
  --head feat/v<NEW>-schema \
  --title "feat(v<NEW>): new schema version for CLI <BOUNDARY>+"
```

PR body must include: validation pass count, drift-scan pass, codegen smoke results, list of new subtypes / tools / fields.

---

## Cross-reference: CHANGELOG hints

If you want a head start on what changed between CLI versions, fetch the upstream changelog:

```bash
uv run --with trafilatura trafilatura --markdown \
  -u "https://raw.githubusercontent.com/anthropics/claude-code/main/CHANGELOG.md" \
  > /tmp/changelog.md
```

Filter to the version range between your last bump and the new one. Look for entries that touch persistence: new message types, hooks, attachments, agent view, plan mode, scheduled tasks. The changelog won't list internal types but flags areas where new on-disk records are likely.

---

## Known limitations

- **Version-detection misroutes** when a session file's first line lacks a `version` field and falls through to the 2.0.76 default. `validate.py` and `drift_scan.py` mitigate this by scanning all lines for a version, but a file that has *no* version field anywhere routes to 2.0.76 even if its content is clearly 2.1.x.
- **Tool input drift is invisible to validation** because `ToolUseBlock.input` is typed `object` without `$ref`-ing into the `ToolInput` union. Phase 7's `drift_check.py` is the only line of defence; codegen consumers depend on it.
- **`mine_tools.py` recovers ~80% of tools**. The remaining ones use a registration shape without `get inputSchema()`. When this matters, hand-author the `$def` from the binary by inspecting the relevant `P9({name:..., inputSchema: ...})` call site directly.
- **Captured `system_*.json` files contain Anthropic's full internal system prompt**. `capture_tools.py` sanitizes OS username and git user.name automatically; review before committing if the runtime injected unexpected context (e.g. memory dir paths, recent commits).
