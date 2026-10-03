"""Runtime status of the local stack (``GET /api/runtime/status``).

One row per piece of the event-day stack, so the worker screen can say "checked on this
computer by the safety agent" and the judge view can show every part:

- ``nemoclaw``: the NemoClaw sandbox ``ambient-mirror``, phase from ``openshell sandbox
  list`` (``~/.local/bin`` on PATH, 3 s timeout, ANSI codes stripped);
- ``openclaw``: the OpenClaw agent ``urban-mirror``; ok when ``app.state.executor`` is the
  ``OpenClawAgentExecutor`` (value "agent"), else "dev harness";
- ``openshell``: the OpenShell gateway, a TCP connect to 127.0.0.1:8080;
- ``tool_server``: the agent's mirror MCP tool server, a TCP connect to 127.0.0.1:8090;
- ``qwen``: the local vLLM ``/health`` of the active profile's perception endpoint, value
  the profile's model id;
- ``detector``: the local YOLO detector ``/health`` (``$HAZARDS_DETECTOR_URL`` or
  127.0.0.1:8003);
- ``network``: "local only" when every configured address is loopback or the OpenShell
  bridge gateway 172.18.0.1.

The result is cached for 15 s. Probing never raises: a probe that errors reports status
"unknown". Rows carry no tokens, URLs or environment values.
"""

from __future__ import annotations

import os
import re
import shutil
import socket
import subprocess
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx

CACHE_TTL_S = 15.0
COMMAND_TIMEOUT_S = 3.0
HTTP_TIMEOUT_S = 2.0
TCP_TIMEOUT_S = 1.0
SANDBOX = "ambient-mirror"
AGENT_ID = "urban-mirror"
AGENT_EXECUTOR_CLASS = "OpenClawAgentExecutor"
GATEWAY_ADDR = ("127.0.0.1", 8080)
TOOL_SERVER_ADDR = ("127.0.0.1", 8090)
DETECTOR_URL_ENV = "HAZARDS_DETECTOR_URL"
DEFAULT_DETECTOR_URL = "http://127.0.0.1:8003"
DEFAULT_QWEN_URL = "http://127.0.0.1:8000/v1"
TOOLS_BIND_ENV = "AUM_TOOLS_BIND"
LOCAL_HOSTS = frozenset({"127.0.0.1", "localhost", "::1", "172.18.0.1"})
ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")

RunCommand = Callable[[Sequence[str], float, Mapping[str, str]], tuple[int, str]]
HttpGet = Callable[[str, float], tuple[int, Any]]
TcpCheck = Callable[[str, int, float], bool]
Which = Callable[[str, str], str | None]


def _which(name: str, path: str) -> str | None:
    return shutil.which(name, path=path)


def strip_ansi(text: str) -> str:
    return ANSI_RE.sub("", text)


def _run_command(args: Sequence[str], timeout: float, env: Mapping[str, str]) -> tuple[int, str]:
    done = subprocess.run(
        list(args), capture_output=True, text=True, timeout=timeout, env=dict(env), check=False
    )
    return done.returncode, done.stdout


def _http_get(url: str, timeout: float) -> tuple[int, Any]:
    with httpx.Client(timeout=timeout, trust_env=False) as client:
        response = client.get(url)
    try:
        body = response.json()
    except ValueError:
        body = None
    return response.status_code, body


def _tcp_open(host: str, port: int, timeout: float) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def row(key: str, label: str, status: str, value: str, detail: str = "") -> dict[str, str]:
    return {"key": key, "label": label, "status": status, "value": value, "detail": detail}


def sandbox_phase(output: str, sandbox: str = SANDBOX) -> str | None:
    """The PHASE column of ``sandbox`` in ``openshell sandbox list`` output, else None."""
    for line in strip_ansi(output).splitlines():
        parts = line.split()
        if parts and parts[0] == sandbox:
            return parts[-1] if len(parts) > 1 else None
    return None


def _host(url: str | None) -> str | None:
    if not url:
        return None
    try:
        return urlsplit(url).hostname
    except ValueError:
        return None


def health_url(base_url: str) -> str:
    """``http://127.0.0.1:8000/v1`` -> ``http://127.0.0.1:8000/health``."""
    base = base_url.rstrip("/")
    base = base.removesuffix("/v1")
    return f"{base}/health"


