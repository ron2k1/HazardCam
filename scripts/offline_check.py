#!/usr/bin/env python3
"""Check that the prebuild runs from local files only (P16).

  python scripts/offline_check.py                    # fixture path; models reported, not required
  python scripts/offline_check.py --require-models   # also fail when a local profile's model is absent

Checks: Python dependencies import; ffmpeg/ffprobe resolve; every manifest scenario has
its camera media, ground-truth media, judge labels and fixture recording; the web app is
installed and built and its source and bundle name no remote font/CDN host; the local
profiles' models are present in Ollama. Then one fixture run goes through the harness with
every non-loopback socket connect and DNS lookup in this Python process refused, so a
network call from the harness fails the check (see ``loopback_only`` for what is not covered).

Writes ``artifacts/offline/OFFLINE_CHECK.json`` and ``OFFLINE_CHECK.md``. Exit status 1 if a
required check fails.
"""

from __future__ import annotations

import argparse
import errno
import importlib
import json
import socket
import subprocess
import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

OUT = REPO / "artifacts" / "offline"
DEPENDENCIES = (
    "fastapi",
    "uvicorn",
    "sse_starlette",
    "pydantic",
    "yaml",
    "jsonschema",
    "httpx",
    "numpy",
    "cv2",
    "PIL",
)
LOCAL_PROFILES = ("lite-local", "full-local")
REMOTE_HOSTS = (
    "fonts.googleapis.com",
    "fonts.gstatic.com",
    "cdn.jsdelivr.net",
    "unpkg.com",
    "cdnjs.cloudflare.com",
)
LOOPBACK = frozenset({"127.0.0.1", "::1", "localhost"})
WEB = REPO / "apps" / "web"
GUARD_SCENARIO = "eval_001"
RECORDING_FILES = ("qwen_observations.json", "final_hypothesis.json", "provenance.json")

Result = dict[str, Any]


def _check(name: str, required: bool, fn: Callable[[], str]) -> Result:
    try:
        return {"name": name, "ok": True, "required": required, "detail": fn()}
    except Exception as exc:  # noqa: BLE001  (any failure is that check's result)
        detail = f"{type(exc).__name__}: {exc}".splitlines()[0][:300]
        return {"name": name, "ok": False, "required": required, "detail": detail}


def dependencies() -> str:
    missing = []
    for module in DEPENDENCIES:
        try:
            importlib.import_module(module)
        except ImportError:
            missing.append(module)
    if missing:
        raise RuntimeError(f"not importable: {', '.join(missing)}")
    return f"{len(DEPENDENCIES)} runtime packages import on Python {sys.version.split()[0]}"


def media_tools() -> str:
    from tools.media.binaries import ffmpeg_bin, ffprobe_bin

    return f"ffmpeg {ffmpeg_bin()}; ffprobe {ffprobe_bin()}"


def scenario_data() -> str:
    manifest = json.loads((REPO / "data" / "eval" / "manifest.json").read_text("utf-8"))
    problems = []
    media = 0
    for scenario_id in manifest["scenarios"]:
        doc = json.loads((REPO / "data" / "manifests" / f"{scenario_id}.json").read_text("utf-8"))
        files = [c["file"] for c in doc["visible_cameras"]] + [doc["ground_truth_camera"]["file"]]
        for rel in files:
            media += 1
            if not (REPO / rel).is_file():
                problems.append(rel)
        if not (REPO / "data" / "prepared" / scenario_id / "expected.json").is_file():
            problems.append(f"{scenario_id}/expected.json")
        for name in RECORDING_FILES:
            if not (REPO / "data" / "fixtures" / scenario_id / name).is_file():
                problems.append(f"data/fixtures/{scenario_id}/{name}")
    if problems:
        raise RuntimeError(f"{len(problems)} missing, first: {', '.join(problems[:4])}")
    return f"{len(manifest['scenarios'])} scenarios, {media} media files, labels and recordings"


def _remote_hits(paths: list[Path]) -> list[str]:
    hits = []
    for path in paths:
        text = path.read_text("utf-8", errors="ignore")
        hits += [f"{path.relative_to(REPO).as_posix()}: {h}" for h in REMOTE_HOSTS if h in text]
    return hits


def web_build() -> str:
    if not (WEB / "node_modules").is_dir():
        raise RuntimeError("apps/web/node_modules missing; run pnpm --dir apps/web install")
    build_id = WEB / ".next" / "BUILD_ID"
    if not build_id.is_file():
        raise RuntimeError("apps/web/.next missing; run pnpm --dir apps/web build")
    sources = [p for p in (WEB / "src").rglob("*") if p.suffix in {".ts", ".tsx", ".css"}]
    bundle = [p for p in (WEB / ".next" / "static").rglob("*") if p.suffix in {".js", ".css"}]
    hits = _remote_hits(sources + bundle)
    if hits:
        raise RuntimeError(f"remote hosts referenced: {'; '.join(hits[:3])}")
    return (
        f"build {build_id.read_text('utf-8').strip()}; {len(sources)} source and "
        f"{len(bundle)} bundle files name no remote font/CDN host"
    )


