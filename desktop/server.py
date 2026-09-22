"""Zero-dependency local backend for the UpAgent desktop UI.

HTTP APIs served by stdlib ThreadingHTTPServer:

- ``GET  /api/status``    provider + workspace info
- ``POST /api/workspace`` switch the workspace directory
- ``GET  /api/tree``      one directory level of the workspace (lazy tree)
- ``GET  /api/file``      read a text file inside the workspace
- ``PUT  /api/file``      write a text file inside the workspace
- ``POST /api/chat``      start an agent run for a goal
- ``GET  /api/events``    SSE stream of chat events for a run
"""

from __future__ import annotations

import json
import os
import queue
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

_IGNORED_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    "dist",
    "build",
}
_MAX_DIR_ENTRIES = 500
_MAX_FILE_BYTES = 4 * 1024 * 1024


@dataclass(frozen=True)
class ChatEvent:
    """One event shown in the chat panel."""

    kind: str  # user | system | step | task | review | done | error
    text: str
    run_id: int
    ts: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, object]:
        return {"kind": self.kind, "text": self.text, "run_id": self.run_id, "ts": self.ts}


class ChatBroker:
    """Per-run event queues consumed by SSE subscribers."""

    def __init__(self) -> None:
        self._queues: dict[int, queue.Queue[ChatEvent | None]] = {}
        self._lock = threading.Lock()

    def start_run(self, run_id: int) -> None:
        with self._lock:
            self._queues[run_id] = queue.Queue()

    def emit(self, run_id: int, kind: str, text: str) -> None:
        with self._lock:
            target = self._queues.get(run_id)
        if target is not None:
            target.put(ChatEvent(kind=kind, text=text, run_id=run_id))

    def close(self, run_id: int) -> None:
        with self._lock:
            target = self._queues.get(run_id)
        if target is not None:
            target.put(None)

    def subscribe(self, run_id: int) -> queue.Queue[ChatEvent | None]:
        with self._lock:
            if run_id not in self._queues:
                self._queues[run_id] = queue.Queue()
            return self._queues[run_id]


