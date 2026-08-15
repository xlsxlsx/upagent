"""Test Runner Tool（new.md「九、Tool 系统大改」中的 test_runner）。

对 TerminalTool 的专用封装：只跑测试命令，输出结构化摘要
（passed/failed 计数），供 Reflection 修复循环直接消费。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import ClassVar

from agent.tools.base import Tool, ToolResult
from agent.tools.terminal import TerminalTool

# pytest 摘要行，如 "3 passed, 1 failed in 0.12s"
_SUMMARY = re.compile(r"(\d+)\s+(passed|failed|errors?)")


@dataclass
class TestRunnerTool(Tool):
    """跑测试并解析结果摘要。"""

    __test__ = False  # 避免 pytest 把 Test* 类名误收集为用例

    terminal: TerminalTool = field(default_factory=TerminalTool)
    default_command: str = "python -m pytest -q"
    name: str = "test_runner"

    def run(self, **kwargs: str) -> ToolResult:
        command = kwargs.get("command", "").strip() or self.default_command
        result = self.terminal.run(command=command)
        counts = {kind: int(num) for num, kind in _SUMMARY.findall(result.output)}
        summary = ", ".join(f"{v} {k}" for k, v in counts.items()) or "no summary parsed"
        prefix = "tests ok" if result.ok else "tests failed"
        return ToolResult(ok=result.ok, output=f"{prefix} ({summary})\n{result.output}")


@dataclass
class PackageManagerTool(Tool):
    """包管理（new.md 的 package_manager）：只放行安装/查询类子命令。"""

    terminal: TerminalTool = field(default_factory=TerminalTool)
    name: str = "package_manager"

    # 允许的包管理器命令前缀（危险操作仍受 terminal 黑名单约束）
    _ALLOWED_PREFIXES: ClassVar[tuple[str, ...]] = (
        "pip install",
        "pip list",
        "pip show",
        "uv add",
        "uv pip install",
        "uv sync",
        "npm install",
        "npm ls",
        "pnpm install",
    )

    def run(self, **kwargs: str) -> ToolResult:
        command = kwargs.get("command", "").strip()
        if not command:
            return ToolResult.failure("package_manager: missing 'command' argument")
        if not command.lower().startswith(self._ALLOWED_PREFIXES):
            return ToolResult.failure(
                f"package_manager: only install/list commands allowed, got: {command}"
            )
        return self.terminal.run(command=command)
