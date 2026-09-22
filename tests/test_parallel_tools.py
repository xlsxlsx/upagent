"""无依赖工具并行化测试（AgentLoop Action.parallel）。"""

from __future__ import annotations

import time
from pathlib import Path

from agent.core.agent import Agent
from agent.core.loop import Action, AgentLoop
from agent.core.state import ProjectState
from agent.tools.base import Tool, ToolResult
from agent.tools.file import FileTool


class _SleepTool(Tool):
    """记录每次调用的耗时，供并行性断言。"""

    name = "sleep"

    def __init__(self, seconds: float) -> None:
        self.seconds = seconds
        self.runs: list[float] = []

    def run(self, **kwargs: str) -> ToolResult:
        started = time.perf_counter()
        time.sleep(self.seconds)
        self.runs.append(time.perf_counter() - started)
        return ToolResult.success("slept")


def _agent(tmp_path: Path, tools: list[Tool]) -> Agent:
    roles = tmp_path / "roles"
    roles.mkdir(exist_ok=True)
    (roles / "dev.md").write_text("# Dev\nwrite code.\n", encoding="utf-8")
    return Agent(
        name="Dev",
        role="dev.md",
        reason_fn=lambda role_prompt, task, context: "ok",
        roles_dir=roles,
        tools=tools,
    )


def test_parallel_batch_runs_concurrently(tmp_path: Path) -> None:
    tool = _SleepTool(0.2)
    actions = [
        Action(
            kind="parallel",
            parallel=(Action("sleep", {"label": "a"}), Action("sleep", {"label": "b"})),
        ),
        Action.finish("done"),
    ]
    loop = AgentLoop(
        agent=_agent(tmp_path, [tool]),
        decide_fn=lambda thought: actions.pop(0),
        state=ProjectState(),
    )
    started = time.perf_counter()
    result = loop.run("run both")
    elapsed = time.perf_counter() - started
    assert result.finished
    assert elapsed < 0.35  # 顺序执行至少 0.4s
    assert len(tool.runs) == 2  # 两个子动作都执行了


def test_parallel_batch_degrades_to_sequential_on_shared_path(tmp_path: Path) -> None:
    file_a = FileTool(workspace=tmp_path)
    file_b = FileTool(workspace=tmp_path)
    actions = [
        Action(
            kind="parallel",
            parallel=(
                Action("file", {"operation": "write", "path": "same.txt", "content": "1"}),
                Action("file", {"operation": "write", "path": "same.txt", "content": "2"}),
            ),
        ),
        Action.finish("done"),
    ]
    loop = AgentLoop(
        agent=_agent(tmp_path, [file_a, file_b]),
        decide_fn=lambda thought: actions.pop(0),
        state=ProjectState(),
    )
    result = loop.run("write same file twice")
    assert result.finished
    assert (tmp_path / "same.txt").read_text(encoding="utf-8") == "2"
    assert "parallel" in result.history[0]


def test_parallel_batch_reports_partial_failure(tmp_path: Path) -> None:
    class _FailTool(Tool):
        name = "boom"

        def run(self, **kwargs: str) -> ToolResult:
            return ToolResult.failure("kaboom")

    file_tool = FileTool(workspace=tmp_path)
    actions = [
        Action(
            kind="parallel",
            parallel=(
                Action("file", {"operation": "write", "path": "a.txt", "content": "1"}),
                Action("boom", {}),
            ),
        ),
        Action.finish("done"),
    ]
    loop = AgentLoop(
        agent=_agent(tmp_path, [file_tool, _FailTool()]),
        decide_fn=lambda thought: actions.pop(0),
        state=ProjectState(),
    )
    result = loop.run("mixed batch")
    assert result.finished
    entry = result.history[0]
    assert "parallel" in entry and "fail" in entry and "kaboom" in entry
    assert "boom->fail" in entry
    assert (tmp_path / "a.txt").is_file()
    assert "a.txt" not in result.touched_paths  # 批量失败不记入审计范围


def test_loop_captures_diff_for_file_writes(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("old\n", encoding="utf-8")
    actions = [
        Action("file", {"operation": "write", "path": "a.txt", "content": "new\n"}),
        Action.finish("done"),
    ]
    loop = AgentLoop(
        agent=_agent(tmp_path, [FileTool(workspace=tmp_path)]),
        decide_fn=lambda thought: actions.pop(0),
        state=ProjectState(),
    )
    result = loop.run("update a.txt")
    assert result.finished
    assert "-old" in result.diff and "+new" in result.diff
    assert result.touched_paths == ("a.txt",)


def test_loop_captures_diff_for_new_files(tmp_path: Path) -> None:
    actions = [
        Action("file", {"operation": "write", "path": "new.txt", "content": "brand new\n"}),
        Action.finish("done"),
    ]
    loop = AgentLoop(
        agent=_agent(tmp_path, [FileTool(workspace=tmp_path)]),
        decide_fn=lambda thought: actions.pop(0),
        state=ProjectState(),
    )
    result = loop.run("create new.txt")
    assert result.finished
    assert "+brand new" in result.diff


def test_auto_finish_after_repeated_parallel_success(tmp_path: Path) -> None:
    tool = _SleepTool(0.0)
    batch = Action("parallel", parallel=(Action("sleep", {"label": "x"}),))
    actions = [batch, batch, Action.finish("unreachable")]
    loop = AgentLoop(
        agent=_agent(tmp_path, [tool]),
        decide_fn=lambda thought: actions.pop(0),
        state=ProjectState(),
    )
    result = loop.run("repeat batch")
    assert result.finished
    assert any("auto-finish" in entry for entry in result.history)

