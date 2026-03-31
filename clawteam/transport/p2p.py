"""ZeroMQ PUSH/PULL transport with file-based fallback for offline agents."""

from __future__ import annotations

import collections
import json
import os
import socket
import threading
import time
import uuid
from pathlib import Path

from clawteam.fileutil import atomic_write_text
from clawteam.paths import ensure_within_root, validate_identifier
from clawteam.team.models import get_data_dir
from clawteam.transport.base import Transport
from clawteam.transport.claimed import ClaimedMessage
from clawteam.transport.file import FileTransport


def _peers_dir(team_name: str) -> Path:
    d = ensure_within_root(get_data_dir() / "teams", validate_identifier(team_name, "team name"), "peers")
    d.mkdir(parents=True, exist_ok=True)
    return d


class P2PTransport(Transport):
    """ZeroMQ PUSH/PULL + FileTransport offline fallback.

    - PULL socket: listens for incoming messages (bound if bind_agent is set)
    - PUSH socket: sends messages to other agents (connects to their PULL port)
    - Peer discovery: via shared filesystem peers/{agent}.json
    - Offline fallback: if peer is unreachable, messages go through FileTransport
    """

    _peer_heartbeat_interval_s = 1.0
    _peer_lease_ms = 5000

    def __init__(self, team_name: str, bind_agent: str | None = None):
        validate_identifier(team_name, "team name")
        validate_identifier(bind_agent or "", "agent name", allow_empty=True)
        self.team_name = team_name
        self._bind_agent = bind_agent
        self._file_fallback = FileTransport(team_name)
        self._ctx = None
        self._pull = None
        self._push_cache: dict[str, object] = {}
        self._peek_buffer: collections.deque = collections.deque()
        self._port: int | None = None
        self._heartbeat_stop = threading.Event()
        self._heartbeat_thread: threading.Thread | None = None
        if bind_agent:
            self._start_listener()

    def _start_listener(self) -> None:
        """Bind a PULL socket and register this peer."""
        import zmq

        self._ctx = zmq.Context()
        self._pull = self._ctx.socket(zmq.PULL)
        self._port = self._pull.bind_to_random_port("tcp://*")
        self._register_peer()
        self._start_peer_heartbeat()

    @staticmethod
    def _now_ms() -> int:
        return int(time.time() * 1000)

    @staticmethod
    def _as_int(value: object) -> int | None:
        if isinstance(value, bool):
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _is_local_host(host: str) -> bool:
        return host in {
            socket.gethostname(),
            socket.getfqdn(),
            "localhost",
            "127.0.0.1",
            "::1",
        }

    def _lease_is_fresh(self, info: dict[str, object]) -> bool | None:
        lease_expires_at_ms = self._as_int(info.get("leaseExpiresAtMs"))
        if lease_expires_at_ms is not None:
            return lease_expires_at_ms >= self._now_ms()

        heartbeat_at_ms = self._as_int(info.get("heartbeatAtMs"))
        lease_duration_ms = self._as_int(info.get("leaseDurationMs"))
        if heartbeat_at_ms is None or lease_duration_ms is None:
            return None
        return heartbeat_at_ms + lease_duration_ms >= self._now_ms()

    def _peer_info(self) -> dict[str, object]:
        now_ms = self._now_ms()
        return {
            "host": socket.gethostname(),
            "port": self._port,
            "pid": os.getpid(),
            "heartbeatAtMs": now_ms,
            "leaseDurationMs": self._peer_lease_ms,
            "leaseExpiresAtMs": now_ms + self._peer_lease_ms,
        }

    def _start_peer_heartbeat(self) -> None:
        if self._heartbeat_thread and self._heartbeat_thread.is_alive():
            return
        self._heartbeat_stop.clear()
        self._heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop,
            name=f"clawteam-p2p-heartbeat-{self.team_name}-{self._bind_agent}",
            daemon=True,
        )
        self._heartbeat_thread.start()

    def _heartbeat_loop(self) -> None:
        while not self._heartbeat_stop.wait(self._peer_heartbeat_interval_s):
            try:
                self._register_peer()
            except Exception:
                continue

    def _register_peer(self) -> None:
        """Write peers/{agent}.json with host/port/pid plus lease metadata."""
        if not self._bind_agent or self._port is None:
            return
        peer_file = _peers_dir(self.team_name) / f"{self._bind_agent}.json"
        atomic_write_text(peer_file, json.dumps(self._peer_info()))

    def _deregister_peer(self) -> None:
        """Remove peers/{agent}.json."""
        if not self._bind_agent:
            return
        peer_file = _peers_dir(self.team_name) / f"{self._bind_agent}.json"
        try:
            peer_file.unlink(missing_ok=True)
        except OSError:
            pass

    def _get_peer_addr(self, recipient: str) -> str | None:
        """Read peers/{recipient}.json and return tcp://host:port if alive."""
        peer_file = _peers_dir(self.team_name) / f"{recipient}.json"
        if not peer_file.exists():
            return None
        try:
            info = json.loads(peer_file.read_text(encoding="utf-8"))
            host = str(info["host"])
            pid = self._as_int(info.get("pid"))
            lease_is_fresh = self._lease_is_fresh(info)
            is_local_host = self._is_local_host(host)
            if is_local_host and pid:
                # Same-host peers can still be trusted via PID liveness even if
                # the lease heartbeat is delayed briefly.
                if self._pid_alive(pid):
                    return f"tcp://{host}:{info['port']}"
                try:
                    peer_file.unlink(missing_ok=True)
                except OSError:
                    pass
                return None
            if lease_is_fresh is False:
                # Remote peers rely on lease freshness because their PIDs are not
                # meaningful on this machine.
                try:
                    peer_file.unlink(missing_ok=True)
                except OSError:
                    pass
                return None
            if lease_is_fresh is None and not is_local_host:
                # Remote peers need lease metadata because the local PID table is meaningless.
                return None
            port = info["port"]
            return f"tcp://{host}:{port}"
        except Exception:
            return None

    @staticmethod
    def _pid_alive(pid: int) -> bool:
        """Check if a process with the given PID is still running."""
        try:
            os.kill(pid, 0)
            return True
        except (OSError, ProcessLookupError):
            return False

    def _get_or_create_push(self, addr: str):
        """Get or create a cached PUSH socket for the given address."""
        import zmq

        if addr in self._push_cache:
            return self._push_cache[addr]
        if self._ctx is None:
            self._ctx = zmq.Context()
        sock = self._ctx.socket(zmq.PUSH)
        sock.setsockopt(zmq.SNDTIMEO, 1000)  # 1s send timeout
        sock.setsockopt(zmq.LINGER, 0)
        sock.connect(addr)
        self._push_cache[addr] = sock
        return sock

    def deliver(self, recipient: str, data: bytes) -> None:
        addr = self._get_peer_addr(recipient)
        if addr:
            try:
                import zmq

                sock = self._get_or_create_push(addr)
                sock.send(data, zmq.NOBLOCK)
                return
            except Exception:
                pass
        # Peer unreachable — fall back to file
        self._file_fallback.deliver(recipient, data)

    def claim_messages(self, agent_name: str, limit: int = 10) -> list[ClaimedMessage]:
        claimed: list[ClaimedMessage] = []

        while self._peek_buffer and len(claimed) < limit:
            data = self._peek_buffer.popleft()
            claimed.append(
                ClaimedMessage(
                    data=data,
                    ack=lambda: None,
                    quarantine=lambda error, payload=data: self._file_fallback._quarantine_bytes(
                        agent_name,
                        payload,
                        error,
                        source_name=f"p2p-{uuid.uuid4().hex[:8]}.json",
                    ),
                )
            )

        if self._pull:
            import zmq

            while len(claimed) < limit:
                try:
                    data = self._pull.recv(zmq.NOBLOCK)
                    claimed.append(
                        ClaimedMessage(
                            data=data,
                            ack=lambda: None,
                            quarantine=lambda error, payload=data: self._file_fallback._quarantine_bytes(
                                agent_name,
                                payload,
                                error,
                                source_name=f"p2p-{uuid.uuid4().hex[:8]}.json",
                            ),
                        )
                    )
                except zmq.Again:
                    break

        remaining = limit - len(claimed)
        if remaining > 0:
            claimed.extend(self._file_fallback.claim_messages(agent_name, remaining))
        return claimed

    def fetch(self, agent_name: str, limit: int = 10, consume: bool = True) -> list[bytes]:
        if consume:
            messages: list[bytes] = []
            for claimed in self.claim_messages(agent_name, limit):
                messages.append(claimed.data)
                claimed.ack()
            return messages

        messages: list[bytes] = []
        # 1. Drain ZMQ PULL socket (non-blocking)
        if self._pull:
            import zmq

            while len(messages) < limit:
                try:
                    data = self._pull.recv(zmq.NOBLOCK)
                    self._peek_buffer.append(data)
                    messages.append(data)
                except zmq.Again:
                    break

        # 2. File fallback for remaining
        remaining = limit - len(messages)
        if remaining > 0:
            messages.extend(self._file_fallback.fetch(agent_name, remaining, consume))
        return messages[:limit]

    def count(self, agent_name: str) -> int:
        # ZMQ has no queue-depth query; return file count + peek buffer size
        return self._file_fallback.count(agent_name) + len(self._peek_buffer)

    def list_recipients(self) -> list[str]:
        # Union of peers/ directory and inboxes/ directory
        peers: set[str] = set()
        peers_dir = _peers_dir(self.team_name)
        for f in peers_dir.glob("*.json"):
            peers.add(f.stem)
        peers.update(self._file_fallback.list_recipients())
        return list(peers)

    def close(self) -> None:
        self._heartbeat_stop.set()
        if self._heartbeat_thread:
            self._heartbeat_thread.join(timeout=self._peer_heartbeat_interval_s + 0.1)
            self._heartbeat_thread = None
        self._deregister_peer()
        for sock in self._push_cache.values():
            try:
                sock.close()
            except Exception:
                pass
        self._push_cache.clear()
        if self._pull:
            try:
                self._pull.close()
            except Exception:
                pass
            self._pull = None
        if self._ctx:
            try:
                self._ctx.term()
            except Exception:
                pass
            self._ctx = None
