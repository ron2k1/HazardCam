"""P16: start_app.sh starts both servers and stops them completely (the stop itself:
test_proc.py); run.sh's e2e targets pin their profile and scope.

The servers are stubs (real uvicorn on a tiny ASGI app, a node stand-in for next) in a scratch
tree, so the lifecycle runs in seconds and nothing is written to the repo.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from tests.unit.scripts._shell import BASH, run_script, script_tree

pytestmark = pytest.mark.skipif(BASH is None, reason="no bash to run the scripts with")


class _Answers(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()

    def log_message(self, *args):
        pass


def test_start_app_refuses_a_port_that_already_answers(tmp_path):
    # Otherwise the readiness check would pass against a server that is not ours.
    root = script_tree(tmp_path / "repo", "start_app.sh", "_python.sh", "_proc.sh")
    with ThreadingHTTPServer(("127.0.0.1", 0), _Answers) as foreign:
        threading.Thread(target=foreign.serve_forever, daemon=True).start()
        port = foreign.server_address[1]
        try:
            done = run_script(
                root / "scripts" / "start_app.sh",
                tmp_path,
                env={"API_PORT": str(port), "WEB_PORT": "1"},
            )
        finally:
            foreign.shutdown()
    assert done.returncode == 1
    assert f"something already answers http://127.0.0.1:{port}/healthz" in done.stderr


def test_start_app_rejects_an_unknown_argument(tmp_path):
    root = script_tree(tmp_path / "repo", "start_app.sh", "_python.sh", "_proc.sh")
    done = run_script(root / "scripts" / "start_app.sh", tmp_path, "--bogus")
    assert done.returncode == 2
    assert "usage: scripts/start_app.sh [--smoke]" in done.stderr


# --- start_app lifecycle on stub servers -----------------------------------------------------

NODE = shutil.which("node")

# Real uvicorn serves this, so the API job is the same shape as the real one.
_STUB_API = """\
import os
from pathlib import Path

Path(os.environ["STUB_API_PIDFILE"]).write_text(str(os.getpid()))


async def app(scope, receive, send):
    if scope["type"] == "lifespan":
        while True:
            message = await receive()
            if message["type"] == "lifespan.startup":
                await send({"type": "lifespan.startup.complete"})
            elif message["type"] == "lifespan.shutdown":
                await send({"type": "lifespan.shutdown.complete"})
                return
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": b"ok"})
"""

# Stands in for node_modules/next/dist/bin/next: `build` empties .next as the real one does
# (cleanDistDir) and logs that it ran; `start` answers 200 on -p.
_STUB_NEXT = """\
const fs = require("fs");
const http = require("http");
const [cmd, ...args] = process.argv.slice(2);
if (cmd === "build") {
  fs.rmSync(".next", { recursive: true, force: true });
  fs.mkdirSync(".next");
  fs.appendFileSync(process.env.STUB_NEXT_LOG, `build ${process.env.NEXT_PUBLIC_API_BASE_URL}\\n`);
  if (process.env.STUB_KILL_API_ON_BUILD) {
    process.kill(Number(fs.readFileSync(process.env.STUB_API_PIDFILE, "utf8")));
  }
} else if (cmd === "start") {
  fs.writeFileSync(process.env.STUB_WEB_PIDFILE, String(process.pid));
  http.createServer((req, res) => res.end("ok")).listen(Number(args[args.indexOf("-p") + 1]), "127.0.0.1");
} else {
  process.exit(2);
}
"""

needs_node = pytest.mark.skipif(NODE is None, reason="no node for the stub next")


def _app_tree(tmp_path: Path) -> Path:
    return script_tree(
        tmp_path / "repo",
        "start_app.sh",
        "_python.sh",
        "_proc.sh",
        files={
            # regular packages, so no other `apps` on sys.path can shadow the stub
            "apps/__init__.py": "",
            "apps/api/__init__.py": "",
            "apps/api/main.py": _STUB_API,
            "apps/web/node_modules/next/dist/bin/next": _STUB_NEXT,
        },
    )


def _free_ports() -> dict[str, str]:
    with socket.socket() as api, socket.socket() as web:
        api.bind(("127.0.0.1", 0))
        web.bind(("127.0.0.1", 0))
        return {"API_PORT": str(api.getsockname()[1]), "WEB_PORT": str(web.getsockname()[1])}


def _refused(port: str, within_s: float = 3.0) -> bool:
    """Nothing accepts on the port; polled, since a killed server's socket closes asynchronously."""
    deadline = time.monotonic() + within_s
    while True:
        try:
            socket.create_connection(("127.0.0.1", int(port)), timeout=0.5).close()
        except OSError:
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.1)


