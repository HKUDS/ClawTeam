"""Lightweight HTTP server for the Web UI dashboard (stdlib only)."""

from __future__ import annotations

import json
import threading
import time
import urllib.request
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from clawteam.board.collector import BoardCollector

_STATIC_DIR = Path(__file__).parent / "static"


@dataclass
class TeamSnapshotCache:
    """Tiny TTL cache for full team snapshots shared across HTTP handlers."""

    ttl_seconds: float
    _entries: dict[str, tuple[float, dict]] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def get(self, team_name: str, loader) -> dict:
        with self._lock:
            entry = self._entries.get(team_name)
            if entry and time.monotonic() - entry[0] < self.ttl_seconds:
                return entry[1]

        # Load outside the lock so one slow collector run does not block all
        # other readers. Concurrent expiry can trigger duplicate refreshes, but
        # this path only rebuilds an in-memory snapshot and the latest result wins.
        data = loader()
        loaded_at = time.monotonic()
        with self._lock:
            self._entries[team_name] = (loaded_at, data)
        return data


class BoardHandler(BaseHTTPRequestHandler):
    """HTTP handler for the board Web UI."""

    collector: BoardCollector
    default_team: str = ""
    interval: float = 2.0
    team_cache: TeamSnapshotCache

    def do_GET(self):
        path = self.path.split("?")[0]

        if path == "/" or path == "/index.html":
            self._serve_static("index.html", "text/html")
        elif path == "/api/overview":
            self._serve_json(self.collector.collect_overview())
        elif path.startswith("/api/team/"):
            team_name = path[len("/api/team/"):].strip("/")
            if not team_name:
                self.send_error(400, "Team name required")
                return
            self._serve_team(team_name)
        elif path.startswith("/api/events/"):
            team_name = path[len("/api/events/"):].strip("/")
            if not team_name:
                self.send_error(400, "Team name required")
                return
            self._serve_sse(team_name)
        elif path.startswith("/api/proxy"):
            query = parse_qs(urlparse(self.path).query)
            target_url = query.get("url", [""])[0]
            if not target_url:
                self.send_error(400, "URL required")
                return
            try:
                # If github URL, convert to api.github.com/repos/.../readme
                if "github.com" in target_url and "raw.githubusercontent.com" not in target_url:
                    parsed = urlparse(target_url)
                    parts = [p for p in parsed.path.split("/") if p]
                    if len(parts) == 2:
                        api_url = f"https://api.github.com/repos/{parts[0]}/{parts[1]}/readme"
                        req = urllib.request.Request(api_url, headers={"User-Agent": "ClawTeam-Server"})
                        with urllib.request.urlopen(req) as resp:
                            data = json.loads(resp.read().decode())
                            target_url = data.get("download_url", target_url)
                    else:
                        target_url = target_url.replace("github.com", "raw.githubusercontent.com").replace("/blob/", "/")

                req = urllib.request.Request(target_url, headers={"User-Agent": "ClawTeam-Server"})
                with urllib.request.urlopen(req) as resp:
                    content = resp.read()
                    self.send_response(200)
                    self.send_header("Content-Type", "text/plain; charset=utf-8")
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.end_headers()
                    self.wfile.write(content)
            except Exception as e:
                self.send_error(500, str(e))
        else:
            self.send_error(404)

    def do_POST(self):
        path = self.path.split("?")[0]
        if path.startswith("/api/team/") and path.endswith("/task"):
            parts = path.strip("/").split("/")
            if len(parts) == 4 and parts[3] == "task":
                team_name = unquote(parts[2])
                if not team_name:
                    self.send_error(404)
                    return
                content_length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(content_length).decode("utf-8")
                try:
                    payload = json.loads(body)
                    from clawteam.team.tasks import TaskStore
                    store = TaskStore(team_name)
                    task = store.create(
                        subject=payload.get("subject", ""),
                        description=payload.get("description", ""),
                        owner=payload.get("owner", "")
                    )
                    self._serve_json({"status": "ok", "task_id": task.id})
                except Exception as e:
                    self.send_error(400, str(e))
                return
        self.send_error(404)

    def _serve_static(self, filename: str, content_type: str):
        filepath = _STATIC_DIR / filename
        if not filepath.exists():
            self.send_error(404, f"Static file not found: {filename}")
            return
        content = filepath.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def _serve_json(self, data):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _serve_team(self, team_name: str):
        try:
            data = self.collector.collect_team(team_name)
            self._serve_json(data)
        except ValueError as e:
            body = json.dumps({"error": str(e)}).encode("utf-8")
            self.send_response(404)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    def _serve_sse(self, team_name: str):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        try:
            while True:
                try:
                    data = self.team_cache.get(
                        team_name,
                        lambda: self.collector.collect_team(team_name),
                    )
                except ValueError as e:
                    data = {"error": str(e)}
                payload = json.dumps(data, ensure_ascii=False)
                self.wfile.write(f"data: {payload}\n\n".encode("utf-8"))
                self.wfile.flush()
                time.sleep(self.interval)
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass

    def log_message(self, format, *args):
        # Suppress default stderr logging for SSE connections
        first = str(args[0]) if args else ""
        if "/api/events/" not in first:
            super().log_message(format, *args)


def serve(
    host: str = "127.0.0.1",
    port: int = 8080,
    default_team: str = "",
    interval: float = 2.0,
):
    """Start the Web UI server."""
    collector = BoardCollector()
    BoardHandler.collector = collector
    BoardHandler.default_team = default_team
    BoardHandler.interval = interval
    BoardHandler.team_cache = TeamSnapshotCache(ttl_seconds=interval)

    server = ThreadingHTTPServer((host, port), BoardHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
