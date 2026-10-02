"""P16: start_app.sh checks its ports and arguments before it starts anything."""

from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

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
