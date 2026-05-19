#!/usr/bin/env python3
"""Mine tool input schemas from the Claude Code CLI binary.

Companion to mine_binary.py. Where mine_binary.py walks attachment-subtype
construction, this one walks tool registrations.

Why this matters: `capture_tools.py` only captures tools whose `isEnabled()`
returns true under the capture host's environment. On macOS without remote
control or claude.ai bridge, the PowerShell / SendUserFile / RemoteTrigger
tools are skipped — they ship in the binary but never make it into the API
request body.

This script extracts those tools' input schemas directly from the bundled
Zod definitions in the binary, so the schema can document them without
needing the right environment to trigger a capture.

Approach:
  1. `strings <binary>` to recover printable JS source (minified but with
     string literals intact).
  2. Find every `<var>="<ToolName>"` constant assignment — gives us the
     name → minified-var map.
  3. Find every `P9({name:<var>, ...})` factory call — that's the tool
     registration.
  4. For each registration, locate the `get inputSchema(){return <fn>()}`
     accessor and resolve its Zod schema body.
  5. Translate the Zod chain to JSON Schema property shapes (key names,
     required-ness, primitive types).

The script is intentionally fail-soft: when a Zod expression is too tangled
to translate cleanly, it falls back to noting "see binary" rather than
emitting wrong types.

Usage:
    python claude-code/mine_tools.py
    python claude-code/mine_tools.py --binary ~/.local/share/claude/versions/2.1.145
"""

import argparse
import json
import re
import subprocess
from pathlib import Path

# Known canonical tool name list (used to anchor the mining — minified bundles
# don't have an explicit "all tools" list we can grep).
KNOWN_TOOL_NAMES = [
    "Agent", "AskUserQuestion", "Bash", "CronCreate", "CronDelete", "CronList",
    "Edit", "EnterPlanMode", "EnterWorktree", "ExitPlanMode", "ExitWorktree",
    "Glob", "Grep", "ListMcpResourcesTool", "Monitor", "NotebookEdit",
    "PowerShell", "PushNotification", "Read", "ReadMcpResourceTool",
    "RemoteTrigger", "ScheduleWakeup", "SendMessage", "SendUserFile",
    "ShareOnboardingGuide", "Skill", "TaskCreate", "TaskGet", "TaskList",
    "TaskOutput", "TaskStop", "TaskUpdate", "TeamCreate", "TeamDelete",
    "ToolSearch", "WaitForMcpServers", "WebFetch", "WebSearch", "Write",
]


def extract_strings(binary_path: Path) -> str:
    out = subprocess.run(
        ["strings", "-n", "4", str(binary_path)],
        capture_output=True, text=True, check=True,
    ).stdout
    return out.replace("\n", " ")


def find_name_vars(blob: str) -> dict[str, str]:
    """For each known tool name, find which minified variable holds the literal.

    Returns {tool_name: var_name}.
    """
    out = {}
    for name in KNOWN_TOOL_NAMES:
        for m in re.finditer(rf'([A-Za-z_0-9$]+)="{re.escape(name)}"', blob):
            var = m.group(1)
            # Filter out the trivial reverse where var IS the name
            if var == name:
                continue
            out[name] = var
            break
    return out


def find_tool_registration(blob: str, var: str) -> str | None:
    """Locate `P9({name:<var>, ... })` or `P9({...name:<var>...})` and return
    the chunk of source that contains the tool's metadata (description,
    inputSchema accessor, etc.).
    """
    for m in re.finditer(rf'P9\(\{{[^{{}}]{{0,500}}name:{re.escape(var)}\b', blob):
        # Grab ~5KB of context after the match — enough to cover description +
        # inputSchema accessor + isEnabled + a few more methods.
        return blob[m.start():m.start() + 5000]
    return None


def find_input_schema_fn(reg_chunk: str) -> str | None:
    """Inside a tool registration chunk, find `get inputSchema(){return <fn>()`."""
    m = re.search(r'get inputSchema\(\)\s*\{\s*return\s+([A-Za-z_0-9$]+)\s*\(', reg_chunk)
    return m.group(1) if m else None