class DesktopApp:
    """Application state shared by HTTP handlers and the chat runner."""

    def __init__(
        self,
        workspace: Path,
        *,
        provider_factory: Callable[[], object],
        status_provider: Callable[[], dict[str, object]],
    ) -> None:
        self.workspace = workspace.resolve()
        self.broker = ChatBroker()
        self._provider_factory = provider_factory
        self._status_provider = status_provider
        self._run_counter = 0
        self._run_lock = threading.Lock()
        self._active_run: int | None = None

    # -- status / workspace -------------------------------------------------

    def status(self) -> dict[str, object]:
        payload = self._status_provider()
        payload["workspace"] = str(self.workspace)
        payload["active_run"] = self._active_run
        return payload

    def set_workspace(self, path_text: str) -> None:
        candidate = Path(os.path.expanduser(path_text)).resolve()
        if not candidate.is_dir():
            raise ValueError(f"not a directory: {path_text}")
        self.workspace = candidate

    # -- file tree / editor -------------------------------------------------

    def resolve_workspace_path(self, relative: str) -> Path:
        root = self.workspace
        candidate = (root / relative).resolve() if relative else root
        if candidate != root and root not in candidate.parents:
            raise ValueError("path escapes the workspace")
        return candidate

    def list_dir(self, relative: str) -> dict[str, object]:
        target = self.resolve_workspace_path(relative)
        if not target.is_dir():
            raise ValueError(f"not a directory: {relative}")
        dirs: list[dict[str, object]] = []
        files: list[dict[str, object]] = []
        try:
            with os.scandir(target) as iterator:
                for entry in iterator:
                    if len(dirs) + len(files) >= _MAX_DIR_ENTRIES:
                        break
                    if entry.name.startswith("."):
                        continue
                    if entry.is_dir(follow_symlinks=False):
                        if entry.name in _IGNORED_DIRS:
                            continue
                        dirs.append({"name": entry.name, "type": "dir"})
                    elif entry.is_file(follow_symlinks=False):
                        files.append({"name": entry.name, "type": "file"})
        except OSError as exc:
            raise ValueError(f"cannot list {relative}: {exc}") from exc
        dirs.sort(key=lambda item: str(item["name"]).lower())
        files.sort(key=lambda item: str(item["name"]).lower())
        return {"path": relative or "", "dirs": dirs, "files": files}

    def read_file(self, relative: str) -> dict[str, object]:
        target = self.resolve_workspace_path(relative)
        if not target.is_file():
            raise ValueError(f"not a file: {relative}")
        if target.stat().st_size > _MAX_FILE_BYTES:
            raise ValueError("file too large to open")
        data = target.read_bytes()
        if b"\x00" in data[:8192]:
            raise ValueError("binary file")
        try:
            content = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("binary file") from exc
        return {"path": relative, "content": content}

    def write_file(self, relative: str, content: str) -> dict[str, object]:
        target = self.resolve_workspace_path(relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8", newline="")
        return {"path": relative, "ok": True}

    # -- chat ---------------------------------------------------------------

    def next_run_id(self) -> int:
        with self._run_lock:
            self._run_counter += 1
            self._active_run = self._run_counter
            return self._run_counter

    def clear_active_run(self, run_id: int) -> None:
        with self._run_lock:
            if self._active_run == run_id:
                self._active_run = None

    def provider(self) -> object:
        return self._provider_factory()


class _Handler(BaseHTTPRequestHandler):
    """Request router for the desktop UI."""

    server_version = "UpAgent/0.1"

    @property
    def app(self) -> DesktopApp:
        return self.server.app  # type: ignore[attr-defined, no-any-return]

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        pass  # keep stdout clean; errors are returned as JSON instead

    # -- helpers ------------------------------------------------------------

    def _json(self, payload: object, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _error(self, message: str, status: int = 400) -> None:
        self._json({"error": message}, status=status)

    def _read_json(self) -> dict[str, object]:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0 or length > _MAX_FILE_BYTES:
            raise ValueError("empty or oversized request body")
        raw = self.rfile.read(length)
        data = json.loads(raw.decode("utf-8"))
        if not isinstance(data, dict):
            raise ValueError("request body must be a JSON object")
        return data

    def _static(self, name: str, content_type: str) -> None:
        path = self.server.frontend_dir / name  # type: ignore[attr-defined]
        try:
            body = path.read_bytes()
        except OSError:
            self._error("not found", status=404)
            return
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # -- routing ------------------------------------------------------------

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        if parsed.path == "/":
            self._static("index.html", "text/html; charset=utf-8")
        elif parsed.path == "/styles.css":
            self._static("styles.css", "text/css; charset=utf-8")
        elif parsed.path == "/app.js":
            self._static("app.js", "application/javascript; charset=utf-8")
        elif parsed.path == "/api/status":
            self._json(self.app.status())
        elif parsed.path == "/api/tree":
            try:
                self._json(self.app.list_dir(query.get("path", [""])[0]))
            except ValueError as exc:
                self._error(str(exc))
        elif parsed.path == "/api/file":
            try:
                self._json(self.app.read_file(query.get("path", [""])[0]))
            except ValueError as exc:
                self._error(str(exc))
        elif parsed.path == "/api/events":
            self._stream_events(query)
        else:
            self._error("not found", status=404)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        try:
            data = self._read_json()
        except (ValueError, json.JSONDecodeError) as exc:
            self._error(str(exc))
            return
        if parsed.path == "/api/workspace":
            try:
                self.app.set_workspace(str(data.get("path") or ""))
                self._json({"ok": True, "workspace": str(self.app.workspace)})
            except ValueError as exc:
                self._error(str(exc))
        elif parsed.path == "/api/chat":
            goal = str(data.get("goal") or "").strip()
            if not goal:
                self._error("goal is required")
                return
            run_id = self.app.next_run_id()
            self.app.broker.start_run(run_id)
            tech_stack = str(data.get("tech_stack") or "").strip()
            self.app.broker.emit(run_id, "user", goal)
            self.server.start_chat(run_id, goal, tech_stack)  # type: ignore[attr-defined]
            self._json({"ok": True, "run_id": run_id})
        else:
            self._error("not found", status=404)

    def do_PUT(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path != "/api/file":
            self._error("not found", status=404)
            return
        try:
            data = self._read_json()
            file_path = str(data.get("path") or "")
            content = str(data.get("content") or "")
            self._json(self.app.write_file(file_path, content))
        except (ValueError, json.JSONDecodeError) as exc:
            self._error(str(exc))

    def _stream_events(self, query: dict[str, list[str]]) -> None:
        try:
            run_id = int(query.get("run_id", ["0"])[0])
        except ValueError:
            self._error("invalid run_id")
            return
        stream = self.app.broker.subscribe(run_id)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        try:
            while True:
                try:
                    event = stream.get(timeout=15.0)
                except queue.Empty:
                    self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
                    continue
                if event is None:
                    break
                payload = json.dumps(event.to_dict(), ensure_ascii=False)
                self.wfile.write(f"data: {payload}\n\n".encode())
                self.wfile.flush()
                if event.kind in {"done", "error"}:
                    break
        except (BrokenPipeError, ConnectionResetError, OSError):
            return


class _DesktopHTTPServer(ThreadingHTTPServer):
    daemon_threads = True


def create_server(
    app: DesktopApp,
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    frontend_dir: Path,
    start_chat: Callable[[int, str, str], None],
) -> _DesktopHTTPServer:
    """Create (but do not start) the desktop HTTP server."""
    server = _DesktopHTTPServer((host, port), _Handler)
    server.app = app  # type: ignore[attr-defined]
    server.frontend_dir = frontend_dir  # type: ignore[attr-defined]
    server.start_chat = start_chat  # type: ignore[attr-defined]
    return server
