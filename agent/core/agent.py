"""核心 Agent 类（new.md「1. Agent Core / agent.py」）。

一个 Agent = 名字 + 角色配置（roles/*.md）+ 工具集 + 记忆。
角色 Markdown 是 Agent 的 Prompt 来源：职责、规则、输出格式。
推理逻辑通过注入的 reason_fn 提供（生产环境接 LLM，测试用桩函数），
使核心与任何具体模型解耦。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent.memory.store import MemoryStore
    from agent.tools.base import Tool

# 推理函数签名：(role_prompt, task, context) -> 原始思考文本
ReasonFn = Callable[[str, str, str], str]

AGENT_ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Thought:
    """一次推理的结构化结果，供 Planner 决定行动。"""

    agent_name: str
    task: str
    content: str


@dataclass
class Agent:
    """一个可调度的角色 Agent 实例。

    例::

        architect = Agent(
            name="Architect",
            role="architect.md",
            tools=[terminal, git],
            memory=store,
            reason_fn=llm_reason,
        )
    """

    name: str
    role: str  # roles/ 下的文件名，如 "architect.md"
    tools: list[Tool] = field(default_factory=list)
    memory: MemoryStore | None = None
    reason_fn: ReasonFn | None = None
    roles_dir: Path = AGENT_ROOT / "roles"

    def role_prompt(self) -> str:
        """读取 roles/<role>，获得职责、规则与输出格式。"""
        path = self.roles_dir / self.role
        if not path.is_file():
            raise FileNotFoundError(f"role config not found: {path}")
        return path.read_text(encoding="utf-8")

    def tool_names(self) -> list[str]:
        return [tool.name for tool in self.tools]

    def find_tool(self, name: str) -> Tool:
        for tool in self.tools:
            if tool.name == name:
                return tool
        raise KeyError(f"agent {self.name!r} has no tool {name!r}")

    def reason(self, task: str, context: str) -> Thought:
        """Agent 思考：角色 Prompt + 任务 + 上下文 → 思考结果。"""
        if self.reason_fn is None:
            raise RuntimeError(f"agent {self.name!r} has no reason_fn configured")
        content = self.reason_fn(self.role_prompt(), task, context)
        return Thought(agent_name=self.name, task=task, content=content)
