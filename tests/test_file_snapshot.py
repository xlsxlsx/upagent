"""文件级回滚测试（dev-notes/software-development-agent-phase.md「文件级回滚」）。

覆盖：
- write_snapshot / restore_snapshot 往返：误删与误改都能还原
- 只备份受管理前缀下的文件，跳过 .git/.venv 与大文件
- snapshot_paths 只读索引；空快照/缺失快照安全返回
- 恢复拒绝越界路径（.. / 绝对路径）
- Supervisor 接入：任务失败恢复、终审失败恢复基线、验收通过清理备份

全部使用假工具与桩函数，不依赖真实 LLM 与网络。
"""

from __future__ import annotations

from pathlib import Path

from agent.communication.event import EventType
from agent.core.agent import Agent
from agent.core.loop import Action
from agent.core.request import UserRequest
from agent.core.state import ProjectState
from agent.memory.store import MemoryStore
from agent.planner.task_tree import TaskNode, TaskTree
from agent.router.router import AgentRouter
from agent.supervisor.file_snapshot import (
    _INDEX,
    restore_snapshot,
    snapshot_paths,
    write_snapshot,
)
from agent.supervisor.supervisor import Supervisor
from agent.tools.file import FileTool

# --- 快照模块 ---


def _tree(root: Path) -> None:
    (root / "src").mkdir(parents=True, exist_ok=True)
    (root / "src" / "app.py").write_text("print('ok')\n", encoding="utf-8")
    (root / "agent" / "core").mkdir(parents=True, exist_ok=True)
    (root / "agent" / "core" / "loop.py").write_text("LOOP = 1\n", encoding="utf-8")
    (root / "tests").mkdir(parents=True, exist_ok=True)
    (root / "tests" / "test_app.py").write_text("def test(): pass\n", encoding="utf-8")
    # 不受管理的内容：忽略目录与根级文件
    (root / ".venv" / "lib").mkdir(parents=True, exist_ok=True)
    (root / ".venv" / "lib" / "junk.py").write_text("junk\n", encoding="utf-8")
    (root / "README.md").write_text("readme\n", encoding="utf-8")