class RuntimeStatus:
    """Probes the local stack; ``status(app_state)`` returns the cached snapshot."""

    def __init__(
        self,
        *,
        profile: str,
        env: Mapping[str, str] | None = None,
        run_command: RunCommand | None = None,
        http_get: HttpGet | None = None,
        tcp_open: TcpCheck | None = None,
        which: Which | None = None,
        clock: Callable[[], float] = time.monotonic,
        ttl_s: float = CACHE_TTL_S,
    ) -> None:
        self.profile = profile
        self.env = dict(os.environ if env is None else env)
        self._run = run_command or _run_command
        self._get = http_get or _http_get
        self._tcp = tcp_open or _tcp_open
        self._which = which or _which
        self._clock = clock
        self.ttl_s = ttl_s
        self._lock = threading.Lock()
        self._cached: tuple[float, dict[str, Any]] | None = None

    # -- configuration ------------------------------------------------------------

    def _endpoints(self) -> dict[str, Any]:
        """The active profile's perception/reasoning endpoints (never raises)."""
        out: dict[str, Any] = {"backend": None, "model": None, "urls": []}
        try:
            from inference.profiles import load_profile

            profile = load_profile(self.profile, require_resolved=False, env=self.env)
        except Exception:  # noqa: BLE001 - status probing never raises
            return out
        out["backend"] = profile.perception.backend
        out["model"] = profile.perception.model
        out["perception_url"] = profile.perception.base_url
        out["urls"] = [u for u in (profile.perception.base_url, profile.reasoning.base_url) if u]
        return out

    def detector_url(self) -> str:
        return (self.env.get(DETECTOR_URL_ENV) or DEFAULT_DETECTOR_URL).rstrip("/")

    def _tool_hosts(self) -> list[str]:
        spec = self.env.get(TOOLS_BIND_ENV) or ""
        hosts = []
        for part in spec.split(","):
            host = part.strip().rsplit(":", 1)[0].strip("[]")
            if host:
                hosts.append(host)
        return hosts or [TOOL_SERVER_ADDR[0]]

    # -- probes ---------------------------------------------------------------------

    def probe_nemoclaw(self) -> dict[str, str]:
        label = "NemoClaw sandbox"
        path = os.pathsep.join(
            [str(Path.home() / ".local" / "bin"), self.env.get("PATH", os.defpath)]
        )
        binary = self._which("openshell", path)
        if binary is None:
            return row("nemoclaw", label, "unknown", "openshell not found", f"sandbox {SANDBOX}")
        try:
            code, out = self._run(
                [binary, "sandbox", "list"], COMMAND_TIMEOUT_S, {**self.env, "PATH": path}
            )
        except Exception:  # noqa: BLE001 - timeout, permission, ...
            return row("nemoclaw", label, "unknown", "no answer", f"sandbox {SANDBOX}")
        if code != 0:
            return row("nemoclaw", label, "unknown", "no answer", f"sandbox {SANDBOX}")
        phase = sandbox_phase(out)
        if phase is None:
            return row("nemoclaw", label, "down", "not found", f"sandbox {SANDBOX}")
        status = "ok" if phase.lower() == "ready" else "down"
        return row("nemoclaw", label, status, phase, f"sandbox {SANDBOX}")

    def probe_openclaw(self, app_state: Any) -> dict[str, str]:
        label = "OpenClaw agent"
        executor = getattr(app_state, "executor", None)
        runner = getattr(app_state, "hazard_review_runner_name", None) or "direct"
        detail = f"agent {AGENT_ID} · safety checks: {runner}"
        if executor is None:
            return row("openclaw", label, "unknown", "no executor", detail)
        if type(executor).__name__ == AGENT_EXECUTOR_CLASS:
            return row("openclaw", label, "ok", "agent", detail)
        return row("openclaw", label, "down", "dev harness", detail)

    def probe_tcp(self, key: str, label: str, addr: tuple[str, int]) -> dict[str, str]:
        detail = f"{addr[0]}:{addr[1]}"
        try:
            listening = self._tcp(addr[0], addr[1], TCP_TIMEOUT_S)
        except Exception:  # noqa: BLE001
            return row(key, label, "unknown", "no answer", detail)
        return row(
            key,
            label,
            "ok" if listening else "down",
            "listening" if listening else "not reachable",
            detail,
        )

    def probe_qwen(self, endpoints: Mapping[str, Any]) -> dict[str, str]:
        label = "Qwen (local AI)"
        model = str(endpoints.get("model") or "")
        if endpoints.get("backend") == "fixture":
            return row("qwen", label, "unknown", "fixture profile (no model)", self.profile)
        url = endpoints.get("perception_url") or DEFAULT_QWEN_URL
        detail = f"profile {self.profile}"
        try:
            code, _body = self._get(health_url(str(url)), HTTP_TIMEOUT_S)
        except Exception:  # noqa: BLE001
            return row("qwen", label, "down", model or "not reachable", detail)
        return row("qwen", label, "ok" if code == 200 else "down", model or "unknown model", detail)

    def probe_detector(self) -> dict[str, str]:
        label = "Detector"
        try:
            code, body = self._get(f"{self.detector_url()}/health", HTTP_TIMEOUT_S)
        except Exception:  # noqa: BLE001
            return row("detector", label, "down", "not reachable", "local YOLO")
        if code != 200 or not isinstance(body, dict):
            return row("detector", label, "down", "not ready", "local YOLO")
        models = body.get("models") if isinstance(body.get("models"), dict) else {}
        names = ", ".join(sorted(str(m) for m in models)) or "no models"
        device = str(body.get("device") or "")
        return row("detector", label, "ok" if body.get("ok") else "down", names, device)

    def probe_network(self, endpoints: Mapping[str, Any]) -> tuple[dict[str, str], bool]:
        urls = [*endpoints.get("urls", []), self.detector_url()]
        hosts = [_host(u) for u in urls]
        hosts += [GATEWAY_ADDR[0], *self._tool_hosts()]
        local = bool(hosts) and all(h in LOCAL_HOSTS for h in hosts if h is not None)
        local = local and all(h is not None for h in hosts)
        if local:
            return row("network", "Network", "ok", "local only", "no internet needed"), True
        return row(
            "network", "Network", "down", "not local", "an address leaves this computer"
        ), False

    # -- snapshot -----------------------------------------------------------------------

    def collect(self, app_state: Any) -> dict[str, Any]:
        endpoints = self._endpoints()
        with ThreadPoolExecutor(max_workers=4, thread_name_prefix="runtime-status") as pool:
            nemoclaw = pool.submit(self.probe_nemoclaw)
            gateway = pool.submit(self.probe_tcp, "openshell", "OpenShell gateway", GATEWAY_ADDR)
            tools = pool.submit(self.probe_tcp, "tool_server", "Tool server", TOOL_SERVER_ADDR)
            qwen = pool.submit(self.probe_qwen, endpoints)
            detector = pool.submit(self.probe_detector)
            rows = []
            for key, future in (
                ("nemoclaw", nemoclaw),
                ("openclaw", None),
                ("openshell", gateway),
                ("tool_server", tools),
                ("qwen", qwen),
                ("detector", detector),
            ):
                if future is None:
                    rows.append(self._safe(lambda: self.probe_openclaw(app_state), key))
                else:
                    rows.append(self._safe(future.result, key))
        network, local_only = self.probe_network(endpoints)
        rows.append(network)
        return {
            "checked_at": datetime.now(UTC).isoformat(),
            "local_only": local_only,
            "rows": rows,
        }

    @staticmethod
    def _safe(fn: Callable[[], dict[str, str]], key: str) -> dict[str, str]:
        try:
            return fn()
        except Exception:  # noqa: BLE001 - never raise from a status probe
            return row(key, key, "unknown", "no answer")

    def status(self, app_state: Any) -> dict[str, Any]:
        """The snapshot, re-probed at most every ``ttl_s`` seconds."""
        with self._lock:
            now = self._clock()
            if self._cached is not None and now - self._cached[0] < self.ttl_s:
                return self._cached[1]
            try:
                snapshot = self.collect(app_state)
            except Exception:  # noqa: BLE001
                snapshot = {
                    "checked_at": datetime.now(UTC).isoformat(),
                    "local_only": False,
                    "rows": [],
                }
            self._cached = (now, snapshot)
            return snapshot
