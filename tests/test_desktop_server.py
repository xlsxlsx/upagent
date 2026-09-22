"""Desktop UI backend tests: file tree/editor APIs + chat SSE pipeline (offline)."""

from __future__ import annotations

import json
import threading
from pathlib import Path

import httpx
import pytest
from desktop.runner import ChatRunner
from desktop.server import DesktopApp, create_server


class _FakeProvider:
    """Offline provider: finish immediately and return a one-task plan."""

    def complete(self, messages, **kwargs) -> str:
        return '{"kind": "finish", "note": "done"}'

    def complete_json(self, messages, **kwargs) -> dict:
        return {"passed": True}


class _FakeDecomposeProvider(_FakeProvider):
    def complete_json(self, messages, **kwargs) -> dict:
        if isinstance(messages[-1].content, str) and "Goal:" in messages[-1].content:
            return {"tasks": [{"title": "implement no-op", "task_type": "backend"}]}
        return {"passed": True}


@pytest.fixture()
def desktop(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "readme.txt").write_text("hello", encoding="utf-8")
    (workspace / "app.py").write_text("print('hi')\n", encoding="utf-8")
    (workspace / "sub").mkdir()
    (workspace / "sub" / "nested.py").write_text("x = 1\n", encoding="utf-8")
    (workspace / ".venv").mkdir()
    (workspace / ".venv" / "hidden.py").write_text("secret", encoding="utf-8")
    (workspace / "bin.dat").write_bytes(b"\x00\x01\x02")
    (tmp_path / "outside.txt").write_text("outside", encoding="utf-8")

    app = DesktopApp(
        workspace,
        provider_factory=lambda: _FakeDecomposeProvider(),
        status_provider=lambda: {"model": "fake", "base_url": "", "key_configured": False},
    )
    runner = ChatRunner(app.broker, get_workspace=lambda: app.workspace)
    server = create_server(
        app,
        host="127.0.0.1",
        port=0,
        frontend_dir=Path(__file__).resolve().parent.parent / "desktop" / "frontend",
        start_chat=lambda run_id, goal, tech_stack: runner.start(run_id, goal, tech_stack, app),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    yield base
    server.shutdown()
    server.server_close()


def test_status_reports_workspace(desktop: str) -> None:
    data = httpx.get(f"{desktop}/api/status").json()
    assert data["model"] == "fake"
    assert data["key_configured"] is False
    assert "workspace" in data


def test_tree_lists_dirs_then_files_and_ignores_noise(desktop: str) -> None:
    data = httpx.get(f"{desktop}/api/tree", params={"path": ""}).json()
    assert [item["name"] for item in data["dirs"]] == ["sub"]
    assert {item["name"] for item in data["files"]} == {"app.py", "readme.txt", "bin.dat"}


def test_tree_lists_subdirectory(desktop: str) -> None:
    data = httpx.get(f"{desktop}/api/tree", params={"path": "sub"}).json()
    assert [item["name"] for item in data["files"]] == ["nested.py"]


def test_file_read(desktop: str) -> None:
    data = httpx.get(f"{desktop}/api/file", params={"path": "readme.txt"}).json()
    assert data["content"] == "hello"


def test_file_read_rejects_binary(desktop: str) -> None:
    response = httpx.get(f"{desktop}/api/file", params={"path": "bin.dat"})
    assert response.status_code == 400
    assert "binary" in response.json()["error"]


def test_file_read_rejects_traversal(desktop: str, tmp_path: Path) -> None:
    response = httpx.get(f"{desktop}/api/file", params={"path": "../outside.txt"})
    assert response.status_code == 400


def test_file_write_then_read(desktop: str) -> None:
    written = httpx.put(
        f"{desktop}/api/file",
        json={"path": "new/dir/note.md", "content": "# note\n"},
    )
    assert written.status_code == 200 and written.json()["ok"] is True
    data = httpx.get(f"{desktop}/api/file", params={"path": "new/dir/note.md"}).json()
    assert data["content"] == "# note\n"


def test_workspace_switch_rejects_missing_dir(desktop: str) -> None:
    response = httpx.post(f"{desktop}/api/workspace", json={"path": "Z:/no/such/dir"})
    assert response.status_code == 400


def test_chat_requires_goal(desktop: str) -> None:
    response = httpx.post(f"{desktop}/api/chat", json={"goal": "  "})
    assert response.status_code == 400


def test_chat_streams_until_done(desktop: str) -> None:
    started = httpx.post(
        f"{desktop}/api/chat",
        json={"goal": "write nothing", "tech_stack": "Python"},
    )
    assert started.status_code == 200
    run_id = started.json()["run_id"]

    events: list[dict] = []
    with httpx.Client(timeout=30) as client, client.stream(
        "GET", f"{desktop}/api/events", params={"run_id": run_id}
    ) as stream:
        for line in stream.iter_lines():
            if not line.startswith("data: "):
                continue
            event = json.loads(line.removeprefix("data: "))
            events.append(event)
            if event["kind"] in {"done", "error"}:
                break
    kinds = [event["kind"] for event in events]
    assert "system" in kinds
    assert "done" in kinds
    assert any(event["kind"] == "step" for event in events)
    done = next(event for event in events if event["kind"] == "done")
    assert "finished" in done["text"]
