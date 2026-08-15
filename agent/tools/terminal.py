"""Terminal Tool（对应 agent/tools/terminal.md 的能力与限制）。

能力：shell / build / test。
限制：内置危险命令黑名单（safety_policy.md），命中即拒绝执行。
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from agent.tools.base import Tool, ToolResult

# 危险命令片段黑名单：删除、提权、强推、下载执行
_FORBIDDEN_PATTERNS: tuple[str, ...] = (
    "rm -rf",
    "rm -fr",
    "remove-item",
    "rmdir",
    "del ",
    "format ",
    "mkfs",
    "sudo ",
    "push --force",
    "push -f",
    "reset --hard",
    "curl ",
    "wget ",
    "> /dev/",
)


@dataclass
class TerminalTool(Tool):
    """执行 shell 命令，带安全黑名单与超时。"""

    cwd: Path = field(default_factory=Path.cwd)
    timeout: float = 300.0
    name: str = "terminal"

    def run(self, **kwargs: str) -> ToolResult:
        command = kwargs.get("command", "").strip()
        if not command:
            return ToolResult.failure("terminal: missing 'command' argument")
        blocked = _match_forbidden(command)
        if blocked:
            return ToolResult.failure(
                f"terminal: command blocked by safety policy (matched {blocked!r})"
            )
        try:
            proc = subprocess.run(
                command,
                shell=True,
                cwd=self.cwd,
                capture_output=True,
                timeout=self.timeout,
            )
        except subprocess.TimeoutExpired:
            return ToolResult.failure(f"terminal: timeout after {self.timeout}s: {command}")
        # 字节捕获 + UTF-8 容错解码，避免 Windows 默认 GBK 解码崩溃
        raw = (proc.stdout or b"") + (proc.stderr or b"")
        output = raw.decode("utf-8", errors="replace").strip()
        if proc.returncode != 0:
            return ToolResult.failure(f"exit {proc.returncode}\n{output}")
        return ToolResult.success(output)


def _match_forbidden(command: str) -> str:
    lowered = command.lower()
    for pattern in _FORBIDDEN_PATTERNS:
        if pattern in lowered:
            return pattern
    return ""
