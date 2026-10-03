"""Merge the D01 tool registration into an ``openclaw.json`` (event day, D01).

    python -m agent.event_day.register --config openclaw.json --out merged.json
    python -m agent.event_day.register --fragment

The merged file adds ``mcp.servers.mirror`` (the seven contract tools, bearer token as the
``${AUM_TOOLS_TOKEN}`` env reference), the ``urban-mirror`` agent entry, and a
``mirror__*`` deny on every other agent. ``--url`` defaults to the sandbox's view of the
host tool server, ``http://host.openshell.internal:8090/mcp``.

The base config usually carries the gateway token and provider keys, so the merged file
does too: write it to a private path, never into the repo or ``artifacts/``. ``--fragment``
prints only the D01 part, which holds no credential.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .registration import TOKEN_ENV, merge_registration, registration, server_url


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m agent.event_day.register")
    parser.add_argument("--config", type=Path, help="base openclaw.json (default: stdin)")
    parser.add_argument("--out", type=Path, help="merged config path (default: stdout)")
    parser.add_argument("--url", default=server_url(), help="the mirror MCP URL")
    parser.add_argument(
        "--token-env",
        default=TOKEN_ENV,
        help="env var holding the bearer token ('' for none)",
    )
    parser.add_argument("--workspace", help="override the agent workspace path")
    parser.add_argument(
        "--fragment", action="store_true", help="print only the D01 registration fragment"
    )
    args = parser.parse_args(argv)
    token_env = args.token_env or None

    if args.fragment:
        print(json.dumps(registration(args.url, token_env=token_env), indent=2))
        return 0
    text = args.config.read_text(encoding="utf-8") if args.config else sys.stdin.read()
    merged = merge_registration(
        json.loads(text), args.url, token_env=token_env, workspace=args.workspace
    )
    out = json.dumps(merged, indent=2) + "\n"
    if args.out is None:
        sys.stdout.write(out)
    else:
        args.out.write_text(out, encoding="utf-8")
        os.chmod(args.out, 0o600)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
