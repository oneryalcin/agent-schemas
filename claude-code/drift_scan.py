#!/usr/bin/env python3
"""Detect undeclared keys in JSONL session lines vs the schema's declared properties.

The session schemas use `additionalProperties: true` on every message-wrapper
$def, which is intentional for forward compatibility: a new CLI ships a new
field and the validator stays green. But that hides drift from consumers —
codegen drops the field silently, downstream tools never see it.

This script doesn't change validation behavior. It walks a JSONL corpus and
reports every observed key that the schema doesn't declare in `properties`.
Use it on a current capture corpus before each schema bump to discover what
needs adding.

Usage:
    python drift_scan.py ~/.claude/projects/<your-project>/
    python drift_scan.py <single-file>.jsonl
    python drift_scan.py <directory> --version 2.1.144     # force schema version
    python drift_scan.py <directory> --top N               # show top N undeclared keys

Exit code is nonzero if any undeclared keys are found (useful for CI).
"""

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Iterable

import importlib.util


def _import_validator_module():
    """Load validate.py for its detect_version + schema-routing helpers."""
    here = Path(__file__).parent
    spec = importlib.util.spec_from_file_location("validate", here / "validate.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["validate"] = mod
    spec.loader.exec_module(mod)
    return mod


validate_mod = _import_validator_module()


# ---------------------------------------------------------------------------
# Schema-side: collect declared property names per $def.
# ---------------------------------------------------------------------------

def declared_properties(defn: dict) -> set[str]:
    """Return the set of property names declared on `defn`.

    Handles direct `properties`, plus oneOf/anyOf/allOf branches by unioning
    their declared property sets (consumers reading any branch need to know
    about all of them).
    """
    props: set[str] = set()
    if isinstance(defn, dict):
        for k in (defn.get("properties") or {}):
            props.add(k)
        for combiner in ("oneOf", "anyOf", "allOf"):
            for branch in defn.get(combiner) or []:
                props |= declared_properties(branch)
    return props


def load_schema(version: str) -> dict:
    """Load the schema for the given version key (e.g. '2.1.144')."""
    return validate_mod.get_schema_for_version(version)


# ---------------------------------------------------------------------------
# Line-side: discriminate which $def applies to a given JSONL line and which
# nested path to inspect.
#
# A "bucket" is the tuple (def_name, optional sub-discriminator string).
# For attachments and system messages we widen the bucket by their sub-type
# so drift on `attachment.hook_success.command` doesn't get conflated with
# drift on `attachment.queued_command.commandMode`.
# ---------------------------------------------------------------------------

def discriminate(line: dict) -> list[tuple[str, str, dict]]:
    """Yield (bucket_label, def_lookup_path, target_obj) inspect targets.

    `def_lookup_path` is dotted: e.g. "UserMessage" inspects the top-level $def;
    "UserMessage/properties/message" inspects the nested message-shape schema
    that UserMessage's `message` property declares inline. This avoids the
    bug where comparing inner message keys against the outer wrapper's
    declared properties falsely flags every inner key as drift.
    """
    top = line.get("type")
    targets: list[tuple[str, str, dict]] = []
    if top == "user":
        targets.append(("user", "UserMessage", line))
        msg = line.get("message")
        if isinstance(msg, dict):
            targets.append(("user.message", "UserMessage/properties/message", msg))
    elif top == "assistant":
        targets.append(("assistant", "AssistantMessage", line))
        msg = line.get("message")
        if isinstance(msg, dict):
            targets.append(("assistant.message", "AssistantMessage/properties/message", msg))
            usage = msg.get("usage")
            if isinstance(usage, dict):
                # UsageInfo is its own $def referenced from message.usage.
                targets.append(("assistant.message.usage", "UsageInfo", usage))
    elif top == "system":
        sub = line.get("subtype") or ""
        targets.append((f"system[{sub}]", "SystemMessage", line))
    elif top == "attachment":
        targets.append(("attachment", "AttachmentMessage", line))
        att = line.get("attachment")
        if isinstance(att, dict):
            sub = att.get("type") or "?"
            inner_def = ATTACHMENT_SUBTYPE_DEFS.get(sub)
            if inner_def:
                targets.append((f"attachment.{sub}", inner_def, att))
            else:
                # Subtype literal not in any Attachment* $def — record as a
                # special bucket so the missing-subtype is reported clearly.
                targets.append((f"attachment.{sub}", f"!Attachment[{sub}]", att))
    elif top == "summary":
        targets.append(("summary", "SummaryMessage", line))
    elif top == "progress":
        targets.append(("progress", "ProgressMessage", line))
        data = line.get("data")
        if isinstance(data, dict):
            sub = data.get("type") or "?"
            inner_def = PROGRESS_SUBTYPE_DEFS.get(sub)
            if inner_def:
                targets.append((f"progress.{sub}", inner_def, data))
            else:
                targets.append((f"progress.{sub}", f"!ProgressData[{sub}]", data))
    elif top == "file-history-snapshot":
        targets.append(("file-history-snapshot", "FileHistorySnapshot", line))
    elif top == "queue-operation":
        targets.append(("queue-operation", "QueueOperation", line))
    elif top == "pr-link":
        targets.append(("pr-link", "PRLinkMessage", line))
    elif top == "agent-name":
        targets.append(("agent-name", "AgentNameMessage", line))
    elif top == "custom-title":
        targets.append(("custom-title", "CustomTitleMessage", line))
    elif top == "last-prompt":
        targets.append(("last-prompt", "LastPromptMessage", line))
    elif top == "permission-mode":
        targets.append(("permission-mode", "PermissionModeMessage", line))
    elif top == "ai-title":
        targets.append(("ai-title", "AITitleMessage", line))
    elif top == "agent-setting":
        targets.append(("agent-setting", "AgentSettingMessage", line))
    elif top == "bridge-session":
        targets.append(("bridge-session", "BridgeSessionMessage", line))
    elif top == "worktree-state":
        targets.append(("worktree-state", "WorktreeStateMessage", line))
    return targets


# Populated lazily from the loaded schema (one schema per file → cached).
ATTACHMENT_SUBTYPE_DEFS: dict[str, str] = {}
PROGRESS_SUBTYPE_DEFS: dict[str, str] = {}


def rebuild_discriminator_maps(schema: dict) -> None:
    """Map subtype const → $def name for the currently loaded schema."""
    ATTACHMENT_SUBTYPE_DEFS.clear()
    PROGRESS_SUBTYPE_DEFS.clear()
    for name, df in (schema.get("$defs") or {}).items():
        if not isinstance(df, dict):
            continue
        type_prop = (df.get("properties") or {}).get("type") or {}
        const = type_prop.get("const")
        if not isinstance(const, str):
            continue
        if name.startswith("Attachment") and name != "AttachmentMessage":
            ATTACHMENT_SUBTYPE_DEFS[const] = name
        # ProgressData branch defs — the schema names them MCPProgressData,
        # BashProgressData, HookProgressData, AgentProgressData,
        # WaitingForTaskData, QueryUpdateData, SearchResultsReceivedData.
        # All carry a `type` const matching their progress subtype.
        elif name.endswith(("ProgressData", "TaskData", "UpdateData", "ReceivedData")):
            PROGRESS_SUBTYPE_DEFS[const] = name


def resolve_def_props(schema: dict, lookup: str) -> set[str]:
    """Resolve a `Def` or `Def/properties/field` path to its declared property set.

    Paths starting with `!` mark unresolved subtypes (e.g. an attachment
    subtype not in the schema); we return an empty set so every key on that
    line shows as drift, which is the desired signal.
    """
    if lookup.startswith("!"):
        return set()
    parts = lookup.split("/")
    if not parts:
        return set()
    defs = schema.get("$defs") or {}
    current = defs.get(parts[0])
    if current is None:
        return set()
    for p in parts[1:]:
        if not isinstance(current, dict):
            return set()
        current = current.get(p)
        if current is None:
            return set()
    return declared_properties(current)


# ---------------------------------------------------------------------------
# Walking the corpus.
# ---------------------------------------------------------------------------

def iter_jsonl_with_version(path: Path) -> Iterable[tuple[Path, int, dict, str | None]]:
    """Yield (file, line_num, parsed_obj, schema_version) over every line in `path`.

    Version is detected once per file using all its lines (matches validate.py),
    not per-line — line-by-line detection misroutes version-less lines to the
    v2.0.76 fallback even when the file is genuinely 2.1.x.
    """
    if path.is_file():
        files = [path]
    else:
        files = sorted(path.rglob("*.jsonl"))
    for f in files:
        try:
            # First pass: parse all lines, detect version
            lines: list[tuple[int, dict]] = []
            with f.open() as fh:
                for ln, line in enumerate(fh, 1):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        lines.append((ln, json.loads(line)))
                    except json.JSONDecodeError:
                        continue
            if not lines:
                continue
            schema_version, _ = validate_mod.detect_version([obj for _ln, obj in lines])
            for ln, obj in lines:
                yield f, ln, obj, schema_version
        except OSError:
            continue


def scan(corpus: Path, version_override: str | None = None) -> dict:
    """Walk the corpus and return per-bucket drift findings.

    Returns:
        {
            (schema_version, bucket_label): {
                "def": def_name,
                "undeclared": {key: {"count": int, "example": (file, line)}},
                "total_lines": int,
            }
        }
    """
    # Cache per-version: schema dict (declared-props is computed per lookup
    # path so we can't pre-build a single name→set map).
    schema_cache: dict[str, dict] = {}
    declared_cache: dict[tuple[str, str], set[str]] = {}

    findings: dict[tuple[str, str], dict] = defaultdict(lambda: {
        "def": "",
        "undeclared": defaultdict(lambda: {"count": 0, "example": None}),
        "total_lines": 0,
    })

    for f, ln, obj, schema_version in iter_jsonl_with_version(corpus):
        if version_override:
            schema_version = version_override
        if not schema_version:
            continue

        if schema_version not in schema_cache:
            schema = load_schema(schema_version)
            schema_cache[schema_version] = schema
        schema = schema_cache[schema_version]
        rebuild_discriminator_maps(schema)

        for bucket_label, lookup, target in discriminate(obj):
            key = (schema_version, bucket_label)
            findings[key]["def"] = lookup
            findings[key]["total_lines"] += 1
            cache_key = (schema_version, lookup)
            if cache_key not in declared_cache:
                declared_cache[cache_key] = resolve_def_props(schema, lookup)
            declared = declared_cache[cache_key]
            for k in target.keys():
                if k in declared:
                    continue
                entry = findings[key]["undeclared"][k]
                entry["count"] += 1
                if entry["example"] is None:
                    entry["example"] = (str(f), ln)

    return findings


# ---------------------------------------------------------------------------
# Reporting.
# ---------------------------------------------------------------------------

def report(findings: dict, top: int | None = None) -> int:
    """Print a per-bucket drift table. Returns shell exit code."""
    has_drift = False
    total_buckets = 0
    drift_buckets = 0
    grand_total_undeclared = 0

    sorted_keys = sorted(findings.keys())
    for key in sorted_keys:
        schema_v, bucket = key
        f = findings[key]
        total_buckets += 1
        if not f["undeclared"]:
            continue
        drift_buckets += 1
        has_drift = True

        print(f"\n[{schema_v}] {bucket:35} → $def: {f['def']:35} lines={f['total_lines']}")
        items = sorted(f["undeclared"].items(), key=lambda kv: -kv[1]["count"])
        if top:
            items = items[:top]
        for key_name, info in items:
            grand_total_undeclared += info["count"]
            ex_file, ex_ln = info["example"]
            ex = f"{ex_file}:{ex_ln}"
            # Trim long file paths for display
            if len(ex) > 80:
                ex = "..." + ex[-77:]
            print(f"  + {key_name:30}  count={info['count']:6d}  e.g. {ex}")

    print("\n" + "=" * 72)
    if has_drift:
        print(f"DRIFT FOUND: {drift_buckets}/{total_buckets} buckets have undeclared keys.")
        print(f"  Total undeclared-key occurrences: {grand_total_undeclared}")
        return 1
    print(f"NO DRIFT: all {total_buckets} buckets match their declared properties.")
    return 0


# ---------------------------------------------------------------------------
# CLI.
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("corpus", type=Path, help="JSONL file or directory tree of session files")
    ap.add_argument("--version", help="Force a schema version (e.g. 2.1.144) instead of auto-detecting per file")
    ap.add_argument("--top", type=int, default=None, help="Show only the top N undeclared keys per bucket")
    args = ap.parse_args()

    if not args.corpus.exists():
        print(f"error: corpus path {args.corpus} does not exist", file=sys.stderr)
        sys.exit(2)

    findings = scan(args.corpus, version_override=args.version)
    if not findings:
        print("(no sessions inspected — corpus empty or all lines below minimum supported version)")
        sys.exit(0)
    sys.exit(report(findings, top=args.top))


if __name__ == "__main__":
    main()
