#!/usr/bin/env python3
"""
Capture tool schemas from Claude Code API requests.

Spins up a local HTTP proxy, runs Claude Code through it, and saves
the tool definitions and system prompt blocks from the first API request.

Usage:
    python capture_tools.py                     # defaults: haiku, output to captured/
    python capture_tools.py --model sonnet      # use sonnet
    python capture_tools.py --output-dir /tmp   # custom output dir

Requires: ANTHROPIC_API_KEY set in environment (or claude CLI configured).
"""

import argparse
import http.server
import json
import os
import signal
import ssl
import subprocess
import sys
import threading
import urllib.request
from pathlib import Path

REAL_URL = "https://api.anthropic.com"


class CaptureHandler(http.server.BaseHTTPRequestHandler):
    """Proxy handler that captures the first API request with tools."""

    captured = False
    tools = None
    system = None

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)

        if b'"messages"' in body and not CaptureHandler.captured:
            data = json.loads(body)
            CaptureHandler.tools = data.get("tools", [])
            CaptureHandler.system = data.get("system", [])
            CaptureHandler.captured = True
            print(
                f"  Captured {len(CaptureHandler.tools)} tools, "
                f"{len(CaptureHandler.system)} system blocks",
                file=sys.stderr,
            )

        # Forward to real API
        ctx = ssl.create_default_context()
        req = urllib.request.Request(REAL_URL + self.path, data=body, method="POST")
        for h in self.headers:
            if h.lower() not in ("host", "content-length"):
                req.add_header(h, self.headers[h])
        req.add_header("Content-Length", str(len(body)))

        try:
            resp = urllib.request.urlopen(req, context=ctx)
            self.send_response(resp.status)
            for h, v in resp.headers.items():
                if h.lower() not in ("transfer-encoding",):
                    self.send_header(h, v)
            self.end_headers()
            while True:
                chunk = resp.read(8192)
                if not chunk:
                    break
                self.wfile.write(chunk)
        except Exception as e:
            print(f"  Proxy error: {e}", file=sys.stderr)
            self.send_error(502)

    def log_message(self, format, *args):
        pass


def find_free_port():
    import socket

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def main():
    parser = argparse.ArgumentParser(description="Capture Claude Code tool schemas")
    parser.add_argument("--model", default="haiku", help="Model to use (default: haiku)")
    parser.add_argument(
        "--output-dir",
        default=str(Path(__file__).parent / "captured"),
        help="Output directory (default: captured/)",
    )
    args = parser.parse_args()

    port = find_free_port()
    server = http.server.HTTPServer(("127.0.0.1", port), CaptureHandler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    print(f"Proxy listening on :{port}", file=sys.stderr)

    # Run claude through proxy
    env = os.environ.copy()
    env["ANTHROPIC_BASE_URL"] = f"http://127.0.0.1:{port}"
    env.pop("CLAUDECODE", None)  # bypass nested session check

    print(f"Running claude --model {args.model} ...", file=sys.stderr)
    result = subprocess.run(
        ["claude", "--model", args.model, "-p", "say hi"],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )

    server.shutdown()

    if not CaptureHandler.captured:
        print("ERROR: No API request captured", file=sys.stderr)
        print("stdout:", result.stdout[:500], file=sys.stderr)
        print("stderr:", result.stderr[:500], file=sys.stderr)
        sys.exit(1)

    # Get CLI version
    ver_result = subprocess.run(["claude", "--version"], capture_output=True, text=True)
    cli_version = ver_result.stdout.strip().split()[0] if ver_result.stdout else "unknown"

    # Write output
    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)

    tools_path = out / f"tools_{cli_version}.json"
    system_path = out / f"system_{cli_version}.json"

    with open(tools_path, "w") as f:
        json.dump(CaptureHandler.tools, f, indent=2)
        f.write("\n")

    with open(system_path, "w") as f:
        json.dump(CaptureHandler.system, f, indent=2)
        f.write("\n")

    # Summary
    builtin = [t for t in CaptureHandler.tools if not t["name"].startswith("mcp__")]
    mcp = [t for t in CaptureHandler.tools if t["name"].startswith("mcp__")]

    print(f"\nCLI version: {cli_version}")
    print(f"Tools: {len(builtin)} built-in, {len(mcp)} MCP")
    print(f"System blocks: {len(CaptureHandler.system)}")
    print(f"\nSaved:")
    print(f"  {tools_path}")
    print(f"  {system_path}")

    # Print built-in tool names
    print(f"\nBuilt-in tools:")
    for t in sorted(builtin, key=lambda x: x["name"]):
        print(f"  {t['name']}")


if __name__ == "__main__":
    main()
