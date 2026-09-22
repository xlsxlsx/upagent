"""Docker Tool（dev-notes/new.md「九、Tool 系统大改」中的 docker）。

开发 Agent 的容器工作通道：只读/构建类子命令白名单
（ps / images / logs / inspect / compose config / build）。

`docker run` / `exec` / `rm` / `push` / `compose up` 会改变运行状态或
执行任意容器 → 不在白名单，需要人工确认（对应 safety_policy.md）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import ClassVar

from agent.tools.base import Tool, ToolResult
from agent.tools.terminal import TerminalTool

# 允许的 docker 子命令前缀（只读/构建类）
_ALLOWED_PREFIXES: ClassVar[tuple[str, ...]] = (
    "docker ps",
    "docker images",
    "docker image ls",
    "docker image inspect",
    "docker network ls",
    "docker volume ls",
    "docker logs",
    "docker inspect",
    "docker stats",
    "docker compose config",
    "docker build",
    "docker compose build",
)


@dataclass
class DockerTool(Tool):
    """白名单化的 docker 操作（终端黑名单仍兜底）。"""

    terminal: TerminalTool = field(default_factory=TerminalTool)
    name: str = "docker"

    def run(self, **kwargs: str) -> ToolResult:
        command = kwargs.get("command", "").strip()
        if not command:
            return ToolResult.failure("docker: missing 'command' argument")
        if not command.lower().startswith(_ALLOWED_PREFIXES):
            return ToolResult.failure(
                "docker: only read/inspect/build commands allowed; "
                "run/exec/rm/push/up 需要人工确认，got: " + command
            )
        return self.terminal.run(command=command)