"""State 状态系统（new.md「3. State」）。

Agent 最大的问题是不知道自己做到哪里，所以必须有状态。
ProjectState 对应 memory/project_memory.md 的结构化形态：
任务、当前阶段、已完成项、当前 Agent、错误列表。
支持 JSON 持久化，长任务中断后可恢复。
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from pathlib import Path

# 八阶段生命周期，顺序即门禁顺序（workflow/task_lifecycle.md）
PHASES: tuple[str, ...] = (
    "requirement",
    "planning",
    "architecture",
    "development",
    "testing",
    "security_audit",
    "optimization",
    "delivery",
)


class PhaseStatus(StrEnum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    FAILED = "failed"


@dataclass
class ProjectState:
    """项目运行状态（单一事实来源）。"""

    task: str = ""
    phase: str = PHASES[0]
    completed: list[str] = field(default_factory=list)
    current_agent: str = ""
    errors: list[str] = field(default_factory=list)

    def mark_completed(self, item: str) -> None:
        if item not in self.completed:
            self.completed.append(item)

    def record_error(self, message: str) -> None:
        self.errors.append(message)

    def advance_phase(self) -> str:
        """推进到下一阶段；已在最后阶段则原地返回。"""
        index = PHASES.index(self.phase)
        if index + 1 < len(PHASES):
            self.phase = PHASES[index + 1]
        return self.phase

    def rollback_to(self, phase: str) -> str:
        """回退到指定阶段（验收失败时使用，见 task_lifecycle.md 回退规则）。"""
        if phase not in PHASES:
            raise ValueError(f"unknown phase: {phase!r}")
        if PHASES.index(phase) > PHASES.index(self.phase):
            raise ValueError(f"cannot roll back forward: {self.phase} -> {phase}")
        self.phase = phase
        return self.phase

    def is_finished(self) -> bool:
        return self.phase == PHASES[-1] and PHASES[-1] in self.completed

    # --- 持久化 ---

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> ProjectState:
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            task=data.get("task", ""),
            phase=data.get("phase", PHASES[0]),
            completed=list(data.get("completed", [])),
            current_agent=data.get("current_agent", ""),
            errors=list(data.get("errors", [])),
        )

    def summary(self) -> str:
        """人类可读摘要，供上下文注入与日志。"""
        done = ", ".join(self.completed) if self.completed else "(none)"
        return (
            f"task: {self.task}\n"
            f"phase: {self.phase}\n"
            f"current_agent: {self.current_agent}\n"
            f"completed: {done}\n"
            f"errors: {len(self.errors)}"
        )
