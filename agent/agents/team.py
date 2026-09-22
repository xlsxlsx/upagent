"""团队工厂（dev-notes/new.md 角色体系的装配层，非 LLM 框架）。

roles/*.md 定义「谁」，build_team 按 task_type 装配默认工具集与角色文件，
一次性注册进 AgentRouter。reason_fn 由调用方注入（生产接 LLM，测试用桩），
因此本模块仍是纯标准库、可离线测试。

用法::

    from agent.agents.team import build_team
    from agent.runner import run_project

    router = build_team(workspace=Path("project"), reason_fn=llm_reason)
    outcome = run_project("开发游戏平台", "FastAPI + MySQL", router=router,
                          decide_fn=Planner().decide, output_dir=Path("project"))
"""

from __future__ import annotations

from pathlib import Path

from agent.core.agent import AGENT_ROOT, Agent, ReasonFn
from agent.memory.store import MemoryStore
from agent.router.router import AgentRouter
from agent.tools.base import Tool
from agent.tools.browser import BrowserTool
from agent.tools.database import DatabaseTool
from agent.tools.docker import DockerTool
from agent.tools.file import FileTool
from agent.tools.git import GitTool
from agent.tools.patch import PatchTool
from agent.tools.terminal import TerminalTool
from agent.tools.test_runner import PackageManagerTool, TestRunnerTool

# task_type → (Agent 名, 角色文件, 工具名列表)；Agent 名与 Router 默认映射一致
_TEAM: dict[str, tuple[str, str, tuple[str, ...]]] = {
    "requirement": ("ProductManager", "product_manager.md", ("file",)),
    "architecture": ("Architect", "architect.md", ("file", "patch")),
    "backend": (
        "Backend",
        "backend_engineer.md",
        ("file", "patch", "terminal", "git", "test_runner", "package_manager"),
    ),
    "frontend": (
        "Frontend",
        "frontend_engineer.md",
        ("file", "patch", "terminal", "test_runner", "package_manager"),
    ),
    "database": ("Database", "database_engineer.md", ("file", "patch", "terminal", "database")),
    "testing": ("Tester", "tester.md", ("file", "terminal", "test_runner")),
    "security": ("Security", "security_auditor.md", ("file", "terminal", "browser")),
    "review": ("Reviewer", "code_reviewer.md", ("file", "patch")),
    "deploy": ("DevOps", "devops_engineer.md", ("terminal", "package_manager", "docker")),
}


def build_team(
    *,
    workspace: Path | None = None,
    memory: MemoryStore | None = None,
    reason_fn: ReasonFn | None = None,
    roles_dir: Path = AGENT_ROOT / "roles",
) -> AgentRouter:
    """装配默认角色团队：每个角色一个 Agent，全部注册进 Router。"""
    workspace = workspace or Path.cwd()
    tools = _tool_bag(workspace)
    router = AgentRouter()
    for _, (name, role_file, tool_names) in _TEAM.items():
        router.register(
            Agent(
                name=name,
                role=role_file,
                tools=[tools[tool_name] for tool_name in tool_names],
                memory=memory,
                reason_fn=reason_fn,
                roles_dir=roles_dir,
            )
        )
    return router


def _tool_bag(workspace: Path) -> dict[str, Tool]:
    """每个工具类型一个实例（无状态共享，跨 Agent 复用）。"""
    terminal = TerminalTool(cwd=workspace)
    return {
        "file": FileTool(workspace=workspace),
        "patch": PatchTool(workspace=workspace),
        "terminal": terminal,
        "git": GitTool(cwd=workspace),
        "test_runner": TestRunnerTool(terminal=terminal),
        "package_manager": PackageManagerTool(terminal=terminal),
        "browser": BrowserTool(),
        "database": DatabaseTool(workspace=workspace),
        "docker": DockerTool(terminal=terminal),
    }