def _pid_in(path: Path) -> int | None:
    try:
        return int(path.read_text())
    except (OSError, ValueError):
        return None


def _start_app(tmp_path, *args, script="start_app.sh", ports=None, env=None):
    """Run a script in the stub tree with output in files, not pipes: a server the script fails
    to stop would otherwise hold the test open. Reports the ports still open when it returned,
    then ends any server it left behind."""
    root = tmp_path / "repo"
    ports = ports or _free_ports()
    stub = {
        "PYTHON": Path(sys.executable).as_posix(),
        "STUB_API_PIDFILE": (tmp_path / "api.pid").as_posix(),
        "STUB_WEB_PIDFILE": (tmp_path / "web.pid").as_posix(),
        "STUB_NEXT_LOG": (tmp_path / "next.log").as_posix(),
        "READY_TIMEOUT_S": "30",
    }
    out, err = tmp_path / "out.txt", tmp_path / "err.txt"
    assert BASH is not None
    left_open: list[str] | None = None
    try:
        with out.open("w") as stdout, err.open("w") as stderr:
            done = subprocess.run(
                [BASH, (root / "scripts" / script).as_posix(), *args],
                cwd=tmp_path,
                env={**os.environ, **stub, **ports, **(env or {})},
                stdout=stdout,
                stderr=stderr,
                timeout=90,
                check=False,
            )
        left_open = [name for name, port in ports.items() if not _refused(port)]
    finally:
        # Only a server whose port still answers: a pid file outlives its server, and Windows
        # hands a freed pid to the next process.
        if left_open is None:
            left_open = [name for name, port in ports.items() if not _refused(port, 0)]
        for name, pidfile in (("API_PORT", "api.pid"), ("WEB_PORT", "web.pid")):
            pid = _pid_in(tmp_path / pidfile)
            if name in left_open and pid is not None:
                with contextlib.suppress(OSError):
                    os.kill(pid, signal.SIGTERM)
    return done.returncode, out.read_text(), err.read_text(), ports, left_open


@needs_node
def test_start_app_smoke_starts_both_servers_and_stops_them(tmp_path):
    root = _app_tree(tmp_path)
    code, out, err, ports, left_open = _start_app(tmp_path, "--smoke")
    assert code == 0, err
    assert "smoke: api and web answer; stopping" in out
    # the probes before start expect refusals; curl must not report them as errors
    assert "curl:" not in err
    assert left_open == []
    api_url = f"http://127.0.0.1:{ports['API_PORT']}"
    assert (tmp_path / "next.log").read_text() == f"build {api_url}\n"
    assert (root / "apps/web/.next/api-base-url.txt").read_text() == f"{api_url}\n"


@needs_node
@pytest.mark.skipif(os.name != "nt", reason="MSYS argument conversion exists only in Git Bash")
def test_start_app_stops_its_servers_with_msys_path_conversion_off(tmp_path):
    _app_tree(tmp_path)
    code, _, err, _, left_open = _start_app(tmp_path, "--smoke", env={"MSYS_NO_PATHCONV": "1"})
    assert code == 0, err
    assert left_open == []


@needs_node
def test_start_app_smoke_fails_when_the_api_died_during_the_build(tmp_path):
    _app_tree(tmp_path)
    code, out, err, ports, left_open = _start_app(
        tmp_path, "--smoke", env={"STUB_KILL_API_ON_BUILD": "1"}
    )
    assert code == 1
    assert f"api no longer answers http://127.0.0.1:{ports['API_PORT']}/healthz" in err
    assert "smoke: api and web answer" not in out
    assert left_open == []


