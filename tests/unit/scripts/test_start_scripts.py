"""P16: start_app.sh checks its ports and arguments before it starts anything; run.sh's e2e
targets pin their profile and scope.
"""

from __future__ import annotations

import os
import shutil
import threading
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
    root = script_tree(tmp_path / "repo", "start_app.sh", "_python.sh")
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
    root = script_tree(tmp_path / "repo", "start_app.sh", "_python.sh")
    done = run_script(root / "scripts" / "start_app.sh", tmp_path, "--bogus")
    assert done.returncode == 2
    assert "usage: scripts/start_app.sh [--smoke]" in done.stderr


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
