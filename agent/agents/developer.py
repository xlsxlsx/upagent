"""Developer Agent — 最关键的 Code Agent（dev-notes/new.md「10. Code Agent」）。

流程：读取需求 → 读取架构 → 读取已有代码 → 生成修改计划 →
修改代码 → 运行测试 → 修复错误 → 提交。

Prompt 来自 roles/backend_engineer.md + knowledge/coding_standard.md
+ workflow/development.md（通过 ContextBuilder 注入知识文件）。
写码-测试-修复循环与 Reflection Agent 协作（dev-notes/new.md「11.」）。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from agent.core.agent import Agent
from agent.core.context import ContextBuilder
from agent.core.loop import AgentLoop
from agent.core.state import ProjectState
from agent.memory.store import MemoryStore
from agent.planner.planner import Planner
from agent.reflection.reflector import Reflector
from agent.tools.base import ToolResult


@dataclass(frozen=True)
class DevResult:
    """一次开发任务的最终结果。"""

    finished: bool
    test_passed: bool
    attempts: int
    detail: str


@dataclass
class DeveloperAgent:
    """写码 → 测试 → 反思修复 的执行器。

    inner 是配置为工程师角色（如 backend_engineer.md）的核心 Agent，
    必须带 file / terminal 工具。
    """

    inner: Agent
    planner: Planner
    state: ProjectState
    memory: MemoryStore | None = None
    reflector: Reflector | None = None
    test_command: str = "pytest"
    max_fix_rounds: int = 3  # 修复轮数上限，防死循环
    context_builder: ContextBuilder = field(
        default_factory=lambda: ContextBuilder(
            knowledge_files=["coding_standard.md", "security_rule.md"]
        )
    )

    def develop(self, task: str) -> DevResult:
        """执行完整开发循环：实现 → 测试 → 反思修复（最多 N 轮，每轮修复后必重测）。"""
        loop = AgentLoop(
            agent=self.inner,
            decide_fn=self.planner.decide,
            state=self.state,
            memory=self.memory,
            context_builder=self.context_builder,
        )
        result = loop.run(task)
        if not result.finished:
            return DevResult(False, False, 0, "implementation did not converge")

        test = self._run_tests()
        if test.ok:
            return DevResult(True, True, 1, test.output[-500:])

        # 测试失败 → Reflection 修复循环：每轮修复后重新跑测试验证
        for round_no in range(1, self.max_fix_rounds + 1):
            if self.reflector is None:
                return DevResult(True, False, round_no, test.output[-500:])
            fix_task = self.reflector.plan_fix(task, test.output)
            fix_run = loop.run(fix_task)
            if not fix_run.finished:
                self._record_failure(task, f"fix loop did not converge (round {round_no})")
                return DevResult(True, False, round_no, "fix loop did not converge")
            test = self._run_tests()
            if test.ok:
                return DevResult(True, True, round_no + 1, test.output[-500:])
        # 修复轮数耗尽：记录失败教训（Rule 6 / failure_memory）
        self._record_failure(task, f"exceeded {self.max_fix_rounds} fix rounds")
        return DevResult(True, False, self.max_fix_rounds + 1, "fix rounds exhausted")

    def _record_failure(self, task: str, what: str) -> None:
        if self.memory is not None:
            self.memory.append_failure(
                title=f"tests still failing: {task[:60]}",
                what=what,
                lesson="拆小任务或回退架构阶段，不再原地重试",
                role=self.inner.name,
            )

    def _run_tests(self) -> ToolResult:
        terminal = self.inner.find_tool("terminal")
        return terminal.run(command=self.test_command)
