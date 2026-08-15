"""Tool 抽象基类与统一结果类型。

Agent 的请求形如 {tool: "terminal", command: "pytest"}，
由具体 Tool 执行并返回 ToolResult。每个 Tool 的能力边界
与安全限制对应 agent/tools/*.md 的描述文件。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class ToolResult:
    """一次工具调用的统一返回。"""

    ok: bool
    output: str

    @classmethod
    def success(cls, output: str = "") -> ToolResult:
        return cls(ok=True, output=output)

    @classmethod
    def failure(cls, output: str) -> ToolResult:
        return cls(ok=False, output=output)


class Tool(ABC):
    """所有工具的基类。name 供 Action.kind 与 Agent.find_tool 匹配。"""

    name: str = ""

    @abstractmethod
    def run(self, **kwargs: str) -> ToolResult:
        """执行工具调用；实现必须捕获自身异常并转为 failure。"""
