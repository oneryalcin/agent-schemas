#!/usr/bin/env python3
"""
Claude Code Session Schema Validator

Validates JSONL session files against the appropriate version schema.
Usage:
    python validate.py <directory_or_file>
    python validate.py ~/.claude/projects/<your-project>/
    python validate.py ~/.claude/projects/<your-project>/session.jsonl
"""

import json
import os
import sys
from pathlib import Path
from collections import defaultdict
from typing import Optional, Tuple

try:
    import jsonschema
    from jsonschema import Draft202012Validator
except ImportError:
    print("Error: jsonschema not installed. Run: pip install jsonschema")
    sys.exit(1)

SCRIPT_DIR = Path(__file__).parent
SCHEMA_V2_0_76 = SCRIPT_DIR / "v2.0.76" / "session.schema.json"
SCHEMA_V2_1_1 = SCRIPT_DIR / "v2.1.1" / "session.schema.json"
SCHEMA_V2_1_59 = SCRIPT_DIR / "v2.1.59" / "session.schema.json"
SCHEMA_HISTORY = SCRIPT_DIR / "history.schema.json"


def load_schema(path: Path) -> dict:
    """Load and return a JSON schema."""
    with open(path) as f:
        return json.load(f)


def parse_semver(version: str) -> tuple[int, int, int]:
    """Parse a semver string into (major, minor, patch)."""
    parts = version.split(".")
    return (int(parts[0]), int(parts[1]), int(parts[2]))


MIN_SUPPORTED_VERSION = (2, 0, 76)


def detect_version(lines: list[dict]) -> Tuple[Optional[str], Optional[str]]:
    """Detect CLI version from session lines.

    Returns (schema_key, raw_version):
    - ("2.1.59", raw) for CLI >= 2.1.2
    - ("2.1.1", raw)  for CLI 2.1.0-2.1.1
    - ("2.0.76", raw)  for CLI 2.0.76-2.0.x
    - (None, raw)     for CLI < 2.0.76 (unsupported)
    """
    for line in lines:
        if "version" in line and line["version"]:
            version = line["version"]
            try:
                major, minor, patch = parse_semver(version)
            except (ValueError, IndexError):
                continue
            if (major, minor, patch) < MIN_SUPPORTED_VERSION:
                return None, version
            if major >= 2 and minor >= 1 and patch >= 2:
                return "2.1.59", version
            if major >= 2 and minor >= 1:
                return "2.1.1", version
            return "2.0.76", version
    # If no version found, check for progress messages (v2.1.2+)
    for line in lines:
        if line.get("type") == "progress":
            return "2.1.59", None
    return "2.0.76", None


def get_schema_for_version(version: str) -> dict:
    """Get the appropriate schema for a version."""
    if version == "2.1.59":
        return load_schema(SCHEMA_V2_1_59)
    if version == "2.1.1":
        return load_schema(SCHEMA_V2_1_1)
    return load_schema(SCHEMA_V2_0_76)


def validate_line(line: dict, validator: Draft202012Validator, line_num: int, file_path: str) -> list[dict]:
    """Validate a single line and return errors."""
    errors = []
    for error in validator.iter_errors(line):
        errors.append({
            "file": file_path,
            "line": line_num,
            "path": ".".join(str(p) for p in error.absolute_path) or "(root)",
            "message": error.message,
            "schema_path": ".".join(str(p) for p in error.schema_path),
            "snippet": json.dumps(line)[:200] + "..." if len(json.dumps(line)) > 200 else json.dumps(line)
        })
    return errors


def validate_file(file_path: Path) -> dict:
    """Validate a single JSONL file. Returns a result dict."""
    result = {
        "total_lines": 0,
        "valid_lines": 0,
        "errors": [],
        "skipped": False,
        "skip_reason": None,
        "raw_version": None,
        "schema_version": None,
    }

    # First pass: read all lines and detect version
    lines = []
    with open(file_path, 'r', encoding='utf-8') as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                lines.append((line_num, data))
            except json.JSONDecodeError as e:
                result["errors"].append({
                    "file": str(file_path),
                    "line": line_num,
                    "path": "(parse)",
                    "message": f"JSON parse error: {e}",
                    "schema_path": "",
                    "snippet": line[:200] + "..." if len(line) > 200 else line
                })

    if not lines:
        return result

    # Detect version
    schema_version, raw_version = detect_version([l[1] for l in lines])
    result["raw_version"] = raw_version
    result["schema_version"] = schema_version

    if schema_version is None:
        min_ver = ".".join(str(v) for v in MIN_SUPPORTED_VERSION)
        result["skipped"] = True
        result["skip_reason"] = f"CLI version {raw_version} < minimum supported {min_ver}"
        result["total_lines"] = len(lines)
        return result

    schema = get_schema_for_version(schema_version)
    validator = Draft202012Validator(schema)

    # Validate each line
    for line_num, data in lines:
        result["total_lines"] += 1
        line_errors = validate_line(data, validator, line_num, str(file_path))
        if line_errors:
            result["errors"].extend(line_errors)
        else:
            result["valid_lines"] += 1

    return result


