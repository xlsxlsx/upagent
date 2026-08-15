"""团队工厂 + 新工具 + Fixer 测试（非 LLM 框架层）。

覆盖：
- DatabaseTool：只读判定、标识符校验、CLI 拼装、迁移脚本工作区约束
- DockerTool：白名单放行 / 危险子命令拒绝
- Fixer：Diagnosis → FixPlan → 修复任务文本；注入 analyze_fn
- build_team：按角色装配工具集并注册进 Router

全部使用桩函数与假工具，不依赖真实 LLM 与网络。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from agent.agents.team import build_team
from agent.planner.task_tree import TaskNode
from agent.reflection.error_analyzer import analyze_output
from agent.reflection.fixer import Fixer
from agent.reflection.reflector import Reflector
from agent.tools.base import ToolResult
from agent.tools.database import (
    DatabaseTool,
    build_command,
    is_read_only_query,
    validate_identifier,
)
from agent.tools.docker import DockerTool
from agent.tools.terminal import TerminalTool

_PYTEST_OUTPUT = """\
============ FAILURES =============
  File "src/auth/user.py", line 10, in login
    assert token
FAILED tests/test_auth.py::test_login - AssertionError: empty token
AssertionError: empty token
"""


# --- DatabaseTool：纯逻辑 ---


def test_is_read_only_query_rules() -> None:
    assert is_read_only_query("SELECT * FROM users")
    assert is_read_only_query("SHOW TABLES")
    assert is_read_only_query("  explain select 1")
    assert not is_read_only_query("INSERT INTO users VALUES (1)")
    assert not is_read_only_query("UPDATE users SET name='x'")
    assert not is_read_only_query("SELECT * FROM users FOR UPDATE")  # 写锁
    assert not is_read_only_query("SELECT * INTO OUTFILE '/tmp/x' FROM t")  # 写文件
    assert not is_read_only_query("")


def test_validate_identifier_rules() -> None:
    validate_identifier("app_db", "database")  # 不抛
    with pytest.raises(ValueError):
        validate_identifier("app; drop", "database")
    with pytest.raises(ValueError):
        validate_identifier("app db", "database")


def test_build_command_mysql_and_postgres() -> None:
    mysql = build_command(
        "mysql", "query", database="app", query="SELECT 1", user="root", port="3306"
    )
    assert mysql[:4] == ["mysql", "--batch", "--host", "localhost"]
    assert "--database" in mysql and "app" in mysql
    assert mysql[-2:] == ["--execute", "SELECT 1"]

    pg = build_command("postgres", "query", database="app", query="SELECT 1", user="root")
    assert pg[0] == "psql" and "--dbname" in pg and "--command" in pg
    assert "--execute" not in pg


def test_build_command_rejects_write_and_bad_input() -> None:
    with pytest.raises(ValueError, match="read-only"):
        build_command("mysql", "query", database="app", query="DELETE FROM t")
    with pytest.raises(ValueError, match="unsupported engine"):
        build_command("oracle", "query", database="app", query="SELECT 1")
    with pytest.raises(ValueError, match="operation"):
        build_command("mysql", "truncate", database="app")
    with pytest.raises(ValueError, match="database"):
        build_command("mysql", "query", database="a b", query="SELECT 1")


# --- DatabaseTool：工具行为 ---


def test_database_tool_rejects_write_without_subprocess(tmp_path: Path) -> None:
    tool = DatabaseTool(workspace=tmp_path)
    result = tool.run(operation="query", database="app", query="INSERT INTO t VALUES (1)")
    assert not result.ok and "read-only" in result.output


def test_database_tool_migration_must_be_in_workspace(tmp_path: Path) -> None:
    tool = DatabaseTool(workspace=tmp_path)
    outside = tmp_path.parent / "evil.sql"
    outside.write_text("DROP TABLE t;", encoding="utf-8")
    result = tool.run(operation="migrate", database="app", migration="../evil.sql")
    assert not result.ok and "migration script not found" in result.output


def test_database_tool_client_error_returns_failure(tmp_path: Path) -> None:
    # 客户端缺失（FileNotFoundError）或连接失败（exit != 0）都返回 failure
    tool = DatabaseTool(workspace=tmp_path, timeout=5.0)
    result = tool.run(operation="query", database="app", query="SELECT 1")
    assert not result.ok and result.output


# --- DockerTool ---


class _FakeTerminal(TerminalTool):
    def __init__(self, ok: bool, output: str) -> None:
        super().__init__()
        self._result = ToolResult(ok=ok, output=output)
        self.calls: list[dict[str, str]] = []

    def run(self, **kwargs: str) -> ToolResult:
        self.calls.append(dict(kwargs))
        return self._result


def test_docker_tool_whitelist_and_blocks() -> None:
    terminal = _FakeTerminal(True, "ok")
    tool = DockerTool(terminal=terminal)
    assert tool.run(command="docker ps -a").ok
    assert tool.run(command="docker compose config").ok
    assert len(terminal.calls) == 2
    blocked = tool.run(command="docker run -it ubuntu bash")
    assert not blocked.ok and "需要人工确认" in blocked.output
    exec_blocked = tool.run(command="docker exec web ls /")  # exec 不在白名单 → 拒绝
    assert not exec_blocked.ok
    assert len(terminal.calls) == 2  # 两次拒绝都没有真的执行终端


def test_docker_tool_requires_command() -> None:
    tool = DockerTool(terminal=_FakeTerminal(True, "ok"))
    assert not tool.run().ok and "missing 'command'" in tool.run().output


# --- Fixer ---


def test_fixer_builds_plan_from_diagnosis() -> None:
    fixer = Fixer()
    plan = fixer.build_plan("实现登录", _PYTEST_OUTPUT)
    assert plan.diagnosis.error_type == "AssertionError"
    assert "src/auth/user.py" in plan.files
    assert plan.diagnosis.failed_tests == ("tests/test_auth.py::test_login",)
    text = plan.to_task()
    assert "修复以下测试失败（原任务：实现登录）" in text
    assert "诊断:" in text and "AssertionError" in text
    assert "tests/test_auth.py::test_login" in text


def test_fixer_plan_fix_injected_analyzer() -> None:
    fixer = Fixer(analyze_fn=lambda task, output: f"fix:{task}")
    assert fixer.plan_fix("t", "whatever") == "fix:t"


def test_reflector_and_fixer_agree_on_diagnosis() -> None:
    diagnosis = analyze_output(_PYTEST_OUTPUT)
    plan = Fixer().build_plan("实现登录", _PYTEST_OUTPUT)
    assert plan.diagnosis == diagnosis
    fix_task = Reflector().plan_fix("实现登录", _PYTEST_OUTPUT)
    assert "AssertionError" in fix_task and "实现登录" in fix_task


# --- build_team ---


def test_build_team_registers_role_agents(tmp_path: Path) -> None:
    router = build_team(
        workspace=tmp_path, reason_fn=lambda role_prompt, task, context: "done"
    )
    names = set(router.agents)
    assert names >= {"Backend", "Frontend", "Database", "Tester", "Security", "Reviewer", "DevOps"}

    backend = router.route(TaskNode(title="x", task_type="backend"))
    assert backend.name == "Backend"
    tools = set(backend.tool_names())
    assert {"file", "patch", "terminal", "test_runner"} <= tools

    tester = router.route(TaskNode(title="x", task_type="testing"))
    assert tester.tool_names() == ["terminal", "test_runner"]

    devops = router.route(TaskNode(title="x", task_type="deploy"))
    assert "docker" in devops.tool_names() and "package_manager" in devops.tool_names()

    # 全部角色的 prompt 可加载（roles/ 下文件齐全）
    for agent in router.agents.values():
        assert agent.role_prompt().strip()


def test_build_team_injects_reason_fn(tmp_path: Path) -> None:
    router = build_team(
        workspace=tmp_path, reason_fn=lambda role_prompt, task, context: "thinking"
    )
    backend = router.route(TaskNode(title="x", task_type="backend"))
    assert backend.reason("t", "c").content == "thinking"