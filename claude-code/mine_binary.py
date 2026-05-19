#!/usr/bin/env python3
"""Mine the Claude Code CLI binary for canonical attachment subtypes and message types.

The CLI ships as a Bun-compiled native binary (~/.local/share/claude/versions/<ver>).
Its JS source survives as printable strings — `strings` extracts them. The persistence
layer constructs attachment lines via a single wrapper function:

    function A9(payload) {
        return {attachment: payload, type: "attachment", uuid: ..., timestamp: ...};
    }

So every JSONL `attachment` line begins life as `A9(<subtype payload>)`. Either:
  1. Direct:   A9({type:"hook_success", ...})
  2. Indirect: A9(varBuiltElsewhere)  — trace back through the dispatch table

This script enumerates both, cross-references against v2.1.144/session.schema.json,
and reports missing subtypes + recovered property names.

Usage:
    python claude-code/mine_binary.py                          # uses current 2.1.144
    python claude-code/mine_binary.py --binary /path/to/claude
    python claude-code/mine_binary.py --schema v2.1.144/session.schema.json
"""

import argparse
import json
import re
import subprocess
from collections import defaultdict
from pathlib import Path


def extract_strings(binary_path: Path) -> str:
    """Run `strings` on the binary, joined to a single line for cross-newline regex."""
    out = subprocess.run(
        ["strings", "-n", "4", str(binary_path)],
        capture_output=True, text=True, check=True,
    ).stdout
    return out.replace("\n", " ")


# An object literal starting with type:"<name>".
# Greedy property name match through the next closing brace at balance 0.
# We don't try full JS parsing — minified code has nested braces in arrow bodies,
# template literals, etc. — but for the immediate {type:"X", ...} literal we only
# need keys before the first comma-followed-key.
OBJ_LITERAL_RE = re.compile(r'\{type:"([a-z_][a-z0-9_]*)"((?:[^{}]|\{[^{}]*\}){0,2000})\}')

# Match the attachment-generator dispatch entries: a$("<name>", <fn-ref>)
DISPATCH_RE = re.compile(r'a\$\("([a-z_][a-z0-9_]*)",')

# Match property keys in an object body — minified code uses bareword keys.
PROP_KEY_RE = re.compile(r'(?:^|[,{])\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*:')


def find_direct_a9_subtypes(blob: str) -> dict[str, list[str]]:
    """Find every A9({type:"X",...}) literal and recover its top-level property keys."""
    subtypes: dict[str, list[str]] = {}
    for m in re.finditer(r'A9\(\{type:"([a-z_][a-z0-9_]*)"((?:[^{}]|\{[^{}]*\}){0,2000})', blob):
        name = m.group(1)
        body = m.group(2)
        keys = ["type"]
        for k in PROP_KEY_RE.findall(body):
            if k not in keys:
                keys.append(k)
        subtypes.setdefault(name, keys)
    return subtypes


def find_all_subtype_returns(blob: str) -> dict[str, list[str]]:
    """Find arrow- and return-statement object literals: =>{type:"X",...}, return{type:"X",...}.

    Returns the cleanest reading of property keys per subtype. This is broader than
    direct-A9 callsites — it captures payloads built in helper functions whose return
    value is then wrapped by A9.
    """
    subtypes: dict[str, list[str]] = {}
    patterns = [
        r'(?:return|=>\(|=>\s*)\{type:"([a-z_][a-z0-9_]*)"((?:[^{}]|\{[^{}]*\}){0,2000})\}',
    ]
    for pat in patterns:
        for m in re.finditer(pat, blob):
            name = m.group(1)
            body = m.group(2)
            keys = ["type"]
            for k in PROP_KEY_RE.findall(body):
                if k not in keys:
                    keys.append(k)
            # Keep the first occurrence's key list as canonical
            if name not in subtypes:
                subtypes[name] = keys
    return subtypes


def find_dispatch_labels(blob: str) -> list[str]:
    """All a$("<name>", ...) dispatch labels (generator-function names, not necessarily subtypes)."""
    return sorted(set(DISPATCH_RE.findall(blob)))


# Match `attachment.type === "X"` and `attachment.type=="X"` — reader-side switch sites.
# Anywhere the CLI compares against a subtype literal, that subtype exists in the schema.
READER_RE = re.compile(r'attachment\.type\s*===?\s*"([a-z_][a-z0-9_]*)"')


def find_reader_subtypes(blob: str) -> set[str]:
    """Return every subtype that the CLI compares attachment.type against."""
    return set(READER_RE.findall(blob))


def best_property_recovery(blob: str, subtype: str) -> list[str]:
    """For a given subtype, scan every `{type:"<subtype>", ...}` literal in the binary
    and union the property keys we can recover from each. We pick the literal with the
    most distinct keys as the canonical shape, then union remaining literals' keys to
    catch optional fields.
    """
    candidates: list[list[str]] = []
    pat = re.compile(
        r'\{type:"' + re.escape(subtype) + r'"((?:[^{}]|\{[^{}]*\}){0,2000})\}'
    )
    for m in pat.finditer(blob):
        body = m.group(1)
        keys = ["type"]
        for k in PROP_KEY_RE.findall(body):
            if k not in keys:
                keys.append(k)
        candidates.append(keys)
    if not candidates:
        return ["type"]
    # Largest candidate as base, union the rest
    base = max(candidates, key=len)
    union = list(base)
    for c in candidates:
        for k in c:
            if k not in union:
                union.append(k)
    return union