def validate_directory(dir_path: Path) -> dict:
    """Validate all JSONL files in a directory."""
    results = {
        "total_files": 0,
        "total_lines": 0,
        "valid_lines": 0,
        "failed_files": 0,
        "errors": [],
        "error_types": defaultdict(int),
        "skipped_files": [],  # list of (filename, version, reason, num_lines)
    }

    jsonl_files = list(dir_path.glob("*.jsonl"))
    results["total_files"] = len(jsonl_files)

    for file_path in jsonl_files:
        if file_path.stat().st_size == 0:
            continue

        try:
            file_result = validate_file(file_path)

            if file_result["skipped"]:
                results["skipped_files"].append((
                    file_path.name,
                    file_result["raw_version"],
                    file_result["skip_reason"],
                    file_result["total_lines"],
                ))
                continue

            results["total_lines"] += file_result["total_lines"]
            results["valid_lines"] += file_result["valid_lines"]

            if file_result["errors"]:
                results["failed_files"] += 1
                results["errors"].extend(file_result["errors"])
                for e in file_result["errors"]:
                    if "parse error" in e["message"].lower():
                        results["error_types"]["JSON parse errors"] += 1
                    elif "required" in e["message"].lower():
                        results["error_types"]["Missing required fields"] += 1
                    elif "not valid" in e["message"].lower():
                        results["error_types"]["Invalid value"] += 1
                    elif "additionalProperties" in e["message"].lower():
                        results["error_types"]["Unknown fields"] += 1
                    else:
                        results["error_types"]["Other"] += 1
        except Exception as e:
            results["failed_files"] += 1
            results["errors"].append({
                "file": str(file_path),
                "line": 0,
                "path": "(file)",
                "message": f"File error: {e}",
                "schema_path": "",
                "snippet": ""
            })

    return results


def print_results(results: dict, verbose: bool = False):
    """Print validation results."""
    print("\n" + "=" * 60)
    print("VALIDATION RESULTS")
    print("=" * 60)

    skipped = results.get("skipped_files", [])
    validated_files = results["total_files"] - len(skipped)

    print(f"\nFiles scanned:   {results['total_files']}")
    print(f"Files validated: {validated_files}")
    print(f"Files skipped:   {len(skipped)}")
    print(f"Total lines:     {results['total_lines']}")
    print(f"Valid lines:     {results['valid_lines']}")
    print(f"Failed lines:    {results['total_lines'] - results['valid_lines']}")
    print(f"Files w/errors:  {results['failed_files']}")

    if skipped:
        min_ver = ".".join(str(v) for v in MIN_SUPPORTED_VERSION)
        skipped_lines = sum(s[3] for s in skipped)
        print(f"\nSkipped files (CLI < {min_ver}, no schema available):")
        for name, version, reason, num_lines in skipped:
            print(f"  {name}: v{version} ({num_lines} lines)")

    if results["error_types"]:
        print("\nError types:")
        for error_type, count in sorted(results["error_types"].items(), key=lambda x: -x[1]):
            print(f"  {error_type}: {count}")

    if results["errors"]:
        print(f"\n{'=' * 60}")
        print(f"ERRORS (showing first 50)")
        print("=" * 60)

        for i, error in enumerate(results["errors"][:50]):
            print(f"\n[{i+1}] {error['file']}:{error['line']}")
            print(f"    Path: {error['path']}")
            print(f"    Error: {error['message']}")
            if verbose and error['snippet']:
                print(f"    Data: {error['snippet'][:100]}...")

    # Summary
    if results['total_lines'] == 0 and skipped:
        print(f"\n{'=' * 60}")
        print("NO LINES VALIDATED (all files below minimum supported version)")
        print("=" * 60)
        return 0

    success_rate = (results['valid_lines'] / results['total_lines'] * 100) if results['total_lines'] > 0 else 100
    print(f"\n{'=' * 60}")
    print(f"SUCCESS RATE: {success_rate:.2f}%")
    print("=" * 60)

    if success_rate == 100:
        print("\nAll lines validated successfully!")
        return 0
    else:
        print(f"\n{results['total_lines'] - results['valid_lines']} lines failed validation.")
        return 1


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    target = Path(sys.argv[1]).expanduser()
    verbose = "--verbose" in sys.argv or "-v" in sys.argv

    if not target.exists():
        print(f"Error: {target} does not exist")
        sys.exit(1)

    if target.is_file():
        file_result = validate_file(target)
        skipped = []
        if file_result["skipped"]:
            skipped.append((
                target.name, file_result["raw_version"],
                file_result["skip_reason"], file_result["total_lines"],
            ))
        results = {
            "total_files": 1,
            "total_lines": 0 if file_result["skipped"] else file_result["total_lines"],
            "valid_lines": file_result["valid_lines"],
            "failed_files": 1 if file_result["errors"] else 0,
            "errors": file_result["errors"],
            "error_types": defaultdict(int),
            "skipped_files": skipped,
        }
        for e in file_result["errors"]:
            if "parse error" in e["message"].lower():
                results["error_types"]["JSON parse errors"] += 1
            elif "required" in e["message"].lower():
                results["error_types"]["Missing required fields"] += 1
            else:
                results["error_types"]["Other"] += 1
    else:
        results = validate_directory(target)

    exit_code = print_results(results, verbose)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
