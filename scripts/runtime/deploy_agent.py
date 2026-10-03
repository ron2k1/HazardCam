"""Deploy the ``urban-mirror`` agent into the NemoClaw sandbox (event day, D02).

    .venv/bin/python scripts/runtime/deploy_agent.py [--sandbox ambient-mirror] [--dry-run]

Steps, all through OpenShell (``openshell sandbox exec``, run as the sandbox user):

1. applies the ``mirror-tools`` egress preset (``runtime/nemoclaw/mirror-tools.policy.yaml``);
2. copies D00's workspace files to the agent's workspace in the sandbox;
3. reads the sandbox ``openclaw.json``, merges D01's registration into it
   (``agent.event_day.registration.merge_registration``: the ``mirror`` MCP server at
   ``http://host.openshell.internal:8090/mcp``, the ``urban-mirror`` agent, a
   ``mirror__*`` deny on every other agent), writes it back and refreshes
   ``.config-hash`` so the OpenClaw gateway hot-reloads it.

The tool server's bearer token lives in ``~/.config/ambient-mirror/tools.token`` (0600,
created on first run, outside the repo). The NemoClaw gateway process does not carry
``AUM_TOOLS_TOKEN`` in its environment, so the merged header holds the literal token; the
file stays 0600 in the sandbox and the agent has no fs/runtime tools to read it. The
merged config is never written on the host. Nothing here prints a token.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import secrets
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from agent.event_day.registration import (
    AGENT_FILE,
    SERVER_NAME,
    TOKEN_ENV,
    WORKSPACE_DIR,
    merge_registration,
    server_url,
)

STATE_DIR = "/sandbox/.openclaw"
CONFIG = f"{STATE_DIR}/openclaw.json"
PRESET = REPO / "runtime" / "nemoclaw" / "mirror-tools.policy.yaml"
PRIVATE_DIR = Path(os.environ.get("AUM_PRIVATE_DIR", Path.home() / ".config" / "ambient-mirror"))
TOKEN_FILE = PRIVATE_DIR / "tools.token"
AGENT_MAX_TOKENS = int(os.environ.get("AUM_AGENT_MAX_TOKENS", "16384"))


def tool(name: str) -> str:
    found = shutil.which(name) or str(Path.home() / ".local" / "bin" / name)
    if not Path(found).exists():
        raise SystemExit(f"{name} not found (add ~/.local/bin to PATH)")
    return found


def sandbox_sh(sandbox: str, script: str, data: bytes | None = None) -> bytes:
    """Run ``sh -c script`` in the sandbox. stdin is ``data`` or closed."""
    proc = subprocess.run(
        [tool("openshell"), "sandbox", "exec", "-n", sandbox, "--", "sh", "-c", script],
        input=data if data is not None else b"",
        capture_output=True,
        timeout=120,
        check=False,
    )
    if proc.returncode != 0:
        tail = proc.stderr.decode(errors="replace").strip().splitlines()[-3:]
        raise SystemExit(f"sandbox command failed ({proc.returncode}): {' | '.join(tail)}")
    return proc.stdout


def tools_token() -> str:
    PRIVATE_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    if not TOKEN_FILE.exists() or not TOKEN_FILE.read_text().strip():
        fd = os.open(TOKEN_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as fh:
            fh.write(secrets.token_urlsafe(32) + "\n")
    os.chmod(TOKEN_FILE, 0o600)
    return TOKEN_FILE.read_text().strip()


def workspace_tar() -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        for path in sorted(WORKSPACE_DIR.glob("*.md")):
            info = tar.gettarinfo(str(path), arcname=path.name)
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            info.mode = 0o644
            with path.open("rb") as fh:
                tar.addfile(info, fh)
    return buf.getvalue()


def merged_config(base: dict, token: str) -> dict:
    merged = merge_registration(base, server_url(), token_env=TOKEN_ENV)
    server = merged["mcp"]["servers"][SERVER_NAME]
    server["headers"] = {"Authorization": f"Bearer {token}"}
    _raise_max_tokens(merged)
    return merged


def _raise_max_tokens(config: dict) -> None:
    """Lift the per-completion cap of the agent's model to ``AGENT_MAX_TOKENS``.

    NemoClaw onboards the local Qwen with ``maxTokens: 4096``. A real run on eval_001 ended
    with ``stopReason=length`` before the submit, so the agent's model entry gets more room
    (the server's context is 262144). Only raises, never lowers; other models are untouched.
    """
    provider_id, _, model_id = json.loads(AGENT_FILE.read_text())["model"]["primary"].partition("/")
    provider = config.get("models", {}).get("providers", {}).get(provider_id, {})
    for model in provider.get("models", []):
        if model.get("id") == model_id:
            model["maxTokens"] = max(int(model.get("maxTokens") or 0), AGENT_MAX_TOKENS)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="deploy_agent.py")
    parser.add_argument("--sandbox", default=os.environ.get("AUM_SANDBOX", "ambient-mirror"))
    parser.add_argument("--dry-run", action="store_true", help="print the plan, change nothing")
    args = parser.parse_args(argv)

    workspace = json.loads(AGENT_FILE.read_text())["workspace"]
    base = json.loads(sandbox_sh(args.sandbox, f"cat {CONFIG}"))
    token = tools_token()
    merged = merged_config(base, token)
    agents = [a.get("id") for a in merged["agents"]["list"]]
    print(f"sandbox={args.sandbox} agents={agents} mcp={sorted(merged['mcp']['servers'])}")
    print(f"mirror url={merged['mcp']['servers'][SERVER_NAME]['url']} workspace={workspace}")
    if args.dry_run:
        print("--dry-run: nothing changed")
        return 0

    subprocess.run(
        [tool("nemoclaw"), args.sandbox, "policy", "add", "--from-file", str(PRESET), "--yes"],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        timeout=180,
        check=True,
    )
    print("policy: mirror-tools applied")

    sandbox_sh(args.sandbox, f"mkdir -p {workspace} && tar -C {workspace} -xf -", workspace_tar())
    print(f"workspace: {len(list(WORKSPACE_DIR.glob('*.md')))} files -> {workspace}")

    body = (json.dumps(merged, indent=2) + "\n").encode()
    digest = hashlib.sha256(body).hexdigest()
    sandbox_sh(
        args.sandbox,
        f"umask 077 && cd {STATE_DIR} && {{ [ -e openclaw.json.pre-d02 ] || cp openclaw.json openclaw.json.pre-d02; }} && "
        "cat > openclaw.json.d02 && mv openclaw.json.d02 openclaw.json && "
        "sha256sum openclaw.json > .config-hash && sha256sum openclaw.json",
        body,
    )
    print(f"openclaw.json: merged and hash refreshed (sha256 {digest[:12]}...)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
