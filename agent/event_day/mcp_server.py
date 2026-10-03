"""The ``mirror`` MCP server: the seven contract tools for the OpenClaw agent (D01).

Written on event day (2026-10-03, task D01). OpenClaw's MCP client (the
``@modelcontextprotocol/sdk`` Streamable HTTP transport in OpenClaw 2026.7.1) talks to
this server. The server runs inside the host process that owns the run, so every call
reaches that run's ``AgentPolicy`` and its events reach the run's SSE stream.

* ``ToolGateway`` binds the server to at most one run at a time. A lease holds the run's
  ``AgentPolicy`` until the agent's turn has ended, so an old turn's late calls can never
  reach the next run. Without a lease every call is refused.
* ``McpServer`` serves exactly one path, ``POST /mcp``: JSON-RPC ``initialize``,
  ``ping``, ``tools/list`` and ``tools/call``. ``GET`` answers 405 (no server-initiated
  stream). Any other path is 404, so the server is no file server. It offers no
  resources and no prompts.
* With a token, every request needs ``Authorization: Bearer <token>``. A request with an
  ``Origin`` header outside ``allowed_origins`` is refused (DNS rebinding).

Replies never quote argument values. The request log holds method, path and status only.
"""

from __future__ import annotations

import hmac
import json
import logging
import secrets
import sys
import threading
from collections import OrderedDict
from collections.abc import Iterable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Self

from apps.api.services.gt_guard import GtGuard
from tools.session import TOOL_NAMES

from .policy import AgentPolicy
from .registration import MCP_PATH, SERVER_NAME, agent_reply, tool_specs

logger = logging.getLogger(__name__)

SERVER_VERSION = "2026.10.3"
PROTOCOL_VERSIONS = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")
DEFAULT_PROTOCOL = "2025-06-18"
MAX_BODY_BYTES = 1 << 20
MAX_SESSIONS = 64
INSTRUCTIONS = (
    "Ambient Urban Mirror run tools. Every reply is a JSON envelope: "
    '{"ok": true, "result": ...} or {"ok": false, "error": ..., "refused": ...}. '
    "Follow the run brief and AGENTS.md."
)
NO_RUN = (
    "refused by the tool surface: no run is active. These tools work only during a run "
    "the runner started; end your turn."
)
UNEXPECTED = "the tool failed unexpectedly ({}). Continue with the next playbook step, or submit."

# JSON-RPC error codes
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602


class GatewayBusyError(RuntimeError):
    """Another run still holds the tool surface (its agent turn has not ended)."""

    stage = "agent"


# -- run binding ----------------------------------------------------------------------


@dataclass
class Lease:
    """One run's hold on the tool surface. ``release`` is idempotent."""

    gateway: ToolGateway
    policy: AgentPolicy
    guard: GtGuard | None = None
    released: bool = field(default=False, init=False)

    @property
    def run_id(self) -> str | None:
        return self.policy.run_id

    def release(self) -> None:
        self.gateway._release(self)