def find_zod_schema_body(blob: str, schema_fn: str) -> tuple[str, str] | None:
    """Locate `<schema_fn>=EH(()=>y.strictObject({...}))` or `=EH(()=>y.object({...}))`
    in the binary and return ("strict"|"loose", body).
    """
    # Direct y.strictObject / y.object
    m = re.search(rf'{re.escape(schema_fn)}=EH\(\(\)=>y\.(strictObject|object)\(\{{', blob)
    if m:
        is_strict = m.group(1) == "strictObject"
        return _walk_object_body(blob, m.end(), strict=is_strict)

    # Delegate: schema_fn=EH(()=><delegate>())
    m = re.search(rf'{re.escape(schema_fn)}=EH\(\(\)=>([A-Za-z_0-9$]+)\(\)', blob)
    if m:
        return find_zod_schema_body(blob, m.group(1))

    # Ternary delegate: schema_fn=EH(()=><cond>?<a>().omit({...}):<b>())
    # In practice the two branches reference the same base schema with one omitting fields;
    # prefer the fuller branch (the one without .omit), then strip the omitted keys.
    m = re.search(
        rf'{re.escape(schema_fn)}=EH\(\(\)=>[A-Za-z_0-9$]+\?([A-Za-z_0-9$]+)\(\)\.omit\(\{{([^}}]+)\}}\):([A-Za-z_0-9$]+)\(\)',
        blob,
    )
    if m:
        # Fuller branch = the else branch (no .omit), which is m.group(3)
        result = find_zod_schema_body(blob, m.group(3))
        return result

    return None


def _walk_object_body(blob: str, start: int, *, strict: bool) -> tuple[str, str]:
    depth = 1
    i = start
    while i < len(blob) and depth > 0:
        if blob[i] == "{":
            depth += 1
        elif blob[i] == "}":
            depth -= 1
        i += 1
    body = blob[start:i - 1]
    return ("strict" if strict else "loose"), body


# Translate Zod-chain fragments to JSON Schema property entries.
# We only handle the shapes Claude Code's tool input schemas actually use.
PRIMITIVE_RE = re.compile(r'y\.(string|number|integer|boolean|unknown|record\([^)]*\))')
LITERAL_RE = re.compile(r'y\.literal\("([^"]+)"\)')
ENUM_RE = re.compile(r'y\.enum\(\[((?:"[^"]*",?)+)\]\)')
ARRAY_RE = re.compile(r'y\.array\(([^)]+)\)')


def parse_zod_value(expr: str) -> dict:
    """Best-effort Zod → JSON Schema for a single property value."""
    out = {}
    # required-ness — `.optional()` makes the field optional
    out["__optional"] = ".optional()" in expr

    # description
    desc = re.search(r'\.describe\("((?:[^"\\]|\\.)*)"\)', expr)
    if desc:
        out["description"] = desc.group(1).encode().decode("unicode_escape")

    # primitive types
    if "y.string()" in expr:
        out["type"] = "string"
    elif "y.number()" in expr:
        out["type"] = "number"
    elif "y.integer()" in expr or "y.int()" in expr:
        out["type"] = "integer"
    elif "y.boolean()" in expr:
        out["type"] = "boolean"
    elif "y.unknown()" in expr:
        pass  # no type constraint

    # enum
    m = ENUM_RE.search(expr)
    if m:
        values = re.findall(r'"([^"]*)"', m.group(1))
        out["type"] = "string"
        out["enum"] = values

    # literal
    m = LITERAL_RE.search(expr)
    if m:
        out["const"] = m.group(1)

    # array — extract inner type via balanced-paren scan
    m = re.search(r'y\.array\(', expr)
    if m:
        out["type"] = "array"
        start = m.end()
        depth = 1
        i = start
        while i < len(expr) and depth > 0:
            if expr[i] == "(":
                depth += 1
            elif expr[i] == ")":
                depth -= 1
            i += 1
        inner_expr = expr[start:i - 1]
        inner = parse_zod_value(inner_expr)
        if "type" in inner:
            out["items"] = {"type": inner["type"]}
        if "enum" in inner:
            out.setdefault("items", {})["enum"] = inner["enum"]

    # record
    if "y.record(" in expr:
        out["type"] = "object"
        out["additionalProperties"] = True

    # number constraints
    m = re.search(r'\.min\((\d+)\)', expr)
    if m:
        out["minimum" if out.get("type") == "number" else "minItems"] = int(m.group(1))
    m = re.search(r'\.max\((\d+)\)', expr)
    if m:
        out["maximum" if out.get("type") == "number" else "maxItems"] = int(m.group(1))

    # regex
    m = re.search(r'\.regex\(/([^/]+)/\)', expr)
    if m:
        out["pattern"] = m.group(1)

    # default
    m = re.search(r'\.default\(([^)]+)\)', expr)
    if m:
        default_val = m.group(1)
        if default_val == "!0":
            out["default"] = True
        elif default_val == "!1":
            out["default"] = False
        elif default_val.isdigit():
            out["default"] = int(default_val)
        else:
            try:
                out["default"] = json.loads(default_val)
            except Exception:
                pass

    return out