def local_models() -> str:
    import httpx

    from inference.profiles import load_profile

    wanted = {}
    for name in LOCAL_PROFILES:
        profile = load_profile(name)
        for endpoint in (profile.perception, profile.reasoning):
            wanted.setdefault(endpoint.base_url, set()).add(endpoint.model)
    found = []
    for base_url, models in wanted.items():
        tags_url = base_url.removesuffix("/v1").rstrip("/") + "/api/tags"
        tags = httpx.get(tags_url, timeout=5.0).json()
        have = {m["name"] for m in tags.get("models", [])}
        missing = sorted(models - have)
        if missing:
            raise RuntimeError(f"{base_url} lacks {', '.join(missing)}")
        found += sorted(models)
    return f"present in Ollama: {', '.join(found)}"


@contextmanager
def loopback_only() -> Iterator[list[str]]:
    """Refuse non-loopback ``connect``/``connect_ex`` and DNS lookups made through Python's
    ``socket`` module in this process; yield the refused hosts.

    Not covered: subprocesses (ffmpeg reads local files only) and asyncio's Windows
    Proactor, which connects through ConnectEx. The fixture path uses neither for network.
    """
    refused: list[str] = []
    real_connect, real_connect_ex = socket.socket.connect, socket.socket.connect_ex
    real_getaddrinfo = socket.getaddrinfo

    def _remote(address: Any) -> str | None:
        host = address[0] if isinstance(address, tuple) else str(address)
        if host in LOOPBACK:
            return None
        refused.append(host)
        return host

    def connect(sock: socket.socket, address: Any) -> Any:
        if (host := _remote(address)) is not None:
            raise OSError(f"offline check refused a connection to {host}")
        return real_connect(sock, address)

    def connect_ex(sock: socket.socket, address: Any) -> int:
        return errno.ECONNREFUSED if _remote(address) else real_connect_ex(sock, address)

    def getaddrinfo(host: Any, *args: Any, **kwargs: Any) -> Any:
        if host not in LOOPBACK and host is not None:
            refused.append(str(host))
            raise socket.gaierror(f"offline check refused a lookup of {host}")
        return real_getaddrinfo(host, *args, **kwargs)

    socket.socket.connect = connect  # type: ignore[method-assign]
    socket.socket.connect_ex = connect_ex  # type: ignore[method-assign]
    socket.getaddrinfo = getaddrinfo  # type: ignore[assignment]
    try:
        yield refused
    finally:
        socket.socket.connect = real_connect  # type: ignore[method-assign]
        socket.socket.connect_ex = real_connect_ex  # type: ignore[method-assign]
        socket.getaddrinfo = real_getaddrinfo


def guarded_fixture_run() -> str:
    from apps.api.services.scenarios import ScenarioStore
    from harness.dev_sequence import run_dev_sequence_detailed
    from inference.profiles import load_profile

    store = ScenarioStore(REPO / "data" / "manifests", REPO, REPO / "data" / "prepared")
    loaded = store.get(GUARD_SCENARIO)
    if loaded is None:
        raise RuntimeError(f"{GUARD_SCENARIO} is not prepared")
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    with loopback_only() as refused:
        result = run_dev_sequence_detailed(
            loaded.scenario,
            load_profile("fixture"),
            lambda _type, _payload: None,
            run_dir=REPO / "data" / "runs" / "offline_check" / f"{GUARD_SCENARIO}_{stamp}",
            media_root=REPO,
        )
    if refused:
        raise RuntimeError(f"network attempted: {', '.join(sorted(set(refused)))}")
    return (
        f"{GUARD_SCENARIO} fixture run with non-loopback sockets refused: "
        f"{result.hypothesis.event_type} in {result.duration_ms / 1000:.1f} s, 0 network attempts"
    )


def render(doc: dict[str, Any]) -> str:
    lines = [
        "# Offline check",
        "",
        (
            f"Checked at {doc['checked_at']} on commit `{doc['git_commit']}`. "
            f"Verdict: **{'PASS' if doc['ok'] else 'FAIL'}**."
        ),
        "",
        "| check | required | result | detail |",
        "|---|---|---|---|",
    ]
    for r in doc["checks"]:
        result = "ok" if r["ok"] else "FAIL"
        lines.append(f"| {r['name']} | {r['required']} | {result} | {r['detail']} |")
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--require-models", action="store_true", help="fail if a model is absent")
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()

    checks = [
        _check("python dependencies", True, dependencies),
        _check("ffmpeg / ffprobe", True, media_tools),
        _check("scenario data", True, scenario_data),
        _check("web install + build", True, web_build),
        _check("local models (Ollama)", args.require_models, local_models),
        _check("fixture run, network refused", True, guarded_fixture_run),
    ]
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True, text=True, check=False
    ).stdout.strip()
    doc = {
        "checked_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "git_commit": commit or None,
        "ok": all(r["ok"] for r in checks if r["required"]),
        "checks": checks,
    }
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "OFFLINE_CHECK.json").write_text(
        json.dumps(doc, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    (args.out / "OFFLINE_CHECK.md").write_text(render(doc), encoding="utf-8", newline="\n")
    for r in checks:
        print(f"{'ok  ' if r['ok'] else 'FAIL'} {r['name']}: {r['detail']}")
    return 0 if doc["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