def test_write_and_restore_roundtrip(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    snaps = tmp_path / "snapshots"
    _tree(root)
    saved = write_snapshot(snaps, root)
    assert set(saved) == {
        "src/app.py",
        "agent/core/loop.py",
        "tests/test_app.py",
    }
    assert snapshot_paths(snaps) == tuple(sorted(saved))
    # 模拟终端误删 + 误改
    (root / "src" / "app.py").write_text("broken\n", encoding="utf-8")
    (root / "agent" / "core" / "loop.py").unlink()
    restored = restore_snapshot(snaps, root)
    assert set(restored) == set(saved)
    assert (root / "src" / "app.py").read_text(encoding="utf-8") == "print('ok')\n"
    assert (root / "agent" / "core" / "loop.py").read_text(encoding="utf-8") == "LOOP = 1\n"
    # 成功后快照目录删除，防止旧快照被重复恢复污染
    assert not snaps.exists()


def test_snapshot_skips_large_files(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    _tree(root)
    (root / "src" / "big.bin").write_bytes(b"\x00" * (1024 * 1024 + 1))
    saved = write_snapshot(tmp_path / "snaps", root)
    assert "src/big.bin" not in saved
    assert (root / "src" / "big.bin").stat().st_size > 1024 * 1024


def test_snapshot_binary_content_roundtrip(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    (root / "scripts").mkdir(parents=True)
    payload = bytes(range(256)) * 4
    (root / "scripts" / "blob.dat").write_bytes(payload)
    snaps = tmp_path / "snaps"
    write_snapshot(snaps, root)
    (root / "scripts" / "blob.dat").unlink()
    restore_snapshot(snaps, root)
    assert (root / "scripts" / "blob.dat").read_bytes() == payload


def test_restore_missing_snapshot_is_noop(tmp_path: Path) -> None:
    assert restore_snapshot(tmp_path / "nope", tmp_path) == ()
    assert snapshot_paths(tmp_path / "nope") == ()


def test_write_snapshot_rewrites_stale_backup(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    _tree(root)
    snaps = tmp_path / "snaps"
    write_snapshot(snaps, root)
    (root / "src" / "app.py").write_text("v2\n", encoding="utf-8")
    write_snapshot(snaps, root)
    (root / "src" / "app.py").write_text("corrupted\n", encoding="utf-8")
    restore_snapshot(snaps, root)
    assert (root / "src" / "app.py").read_text(encoding="utf-8") == "v2\n"


def test_restore_rejects_escaping_index_entries(tmp_path: Path) -> None:
    root = tmp_path / "root"
    (root / "src").mkdir(parents=True)
    snaps = tmp_path / "snaps"
    snaps.mkdir()
    (snaps / "good").write_text("ok\n", encoding="utf-8")
    (snaps / "evil").write_text("pwned\n", encoding="utf-8")
    (snaps / _INDEX).write_text(
        "# file-snapshot v1\n"
        "good\tsrc/ok.txt\n"
        "evil\t../outside.txt\n",
        encoding="utf-8",
    )
    restored = restore_snapshot(snaps, root)
    assert restored == ("src/ok.txt",)
    assert not (tmp_path / "outside.txt").exists()
    assert (root / "src" / "ok.txt").read_text(encoding="utf-8") == "ok\n"
    # 存在越界条目：保留快照目录供人工检查，不静默删除
    assert snaps.exists()


# --- Supervisor 接入 ---


def _router_with_file_tool(workspace: Path) -> AgentRouter:
    roles = workspace / "_roles"
    roles.mkdir(parents=True, exist_ok=True)
    (roles / "any.md").write_text("# Any\n职责：全栈。\n", encoding="utf-8")
    agent = Agent(
        name="Any",
        role="any.md",
        reason_fn=lambda role_prompt, task, context: "done",
        roles_dir=roles,
        tools=[FileTool(workspace=workspace)],
    )
    router = AgentRouter(llm_route_fn=lambda title, names: "Any")
    router.register(agent)
    return router


def _write_then_finish(path: str, content: str):
    wrote = False

    def decide_fn(thought) -> Action:
        nonlocal wrote
        if not wrote:
            wrote = True
            return Action("file", {"operation": "write", "path": path, "content": content})
        return Action.finish("done")

    return decide_fn


def _single_node_tree(task: str, tech_stack=None) -> TaskTree:
    return TaskTree(TaskNode(task, "backend"))


def test_supervisor_reverts_files_on_failed_task(tmp_path: Path) -> None:
    out = tmp_path / "out"
    (out / "src").mkdir(parents=True)
    artifact = out / "src" / "app.py"
    artifact.write_text("original\n", encoding="utf-8")
    supervisor = Supervisor(
        router=_router_with_file_tool(out),
        decide_fn=_write_then_finish("src/app.py", "corrupted\n"),
        state=ProjectState(),
        memory=MemoryStore(root=tmp_path / "memory"),
        output_dir=out,
        file_backups=tmp_path / "backups",
        review_fn=lambda node, summary: False,
        max_retries=0,
    )
    node = TaskNode(title="改写核心逻辑", task_type="backend")
    assert not supervisor._run_node(node)
    assert artifact.read_text(encoding="utf-8") == "original\n"
    types = {event.type for event in supervisor.events.history()}
    assert EventType.FILES_REVERTED in types
    assert "src/app.py" in supervisor.touched_paths


def test_supervisor_without_output_dir_skips_backups(tmp_path: Path) -> None:
    supervisor = Supervisor(
        router=_router_with_file_tool(tmp_path),
        decide_fn=lambda thought: Action.finish("done"),
        state=ProjectState(),
        file_backups=tmp_path / "backups",
        review_fn=lambda node, summary: False,
        max_retries=0,
    )
    node = TaskNode(title="改写核心逻辑", task_type="backend")
    assert not supervisor._run_node(node)
    # output_dir 未设置：不扫描当前仓库，也不创建备份目录
    assert not (tmp_path / "backups").exists()


def test_run_request_restores_baseline_on_acceptance_failure(tmp_path: Path) -> None:
    out = tmp_path / "out"
    (out / "src").mkdir(parents=True)
    artifact = out / "src" / "app.py"
    artifact.write_text("original\n", encoding="utf-8")
    supervisor = Supervisor(
        router=_router_with_file_tool(out),
        decide_fn=_write_then_finish("src/app.py", "broken\n"),
        state=ProjectState(),
        memory=MemoryStore(root=tmp_path / "memory"),
        decompose_fn=_single_node_tree,
        output_dir=out,
        file_backups=tmp_path / "backups",
        acceptance_fn=lambda plan: False,
        max_rollbacks=0,
    )
    result = supervisor.run_request(UserRequest(goal="改写核心逻辑", tech_stack="Python"))
    assert result.finished and not result.accepted
    assert artifact.read_text(encoding="utf-8") == "original\n"
    types = {event.type for event in supervisor.events.history()}
    assert EventType.FILES_REVERTED in types


def test_run_request_drops_backups_after_acceptance(tmp_path: Path) -> None:
    out = tmp_path / "out"
    (out / "src").mkdir(parents=True)
    (out / "src" / "app.py").write_text("original\n", encoding="utf-8")
    supervisor = Supervisor(
        router=_router_with_file_tool(out),
        decide_fn=_write_then_finish("src/app.py", "final\n"),
        state=ProjectState(),
        decompose_fn=_single_node_tree,
        output_dir=out,
        file_backups=tmp_path / "backups",
        acceptance_fn=lambda plan: True,
    )
    result = supervisor.run_request(UserRequest(goal="改写核心逻辑", tech_stack="Python"))
    assert result.finished and result.accepted
    assert (out / "src" / "app.py").read_text(encoding="utf-8") == "final\n"
    assert not (tmp_path / "backups").exists()