@needs_node
@pytest.mark.parametrize("stamp", [None, "http://127.0.0.1:1\n"], ids=["no-stamp", "other-api"])
def test_start_app_skip_build_refuses_a_build_it_cannot_vouch_for(tmp_path, stamp):
    # NEXT_PUBLIC_API_BASE_URL is inlined at build time: a build for another API is broken.
    root = _app_tree(tmp_path)
    (root / "apps/web/.next").mkdir()
    if stamp:
        (root / "apps/web/.next/api-base-url.txt").write_text(stamp, newline="\n")
    code, _, err, _, left_open = _start_app(tmp_path, "--smoke", env={"SKIP_BUILD": "1"})
    assert code == 1
    assert "SKIP_BUILD=1, but apps/web/.next was not built by this script for" in err
    assert not (tmp_path / "api.pid").exists(), "refused before starting anything"
    assert left_open == []


@needs_node
def test_start_app_skip_build_reuses_a_build_for_this_api(tmp_path):
    root = _app_tree(tmp_path)
    ports = _free_ports()
    (root / "apps/web/.next").mkdir()
    (root / "apps/web/.next/api-base-url.txt").write_text(
        f"http://127.0.0.1:{ports['API_PORT']}\n", newline="\n"
    )
    code, _, err, _, left_open = _start_app(
        tmp_path, "--smoke", ports=ports, env={"SKIP_BUILD": "1"}
    )
    assert code == 0, err
    assert not (tmp_path / "next.log").exists(), "SKIP_BUILD=1 must not build"
    assert left_open == []


# A TERM (systemd, docker stop, a supervisor) while both servers run.
_TERM_DRIVER = """\
"$(dirname "$0")/start_app.sh" >"$1/app.out" 2>"$1/app.err" &
app=$!
for _ in $(seq 300); do grep -q '^open ' "$1/app.out" 2>/dev/null && break; sleep 0.1; done
kill -TERM "$app"
wait "$app"
echo "exit $?"
"""


@needs_node
def test_start_app_on_term_stops_both_servers_and_exits_143(tmp_path):
    root = _app_tree(tmp_path)
    (root / "scripts/term_driver.sh").write_text(_TERM_DRIVER, newline="\n")
    code, out, err, _, left_open = _start_app(
        tmp_path, tmp_path.as_posix(), script="term_driver.sh"
    )
    assert code == 0, err
    assert "open http" in (tmp_path / "app.out").read_text(), (tmp_path / "app.err").read_text()
    assert out.strip() == "exit 143"
    assert left_open == []


# --- run.sh e2e targets ------------------------------------------------------------------------

_STUB_PNPM = '#!/usr/bin/env bash\necho "E2E_PROFILE=${E2E_PROFILE:-} args: $*"\n'


def _tool_dir() -> str:
    """The directory holding coreutils for the bash in use; PATH gets nothing else, so a stub
    that bash fails to pick up cannot fall through to the real pnpm and start Playwright."""
    assert BASH is not None
    if os.name == "nt":
        return str(Path(BASH).parents[1] / "usr" / "bin")
    dirname = shutil.which("dirname")
    assert dirname is not None
    return str(Path(dirname).parent)


@pytest.mark.parametrize(
    ("target", "args", "expected"),
    [
        # a profile left in the shell must not turn the fixture suite into a model run
        ("fixture-e2e", (), "E2E_PROFILE=fixture args: --dir apps/web e2e"),
        # bare real-model targets run eval_001 alone, so they do not rewrite fixture evidence
        ("lite-e2e", (), "E2E_PROFILE=lite-local args: --dir apps/web e2e -g eval_001"),
        ("full-e2e", (), "E2E_PROFILE=full-local args: --dir apps/web e2e -g eval_001"),
        (
            "lite-e2e",
            ("-g", "eval_005"),
            "E2E_PROFILE=lite-local args: --dir apps/web e2e -g eval_005",
        ),
    ],
)
def test_run_e2e_targets_pin_their_profile_and_scope(tmp_path, target, args, expected):
    root = script_tree(tmp_path / "repo", "run.sh", "_python.sh")
    stubs = tmp_path / "bin"
    stubs.mkdir()
    (stubs / "pnpm").write_text(_STUB_PNPM, newline="\n")
    (stubs / "pnpm").chmod(0o755)
    done = run_script(
        root / "scripts" / "run.sh",
        tmp_path,
        target,
        *args,
        env={"PATH": f"{stubs}{os.pathsep}{_tool_dir()}", "E2E_PROFILE": "from-the-shell"},
    )
    assert done.returncode == 0, done.stderr
    assert done.stdout.strip() == expected
