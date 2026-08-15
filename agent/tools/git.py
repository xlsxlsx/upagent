"""Git Tool（对应 agent/tools/git.md 的规范与红线）。

只允许白名单子命令（status/diff/log/add/commit/branch/checkout/merge），
提交信息强制 Conventional Commits 前缀；force push、reset --hard
等红线操作直接拒绝（由 TerminalTool 黑名单兜底，这里再加白名单）。
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from agent.tools.base import Tool, ToolResult

_ALLOWED_SUBCOMMANDS = frozenset(
    {"status", "diff", "log", "add", "commit", "branch", "checkout", "switch", "merge"}
)
_COMMIT_PREFIXES = ("feat:", "fix:", "refactor:", "test:", "docs:", "chore:")


@dataclass
class GitTool(Tool):
    """白名单化的 git 操作。"""

    cwd: Path = field(default_factory=Path.cwd)
    timeout: float = 60.0
    name: str = "git"

    def run(self, **kwargs: str) -> ToolResult:
        subcommand = kwargs.get("subcommand", "").strip()
        if subcommand not in _ALLOWED_SUBCOMMANDS:
            return ToolResult.failure(
                f"git: subcommand {subcommand!r} not allowed; allowed: "
                f"{sorted(_ALLOWED_SUBCOMMANDS)}"
            )
        args = kwargs.get("args", "").strip()
        if subcommand == "commit":
            message = kwargs.get("message", "").strip()
            if not message.lower().startswith(_COMMIT_PREFIXES):
                return ToolResult.failure(
                    f"git: commit message must start with one of {_COMMIT_PREFIXES}"
                )
            command = ["git", "commit", "-m", message]
        else:
            command = ["git", subcommand, *args.split()]
        try:
            proc = subprocess.run(
                command,
                cwd=self.cwd,
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )
        except subprocess.TimeoutExpired:
            return ToolResult.failure(f"git: timeout: {' '.join(command)}")
        output = (proc.stdout + proc.stderr).strip()
        if proc.returncode != 0:
            return ToolResult.failure(f"exit {proc.returncode}\n{output}")
        return ToolResult.success(output)
