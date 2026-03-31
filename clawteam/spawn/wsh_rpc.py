"""JSON-RPC client for TideTerm server communication."""

from __future__ import annotations

import base64
import json
import socket
from pathlib import Path

MAX_RESPONSE_SIZE = 10 * 1024 * 1024


class WshRpcClient:
    """JSON-RPC client for TideTerm server communication.

    Communicates over Unix socket at ~/.local/share/tideterm/tideterm.sock
    """

    SOCKET_PATH = Path.home() / ".local/share/tideterm/tideterm.sock"
    _rpc_id = 0

    def __init__(self, socket_path: Path | None = None):
        self._socket_path = socket_path or self._resolve_socket_path()
        self._connected = False

    def _resolve_socket_path(self) -> Path:
        path = Path.home() / ".local/state/waveterm/tideterm.sock"
        if not path.exists():
            path = Path.home() / ".local/share/tideterm/tideterm.sock"
        return path

    def is_connected(self) -> bool:
        if not self._socket_path.exists():
            return False
        try:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.settimeout(1.0)
            sock.connect(str(self._socket_path))
            sock.close()
            self._connected = True
            return True
        except (socket.error, socket.timeout, OSError):
            self._connected = False
            return False

    def _send_request(self, method: str, params: dict) -> dict | None:
        if not self.is_connected():
            return None

        request = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
            "id": self._rpc_id,
        }
        self._rpc_id += 1

        try:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.settimeout(10.0)
            sock.connect(str(self._socket_path))
            sock.sendall(json.dumps(request).encode("utf-8"))

            response_data = b""
            while len(response_data) < MAX_RESPONSE_SIZE:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                response_data += chunk

            sock.close()

            if len(response_data) >= MAX_RESPONSE_SIZE:
                return None

            response = json.loads(response_data.decode("utf-8"))
            if "error" in response:
                return None
            return response.get("result")

        except (socket.error, socket.timeout, OSError, json.JSONDecodeError):
            return None

    def send_input(self, block_id: str, data: str, is_base64: bool = False) -> bool:
        params = {
            "blockid": block_id,
            "inputdata64": data if is_base64 else "",
        }
        if not is_base64:
            params["inputdata64"] = base64.b64encode(data.encode("utf-8")).decode("ascii")

        result = self._send_request("ControllerInputCommand", params)
        return result is not None

    def send_signal(self, block_id: str, signal: str) -> bool:
        params = {
            "blockid": block_id,
            "signame": signal,
        }
        result = self._send_request("ControllerInputCommand", params)
        return result is not None

    def get_block_info(self, block_id: str) -> dict | None:
        params = {"blockId": block_id}
        result = self._send_request("BlockInfoCommand", params)
        return result
