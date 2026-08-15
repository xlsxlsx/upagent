"""Tool System（new.md「9. Tool System」+「九、Tool 系统大改」）。

Agent 不直接操作电脑，它调用 Tool。
写代码优先走 PatchTool（diff → 审核 → 应用），不直接写文件。
"""

from agent.tools.base import Tool, ToolResult
from agent.tools.browser import BrowserTool
from agent.tools.database import DatabaseTool, build_command, is_read_only_query
from agent.tools.docker import DockerTool
from agent.tools.file import FileTool
from agent.tools.git import GitTool
from agent.tools.patch import PatchTool, make_diff
from agent.tools.terminal import TerminalTool
from agent.tools.test_runner import PackageManagerTool, TestRunnerTool

__all__ = [
    "BrowserTool",
    "DatabaseTool",
    "DockerTool",
    "FileTool",
    "GitTool",
    "PackageManagerTool",
    "PatchTool",
    "TerminalTool",
    "TestRunnerTool",
    "Tool",
    "ToolResult",
    "build_command",
    "is_read_only_query",
    "make_diff",
]
