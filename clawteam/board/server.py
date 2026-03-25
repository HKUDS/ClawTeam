"""Lightweight HTTP server for the Web UI dashboard (stdlib only)."""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

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

    # Performance monitoring stats
    _total_requests: int = 0
    _active_connections: int = 0
    _stats_lock: threading.Lock = threading.Lock()

    def handle(self):
        """Handle a single HTTP request with performance tracking."""
        self._start_time = time.monotonic()
        with self._stats_lock:
            BoardHandler._active_connections += 1
            BoardHandler._total_requests += 1
        try:
            super().handle()
        finally:
            with self._stats_lock:
                BoardHandler._active_connections -= 1

    def do_GET(self):
        path = self.path.split("?")[0]

        if path == "/" or path == "/index.html":
            self._serve_static("index.html", "text/html")
        elif path == "/api/overview":
            self._serve_json(self.collector.collect_overview())
        elif path == "/api/stats":
            self._serve_stats()
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
        else:
            self.send_error(404)

    def do_POST(self):
        path = self.path.split("?")[0]

        if path == "/api/teams":
            self._handle_create_team()
        elif path.startswith("/api/teams/") and path.endswith("/tasks"):
            team_name = path[len("/api/teams/"): -len("/tasks")].strip("/")
            self._handle_create_task(team_name)
        elif path.startswith("/api/teams/") and path.endswith("/messages"):
            team_name = path[len("/api/teams/"): -len("/messages")].strip("/")
            self._handle_send_message(team_name)
        else:
            self.send_error(404)

    def do_PATCH(self):
        path = self.path.split("?")[0]

        # /api/teams/{team_name}/tasks/{task_id}
        if path.startswith("/api/teams/"):
            parts = path[len("/api/teams/"):].strip("/").split("/")
            if len(parts) == 3 and parts[1] == "tasks":
                team_name, _, task_id = parts
                self._handle_update_task(team_name, task_id)
                return

        self.send_error(404)

    def do_DELETE(self):
        path = self.path.split("?")[0]

        if path.startswith("/api/teams/"):
            team_name = path[len("/api/teams/"):].strip("/")
            if team_name:
                self._handle_cleanup_team(team_name)
                return

        self.send_error(404)

    def _get_json_body(self):
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            if content_length == 0:
                return {}
            body = self.rfile.read(content_length)
            return json.loads(body.decode("utf-8"))
        except Exception:
            return {}

    def _handle_create_team(self):
        from clawteam.identity import AgentIdentity
        from clawteam.team.manager import TeamManager

        body = self._get_json_body()
        name = body.get("name")
        if not name:
            self.send_error(400, "Team name required")
            return

        description = body.get("description", "")
        identity = AgentIdentity.from_env()

        try:
            TeamManager.create_team(
                name=name,
                leader_name=body.get("leaderName") or identity.agent_name,
                leader_id=body.get("leaderId") or identity.agent_id,
                description=description,
                user=identity.user,
            )
            self._serve_json({"status": "created", "name": name})
        except ValueError as e:
            self._serve_error(400, str(e))

    def _handle_create_task(self, team_name: str):
        from clawteam.team.models import TaskPriority
        from clawteam.team.tasks import TaskStore

        body = self._get_json_body()
        subject = body.get("subject")
        if not subject:
            self.send_error(400, "Task subject required")
            return

        try:
            store = TaskStore(team_name)
            task = store.create(
                subject=subject,
                description=body.get("description", ""),
                owner=body.get("owner", ""),
                priority=TaskPriority(body.get("priority", "medium")),
                blocks=body.get("blocks", []),
                blocked_by=body.get("blockedBy", []),
            )
            self._serve_json(json.loads(task.model_dump_json(by_alias=True, exclude_none=True)))
        except Exception as e:
            self._serve_error(400, str(e))

    def _handle_update_task(self, team_name: str, task_id: str):
        from clawteam.identity import AgentIdentity
        from clawteam.team.models import TaskPriority, TaskStatus
        from clawteam.team.tasks import TaskStore

        body = self._get_json_body()
        try:
            store = TaskStore(team_name)
            caller = body.get("caller") or AgentIdentity.from_env().agent_name

            status = body.get("status")
            priority = body.get("priority")

            task = store.update(
                task_id,
                status=TaskStatus(status) if status else None,
                owner=body.get("owner"),
                subject=body.get("subject"),
                description=body.get("description"),
                priority=TaskPriority(priority) if priority else None,
                add_blocks=body.get("addBlocks"),
                add_blocked_by=body.get("addBlockedBy"),
                caller=caller,
                force=body.get("force", False),
            )
            if not task:
                self.send_error(404, "Task not found")
                return
            self._serve_json(json.loads(task.model_dump_json(by_alias=True, exclude_none=True)))
        except Exception as e:
            self._serve_error(400, str(e))

    def _handle_send_message(self, team_name: str):
        from clawteam.identity import AgentIdentity
        from clawteam.team.mailbox import MailboxManager
        from clawteam.team.models import MessageType

        body = self._get_json_body()
        to = body.get("to")
        content = body.get("content")
        if not content:
            self.send_error(400, "Message content required")
            return

        try:
            sender = body.get("from") or AgentIdentity.from_env().agent_name
            mailbox = MailboxManager(team_name)
            msg_type = MessageType(body.get("type", "broadcast" if not to else "message"))

            if not to or msg_type == MessageType.broadcast:
                msgs = mailbox.broadcast(
                    from_agent=sender,
                    content=content,
                    msg_type=msg_type,
                    key=body.get("key"),
                )
                self._serve_json({"status": "sent", "count": len(msgs)})
            else:
                msg = mailbox.send(
                    from_agent=sender,
                    to=to,
                    content=content,
                    msg_type=msg_type,
                    key=body.get("key"),
                )
                self._serve_json(json.loads(msg.model_dump_json(by_alias=True, exclude_none=True)))
        except Exception as e:
            self._serve_error(400, str(e))

    def _handle_cleanup_team(self, team_name: str):
        from clawteam.team.manager import TeamManager

        try:
            if TeamManager.cleanup(team_name):
                self._serve_json({"status": "deleted", "name": team_name})
            else:
                self.send_error(404, "Team not found")
        except Exception as e:
            self._serve_error(400, str(e))

    def _serve_error(self, code: int, message: str):
        body = json.dumps({"error": message}).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_stats(self):
        """Serve internal performance stats as JSON."""
        with self._stats_lock:
            stats = {
                "active_connections": self._active_connections,
                "total_requests": self._total_requests,
                "uptime_seconds": time.monotonic() - getattr(self.server, "_started_at", time.monotonic()),
            }
        self._serve_json(stats)

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

    def log_request(self, code="-", size="-"):
        """Override to include duration in logs."""
        duration = time.monotonic() - getattr(self, "_start_time", time.monotonic())
        self.log_message('"%s" %s %s [%.4fs]', self.requestline, str(code), str(size), duration)


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
    server._started_at = time.monotonic()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
