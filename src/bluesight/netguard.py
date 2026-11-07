"""Network guard: counts (and by default blocks) every outbound network connection made while it is active.

BlueSight never needs the internet after the one-time model download. During every pipeline run this guard patches
``socket.socket.connect`` / ``connect_ex`` and ``socket.getaddrinfo`` (DNS) so that

* connections to this computer (127.0.0.0/8, ::1, ``localhost``, Unix sockets) are allowed, and
* anything else is recorded and, in ``block`` mode, refused with ``ConnectionRefusedError``.

The count is written into each run's report and shown on the app's Model & privacy page. It is a lightweight
in-process guard: it sees every connection made by Python code in this process (including libraries such as
huggingface_hub, requests, urllib3 and httpx, which all go through ``socket``). It does not see other programs.
"""
from __future__ import annotations

import ipaddress
import socket
import threading
import traceback
from dataclasses import dataclass, field
from typing import Any

_LOCAL_NAMES = {"localhost", "localhost.localdomain", "ip6-localhost", ""}
_lock = threading.RLock()
_active: list["NetworkGuard"] = []
_orig: dict[str, Any] = {}


def is_local(host: Any) -> bool:
    """True for loopback addresses, 'localhost' and Unix-socket paths."""
    if host is None:
        return True
    if isinstance(host, (bytes, bytearray)):
        host = host.decode(errors="ignore")
    h = str(host).strip("[]").lower()
    if h in _LOCAL_NAMES:
        return True
    try:
        ip = ipaddress.ip_address(h.split("%")[0])
        return ip.is_loopback or ip.is_unspecified
    except ValueError:
        return False


@dataclass
class Attempt:
    kind: str      # "connect" | "dns"
    host: str
    port: int | None
    blocked: bool
    where: str     # innermost non-library frame, for diagnosis


@dataclass
class NetworkGuard:
    """Context manager. ``mode`` = "block" (refuse non-local connections) or "count" (record only)."""

    mode: str = "block"
    attempts: list[Attempt] = field(default_factory=list)
    local_connections: int = 0

    # ---------------------------------------------------------------- patching
    def __enter__(self) -> "NetworkGuard":
        with _lock:
            if not _active:
                _install()
            _active.append(self)
        return self

    def __exit__(self, *exc) -> None:
        with _lock:
            if self in _active:
                _active.remove(self)
            if not _active:
                _uninstall()

    # ---------------------------------------------------------------- results
    @property
    def external_attempts(self) -> int:
        return len(self.attempts)

    def summary(self) -> dict[str, Any]:
        return {"mode": self.mode, "external_connection_attempts": self.external_attempts,
                "blocked": sum(a.blocked for a in self.attempts), "local_connections": self.local_connections,
                "attempts": [a.__dict__ for a in self.attempts[:20]],
                "how": "in-process guard on socket.connect/connect_ex/getaddrinfo (bluesight/netguard.py)"}


def _where() -> str:
    for fr in reversed(traceback.extract_stack()[:-3]):
        if "netguard" not in fr.filename:
            return f"{fr.filename.split('site-packages/')[-1]}:{fr.lineno}"
    return "?"


def _record(kind: str, host: Any, port: Any) -> bool:
    """Record an external attempt on every active guard. Returns True if it must be blocked."""
    block = any(g.mode == "block" for g in _active)
    a = Attempt(kind, str(host), int(port) if isinstance(port, int) else None, block, _where())
    for g in _active:
        g.attempts.append(a)
    return block


def _addr_host_port(address: Any) -> tuple[Any, Any]:
    if isinstance(address, tuple) and address:
        return address[0], (address[1] if len(address) > 1 else None)
    return None, None  # AF_UNIX path or unknown -> local


def _install() -> None:
    _orig["connect"] = socket.socket.connect
    _orig["connect_ex"] = socket.socket.connect_ex
    _orig["getaddrinfo"] = socket.getaddrinfo

    def connect(self, address):  # noqa: ANN001
        host, port = _addr_host_port(address)
        if self.family == getattr(socket, "AF_UNIX", -1) or is_local(host):
            for g in _active:
                g.local_connections += 1
            return _orig["connect"](self, address)
        if _record("connect", host, port):
            raise ConnectionRefusedError(f"BlueSight network guard blocked an outbound connection to {host}:{port}")
        return _orig["connect"](self, address)

    def connect_ex(self, address):  # noqa: ANN001
        host, port = _addr_host_port(address)
        if self.family == getattr(socket, "AF_UNIX", -1) or is_local(host):
            for g in _active:
                g.local_connections += 1
            return _orig["connect_ex"](self, address)
        if _record("connect", host, port):
            return 111  # ECONNREFUSED
        return _orig["connect_ex"](self, address)

    def getaddrinfo(host, port, *a, **k):  # noqa: ANN001
        if not is_local(host) and _record("dns", host, port):
            raise socket.gaierror(socket.EAI_NONAME, f"BlueSight network guard blocked a DNS lookup of {host}")
        return _orig["getaddrinfo"](host, port, *a, **k)

    socket.socket.connect = connect
    socket.socket.connect_ex = connect_ex
    socket.getaddrinfo = getaddrinfo


def _uninstall() -> None:
    if _orig:
        socket.socket.connect = _orig.pop("connect")
        socket.socket.connect_ex = _orig.pop("connect_ex")
        socket.getaddrinfo = _orig.pop("getaddrinfo")
