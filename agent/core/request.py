"""UserRequest — 用户输入模型（软件开发 Agent 的入口）。

用户只给两样东西：

    goal        最终目标（要做什么）
    tech_stack  可能的技术栈（用什么做，可为空但强烈建议）

Agent 负责把这两样变成「计划 → 执行 → 审查」的完整流水线。
本模块只做结构化与校验，不含任何业务逻辑；渲染出的文本
供上下文注入与计划落档使用。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class UserRequest:
    """一次软件开发任务的用户输入。"""

    goal: str
    tech_stack: str = ""
    constraints: str = ""  # 可选约束：预算、平台、部署环境等
    output_dir: Path | None = None  # 项目产物目录（计划/报告落盘位置）

    def validate(self) -> None:
        """校验输入；不合法直接抛 ValueError，避免把坏输入送进流水线。"""
        if not self.goal or not self.goal.strip():
            raise ValueError("goal is required: 请描述最终目标")
        if len(self.goal) > 2000:
            raise ValueError("goal is too long (max 2000 chars)")
        if self.tech_stack and len(self.tech_stack) > 1000:
            raise ValueError("tech_stack is too long (max 1000 chars)")

    def render(self) -> str:
        """渲染为给 LLM/计划的请求摘要。"""
        lines = [f"目标: {self.goal.strip()}"]
        if self.tech_stack.strip():
            lines.append(f"技术栈: {self.tech_stack.strip()}")
        if self.constraints.strip():
            lines.append(f"约束: {self.constraints.strip()}")
        return "\n".join(lines)