def load_schema_subtypes(schema_path: Path) -> set[str]:
    """Pull every `attachment.type` const from the v2.1.144 schema's $defs.

    Filter out the AttachmentMessage wrapper itself (which has type:"attachment", not a subtype).
    """
    s = json.loads(schema_path.read_text())
    found: set[str] = set()
    for name, df in s.get("$defs", {}).items():
        if not name.startswith("Attachment") or name == "AttachmentMessage":
            continue
        type_prop = df.get("properties", {}).get("type", {})
        const = type_prop.get("const")
        if isinstance(const, str):
            found.add(const)
    return found


def main():
    ap = argparse.ArgumentParser()
    default_binary = Path.home() / ".local/share/claude/versions/2.1.144"
    default_schema = Path(__file__).parent / "v2.1.144" / "session.schema.json"
    ap.add_argument("--binary", type=Path, default=default_binary)
    ap.add_argument("--schema", type=Path, default=default_schema)
    ap.add_argument("--show-known", action="store_true", help="Also list subtypes already in schema")
    args = ap.parse_args()

    if not args.binary.exists():
        ap.error(f"binary not found: {args.binary}")
    if not args.schema.exists():
        ap.error(f"schema not found: {args.schema}")

    print(f"Mining {args.binary} ({args.binary.stat().st_size / 1e6:.0f}MB)...")
    blob = extract_strings(args.binary)
    print(f"  extracted {len(blob) / 1e6:.0f}MB of strings\n")

    schema_subtypes = load_schema_subtypes(args.schema)
    print(f"Schema declares {len(schema_subtypes)} attachment subtypes:")
    for s in sorted(schema_subtypes):
        print(f"  - {s}")
    print()

    # Three sources of canonical evidence:
    #   1. Reader-side: `attachment.type === "X"` — code reads X as a subtype
    #   2. Writer-side: `A9({type:"X", ...})` — code writes X through the wrapper
    #   3. Schema-side: subtypes already documented in v2.1.144 (we trust these from observation)
    reader_subtypes = find_reader_subtypes(blob)
    direct = find_direct_a9_subtypes(blob)
    canonical = reader_subtypes | set(direct.keys()) | schema_subtypes

    print(f"Reader-side evidence (attachment.type === \"X\"): {len(reader_subtypes)} subtypes")
    print(f"Writer-side evidence (A9({{type:\"X\"}})): {len(direct)} subtypes")
    print(f"Schema declares: {len(schema_subtypes)} subtypes")
    print(f"Canonical union: {len(canonical)} subtypes\n")

    missing = canonical - schema_subtypes
    only_schema = schema_subtypes - reader_subtypes - set(direct.keys())

    print("=" * 80)
    print(f"CANONICAL ATTACHMENT SUBTYPES: {len(canonical)}")
    print("=" * 80)
    print(f"  legend: [OK] in schema  [NEW] needs adding  reader/writer evidence ticks\n")
    for s in sorted(canonical):
        in_schema = "OK " if s in schema_subtypes else "NEW"
        r = "R" if s in reader_subtypes else " "
        w = "W" if s in direct else " "
        keys = best_property_recovery(blob, s)
        print(f"  [{in_schema}][{r}{w}] {s:35} keys={keys}")
    print()
    if missing:
        print(f"NEW SUBTYPES TO ADD TO SCHEMA ({len(missing)}):")
        print("-" * 80)
        for m in sorted(missing):
            keys = best_property_recovery(blob, m)
            r = "R" if m in reader_subtypes else " "
            w = "W" if m in direct else " "
            print(f"  [{r}{w}] {m:35} keys={keys}")
    if only_schema:
        print(f"\nIN SCHEMA BUT NO REGEX-RECOVERABLE READ/WRITE SITE ({len(only_schema)}):")
        print("  (Likely fine — these subtypes are built via helper functions whose A9() call")
        print("   uses a variable rather than a literal. Validated against real sessions instead.)")
        for e in sorted(only_schema):
            print(f"  - {e}")

    # Save canonical results to a JSON artifact so downstream tools (schema-update,
    # codegen) can consume the same source-of-truth.
    out_path = Path(__file__).parent / "captured" / f"binary_attachments_{args.binary.name}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    artifact = {
        "binary": str(args.binary),
        "schema_subtypes": sorted(schema_subtypes),
        "reader_subtypes": sorted(reader_subtypes),
        "writer_subtypes": sorted(direct.keys()),
        "canonical_subtypes": sorted(canonical),
        "missing_from_schema": sorted(missing),
        "properties": {s: best_property_recovery(blob, s) for s in sorted(canonical)},
    }
    out_path.write_text(json.dumps(artifact, indent=2) + "\n")
    print(f"\nArtifact saved: {out_path}")


if __name__ == "__main__":
    main()