def split_zod_object_body(body: str) -> list[tuple[str, str]]:
    """Split a Zod object body like `key1:y.string()...,key2:y.number()...`
    into [(key, value_expr), ...]. Respects balanced parens.
    """
    out: list[tuple[str, str]] = []
    i = 0
    n = len(body)
    while i < n:
        # Skip leading whitespace/commas
        while i < n and body[i] in ", \t":
            i += 1
        if i >= n:
            break
        # Read key — bareword
        km = re.match(r'([A-Za-z_][A-Za-z0-9_]*)', body[i:])
        if not km:
            break
        key = km.group(1)
        i += len(key)
        # Expect ':'
        while i < n and body[i] in " \t":
            i += 1
        if i >= n or body[i] != ":":
            break
        i += 1
        # Read value expression until next top-level comma
        depth_paren = 0
        depth_brace = 0
        depth_brack = 0
        in_str = None
        start_v = i
        while i < n:
            ch = body[i]
            if in_str:
                if ch == "\\":
                    i += 2
                    continue
                if ch == in_str:
                    in_str = None
            elif ch in '"\'':
                in_str = ch
            elif ch == "(":
                depth_paren += 1
            elif ch == ")":
                depth_paren -= 1
            elif ch == "{":
                depth_brace += 1
            elif ch == "}":
                depth_brace -= 1
            elif ch == "[":
                depth_brack += 1
            elif ch == "]":
                depth_brack -= 1
            elif ch == "," and depth_paren == 0 and depth_brace == 0 and depth_brack == 0:
                break
            i += 1
        value_expr = body[start_v:i].strip()
        out.append((key, value_expr))
    return out


def zod_to_json_schema(strict_or_loose: str, body: str, description: str = "") -> dict:
    """Convert a top-level Zod object body to a JSON Schema object."""
    pairs = split_zod_object_body(body)
    properties = {}
    required = []
    for key, expr in pairs:
        prop = parse_zod_value(expr)
        opt = prop.pop("__optional", False)
        properties[key] = {k: v for k, v in prop.items() if not k.startswith("__")}
        if not opt:
            required.append(key)
    out = {"type": "object", "properties": properties}
    if required:
        out["required"] = required
    out["additionalProperties"] = False if strict_or_loose == "strict" else True
    if description:
        out["description"] = description
    return out


def main():
    ap = argparse.ArgumentParser()
    default_binary = Path.home() / ".local/share/claude/versions/2.1.144"
    ap.add_argument("--binary", type=Path, default=default_binary)
    ap.add_argument(
        "--captured",
        type=Path,
        default=Path(__file__).parent / "captured" / "tools_2.1.144.json",
        help="Captured tools file to diff against (find tools the binary has that the live capture missed).",
    )
    args = ap.parse_args()

    if not args.binary.exists():
        ap.error(f"binary not found: {args.binary}")

    print(f"Mining tools from {args.binary} ({args.binary.stat().st_size / 1e6:.0f}MB)...")
    blob = extract_strings(args.binary)
    print(f"  extracted {len(blob) / 1e6:.0f}MB of strings\n")

    captured_names = set()
    if args.captured.exists():
        captured = json.loads(args.captured.read_text())
        captured_names = {t["name"] for t in captured}
        print(f"Tools in capture ({args.captured.name}): {len(captured_names)} (excluding MCP)")
        print()

    name_to_var = find_name_vars(blob)
    print(f"Resolved {len(name_to_var)} tool name → minified-var mappings")

    binary_only = []
    binary_schemas: dict[str, dict] = {}

    for name in KNOWN_TOOL_NAMES:
        var = name_to_var.get(name)
        if not var:
            continue
        reg = find_tool_registration(blob, var)
        if not reg:
            continue
        schema_fn = find_input_schema_fn(reg)
        if not schema_fn:
            continue
        zod = find_zod_schema_body(blob, schema_fn)
        if zod is None:
            continue
        strictness, body = zod
        schema = zod_to_json_schema(strictness, body)
        binary_schemas[name] = schema
        if name not in captured_names:
            binary_only.append(name)

    print(f"\nRecovered input schemas for {len(binary_schemas)} tools.")
    print(f"Of those, {len(binary_only)} are NOT in the captured tools (conditional / platform-gated):")
    for name in sorted(binary_only):
        schema = binary_schemas[name]
        keys = list((schema.get("properties") or {}).keys())
        req = schema.get("required", [])
        print(f"  [BINARY-ONLY] {name:25} keys={keys} required={req}")

    out_path = Path(__file__).parent / "captured" / f"binary_tools_{args.binary.name}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps({
        "binary": str(args.binary),
        "binary_only_tools": sorted(binary_only),
        "schemas": binary_schemas,
    }, indent=2) + "\n")
    print(f"\nArtifact saved: {out_path}")


if __name__ == "__main__":
    main()