class ToolGateway:
    """Routes MCP tool calls to the run that holds the lease, or refuses them."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._slot = threading.Lock()  # held from acquire to release
        self._lease: Lease | None = None

    @property
    def active_run_id(self) -> str | None:
        lease = self._lease
        return lease.run_id if lease is not None else None

    def acquire(
        self, policy: AgentPolicy, *, guard: GtGuard | None = None, timeout: float = 60.0
    ) -> Lease:
        """Bind the surface to ``policy``. Waits up to ``timeout`` for the previous lease."""
        if not self._slot.acquire(timeout=timeout):
            raise GatewayBusyError(
                "the previous agent turn still holds the tool surface; try again shortly"
            )
        lease = Lease(self, policy, guard)
        with self._lock:
            self._lease = lease
        return lease

    @contextmanager
    def bind(
        self, policy: AgentPolicy, *, guard: GtGuard | None = None, timeout: float = 60.0
    ) -> Iterator[Lease]:
        lease = self.acquire(policy, guard=guard, timeout=timeout)
        try:
            yield lease
        finally:
            lease.release()

    def _release(self, lease: Lease) -> None:
        with self._lock:
            if lease.released:
                return
            lease.released = True
            if self._lease is lease:
                self._lease = None
        self._slot.release()

    def call(self, tool: str, arguments: Any) -> dict[str, Any]:
        """Run contract tool ``tool`` for the active run; the agent-facing reply."""
        with self._lock:
            lease = self._lease
        if lease is None:
            return {"ok": False, "error": NO_RUN, "refused": True}
        try:
            outcome = lease.policy.call(tool, arguments).to_json()
        except Exception as exc:
            # The policy reports tool errors itself. Anything else must still answer the
            # call: a dropped connection makes OpenClaw back off the whole server.
            logger.warning("%s raised %s", tool, type(exc).__name__)
            logger.debug("tool failure detail", exc_info=True)
            return {"ok": False, "error": UNEXPECTED.format(type(exc).__name__), "refused": False}
        return agent_reply(tool, outcome, lease.guard)


# -- JSON-RPC -------------------------------------------------------------------------


def _error(msg_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}


def _result(msg_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": msg_id, "result": result}


def _negotiate(params: Any) -> str:
    requested = params.get("protocolVersion") if isinstance(params, dict) else None
    return requested if requested in PROTOCOL_VERSIONS else DEFAULT_PROTOCOL


def handle_message(gateway: ToolGateway, message: Any) -> dict[str, Any] | None:
    """One JSON-RPC message in, its response out (``None`` for a notification)."""
    if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
        return _error(None, INVALID_REQUEST, "not a JSON-RPC 2.0 message")
    method = message.get("method")
    if not isinstance(method, str):  # a response to a server request we never send
        return None
    if "id" not in message:  # notification: nothing to answer
        return None
    msg_id = message["id"]
    params = message.get("params") or {}
    if method == "initialize":
        return _result(
            msg_id,
            {
                "protocolVersion": _negotiate(params),
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": f"urban-{SERVER_NAME}-tools", "version": SERVER_VERSION},
                "instructions": INSTRUCTIONS,
            },
        )
    if method == "ping":
        return _result(msg_id, {})
    if method == "tools/list":
        return _result(msg_id, {"tools": tool_specs()})
    if method == "tools/call":
        if not isinstance(params, dict) or params.get("name") not in TOOL_NAMES:
            return _error(
                msg_id, INVALID_PARAMS, "unknown tool; tools are: " + ", ".join(TOOL_NAMES)
            )
        arguments = params.get("arguments")
        reply = gateway.call(params["name"], {} if arguments is None else arguments)
        return _result(
            msg_id,
            {
                "content": [{"type": "text", "text": json.dumps(reply, separators=(",", ":"))}],
                "isError": not reply.get("ok", False),
            },
        )
    return _error(msg_id, METHOD_NOT_FOUND, "method not found")


# -- HTTP -----------------------------------------------------------------------------


class _Sessions:
    """MCP session ids this server issued (bounded, oldest dropped first)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._ids: OrderedDict[str, None] = OrderedDict()

    def new(self) -> str:
        sid = secrets.token_hex(16)
        with self._lock:
            self._ids[sid] = None
            while len(self._ids) > MAX_SESSIONS:
                self._ids.popitem(last=False)
        return sid

    def known(self, sid: str) -> bool:
        with self._lock:
            return sid in self._ids

    def drop(self, sid: str) -> bool:
        with self._lock:
            if sid not in self._ids:
                return False
            del self._ids[sid]
            return True


