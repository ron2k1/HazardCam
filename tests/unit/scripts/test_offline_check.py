"""P16: the offline check's network guard refuses remote hosts and lets loopback through."""

from __future__ import annotations

import importlib.util
import socket

import httpx
import pytest

from apps.api.schemas import REPO_ROOT

_SPEC = importlib.util.spec_from_file_location(
    "offline_check", REPO_ROOT / "scripts" / "offline_check.py"
)
assert _SPEC is not None and _SPEC.loader is not None
offline_check = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(offline_check)


def test_a_remote_request_is_refused_and_recorded():
    with offline_check.loopback_only() as refused, pytest.raises(httpx.ConnectError):
        httpx.get("http://example.com/", timeout=2.0)
    assert refused == ["example.com"]


def test_a_remote_address_is_refused_without_dns():
    with offline_check.loopback_only() as refused:
        sock = socket.socket()
        with sock, pytest.raises(OSError, match="refused a connection to 192.0.2.1"):
            sock.connect(("192.0.2.1", 80))
    assert refused == ["192.0.2.1"]


def test_connect_ex_is_refused_too():
    with offline_check.loopback_only() as refused:
        sock = socket.socket()
        with sock:
            assert sock.connect_ex(("192.0.2.1", 80)) != 0
    assert refused == ["192.0.2.1"]


def test_loopback_still_connects_and_the_guard_is_removed_afterwards():
    real = (socket.socket.connect, socket.socket.connect_ex, socket.getaddrinfo)
    with socket.socket() as server:
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        with offline_check.loopback_only() as refused, socket.socket() as client:
            assert (socket.socket.connect, socket.getaddrinfo) != real[::2]  # guard is on
            client.connect(server.getsockname())
        assert refused == []
    assert (socket.socket.connect, socket.socket.connect_ex, socket.getaddrinfo) == real