class _Handler(BaseHTTPRequestHandler):
    server: _HttpServer
    protocol_version = "HTTP/1.1"
    server_version = "urban-mirror-tools"
    sys_version = ""

    # -- plumbing ---------------------------------------------------------------------

    def log_message(self, format: str, *args: Any) -> None:
        pass  # request lines can carry agent text; log_request below logs what is safe

    def log_request(self, code: int | str = "-", size: int | str = "-") -> None:
        logger.debug("%s %s -> %s", self.command, self.path.split("?", 1)[0], code)

    def version_string(self) -> str:
        return self.server_version

    def _send(self, status: int, body: Any = None, headers: dict[str, str] | None = None) -> None:
        data = b"" if body is None else json.dumps(body, separators=(",", ":")).encode()
        self.send_response(status)
        if body is not None:
            self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        if data:
            self.wfile.write(data)

    def _drain(self) -> bytes | None:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = -1
        if length < 0 or length > MAX_BODY_BYTES:
            self.close_connection = True
            return None
        return self.rfile.read(length) if length else b""

    def _admitted(self) -> bool:
        """Path, origin and token checks shared by every method."""
        cfg = self.server.config
        if self.path != MCP_PATH:
            self._drain()
            self._send(HTTPStatus.NOT_FOUND, {"error": "not found"})
            return False
        origin = self.headers.get("Origin")
        if origin is not None and origin not in cfg.allowed_origins:
            self._drain()
            self._send(HTTPStatus.FORBIDDEN, {"error": "origin not allowed"})
            return False
        if cfg.token is not None:
            given = self.headers.get("Authorization", "")
            expected = f"Bearer {cfg.token}"
            if not hmac.compare_digest(given.encode(), expected.encode()):
                self._drain()
                self._send(
                    HTTPStatus.UNAUTHORIZED,
                    {"error": "unauthorized"},
                    {"WWW-Authenticate": "Bearer"},
                )
                return False
        return True

    # -- methods ----------------------------------------------------------------------

    def do_GET(self) -> None:
        if self._admitted():
            self._send(
                HTTPStatus.METHOD_NOT_ALLOWED, {"error": "POST only"}, {"Allow": "POST, DELETE"}
            )

    def do_PUT(self) -> None:
        if self._admitted():
            self._drain()
            self._send(
                HTTPStatus.METHOD_NOT_ALLOWED, {"error": "POST only"}, {"Allow": "POST, DELETE"}
            )

    do_PATCH = do_PUT

    def do_DELETE(self) -> None:
        if not self._admitted():
            return
        sid = self.headers.get("Mcp-Session-Id", "")
        self._send(HTTPStatus.OK if self.server.sessions.drop(sid) else HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        if not self._admitted():
            return
        raw = self._drain()
        if raw is None:
            self._send(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {"error": "body too large"})
            return
        try:
            payload = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._send(HTTPStatus.BAD_REQUEST, _error(None, PARSE_ERROR, "parse error"))
            return
        messages = payload if isinstance(payload, list) else [payload]
        if not messages:
            self._send(HTTPStatus.BAD_REQUEST, _error(None, INVALID_REQUEST, "empty batch"))
            return

        headers: dict[str, str] = {}
        initializing = any(
            isinstance(m, dict) and m.get("method") == "initialize" for m in messages
        )
        if initializing:
            headers["Mcp-Session-Id"] = self.server.sessions.new()
        else:
            sid = self.headers.get("Mcp-Session-Id")
            if not sid:
                self._send(
                    HTTPStatus.BAD_REQUEST, _error(None, INVALID_REQUEST, "missing Mcp-Session-Id")
                )
                return
            if not self.server.sessions.known(sid):
                self._send(HTTPStatus.NOT_FOUND, _error(None, INVALID_REQUEST, "unknown session"))
                return

        responses = [r for r in (handle_message(self.server.gateway, m) for m in messages) if r]
        if not responses:
            self._send(HTTPStatus.ACCEPTED, None, headers)
            return
        body = responses if isinstance(payload, list) else responses[0]
        self._send(HTTPStatus.OK, body, headers)


@dataclass(frozen=True)
class ServerConfig:
    token: str | None = None
    allowed_origins: frozenset[str] = frozenset()


class _HttpServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(
        self,
        address: tuple[str, int],
        gateway: ToolGateway,
        sessions: _Sessions,
        config: ServerConfig,
    ) -> None:
        super().__init__(address, _Handler)
        self.gateway = gateway
        self.sessions = sessions
        self.config = config

    def handle_error(self, request: Any, client_address: Any) -> None:
        # Called from socketserver's except block. A client closing a keep-alive
        # connection is routine; anything else is logged without the request.
        logger.debug("mirror MCP connection error", exc_info=sys.exc_info())


class McpServer:
    """The ``mirror`` MCP server on one or more ``(host, port)`` addresses.

    The sandbox reaches the host on the OpenShell bridge gateway (``172.18.0.1``) while
    host-side checks use loopback, so each address gets its own listener over the same
    gateway and sessions. Port 0 picks a free port.
    """

    def __init__(
        self,
        gateway: ToolGateway,
        binds: Sequence[tuple[str, int]] = (("127.0.0.1", 0),),
        *,
        token: str | None = None,
        allowed_origins: Iterable[str] = (),
    ) -> None:
        if not binds:
            raise ValueError("at least one bind address is required")
        if token is not None and len(token) < 16:
            raise ValueError("the bearer token must be at least 16 characters")
        self.gateway = gateway
        self._binds = list(binds)
        self._config = ServerConfig(token, frozenset(allowed_origins))
        self._sessions = _Sessions()
        self._servers: list[_HttpServer] = []
        self._threads: list[threading.Thread] = []

    @property
    def addresses(self) -> list[tuple[str, int]]:
        """The bound ``(host, port)`` pairs (ports resolved once started)."""
        return [(s.server_address[0], s.server_address[1]) for s in self._servers]

    def url(self, index: int = 0) -> str:
        host, port = self.addresses[index]
        return f"http://{host}:{port}{MCP_PATH}"

    def start(self) -> Self:
        try:
            for host, port in self._binds:
                self._servers.append(
                    _HttpServer((host, port), self.gateway, self._sessions, self._config)
                )
        except OSError:
            self.close()
            raise
        for server in self._servers:
            thread = threading.Thread(
                target=server.serve_forever,
                kwargs={"poll_interval": 0.2},
                name=f"mcp:{server.server_address[0]}:{server.server_address[1]}",
                daemon=True,
            )
            thread.start()
            self._threads.append(thread)
        logger.info("mirror MCP server on %s", ", ".join(f"{h}:{p}" for h, p in self.addresses))
        return self

    def close(self) -> None:
        for server in self._servers:
            if self._threads:
                server.shutdown()
            server.server_close()
        for thread in self._threads:
            thread.join(timeout=5)
        self._servers.clear()
        self._threads.clear()

    def __enter__(self) -> Self:
        return self.start()

    def __exit__(self, *exc: object) -> None:
        self.close()


def parse_binds(spec: str, default_port: int) -> list[tuple[str, int]]:
    """``"127.0.0.1:8090,172.18.0.1:8090"`` (or bare hosts) as ``(host, port)`` pairs."""
    binds: list[tuple[str, int]] = []
    for part in (p.strip() for p in spec.split(",")):
        if not part:
            continue
        host, sep, port = part.rpartition(":")
        if not sep:
            host, port = part, str(default_port)
        binds.append((host, int(port)))
    if not binds:
        raise ValueError("no bind address given")
    return binds


__all__ = [
    "GatewayBusyError",
    "Lease",
    "McpServer",
    "ToolGateway",
    "handle_message",
    "parse_binds",
]
