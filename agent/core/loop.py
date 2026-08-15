"""Agent Loop — 最核心部分（new.md「2. Agent Loop」）。

    while task_not_finished:
        context = memory.load()
        thought = agent.reason(task, context)
        action  = planner.decide(thought)
        result  = execute(action)
        memory.save(result)

循环协议由 AgentLoop 实现；「决定行动」由可注入的 decide_fn 提供
（默认由 planner.Planner.decide 承担），执行由 Agent 的工具完成。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from agent.core.agent import Agent, Thought
from agent.core.context import ContextBuilder
from agent.core.state import ProjectState
from agent.tools.base import ToolResult

if TYPE_CHECKING:
    from agent.memory.store import MemoryStore

# 仓库地图提供者：每次编码前读取项目结构（codebase/repository_map.py）
RepoMapProvider = Callable[[], str]


@dataclass(frozen=True)
class Action:
    """一次可执行的行动：调用哪个工具、带什么参数。

    kind="finish" 表示当前任务完成，退出循环。
    """

    kind: str  # 工具名，或 "finish"
    args: dict[str, str] = field(default_factory=dict)
    note: str = ""

    @classmethod
    def finish(cls, note: str = "") -> Action:
        return cls(kind="finish", note=note)


# 决策函数：思考 → 行动（生产环境由 Planner/LLM 提供）
DecideFn = Callable[[Thought], Action]
# 一步式（思考+决策合并）：(agent_name, role_prompt, task, context) -> (Thought, Action)
StepFn = Callable[[str, str, str, str], tuple[Thought, Action]]


@dataclass(frozen=True)
class LoopResult:
    """一轮循环运行的结果。"""

    steps: int
    finished: bool
    history: tuple[str, ...]


@dataclass
class AgentLoop:
    """主控制循环。"""

    agent: Agent
    decide_fn: DecideFn
    state: ProjectState
    memory: MemoryStore | None = None
    context_builder: ContextBuilder = field(default_factory=ContextBuilder)
    max_steps: int = 10  # 防失控上限（收敛控制）
    repo_map_provider: RepoMapProvider | None = None  # Code Intelligence 注入
    step_fn: StepFn | None = None  # 一步式 reason+decide（LLM 版快路径，可选）

    def run(self, task: str) -> LoopResult:
        """对单个任务执行 思考→决策→执行→记录 循环，直到 finish。

        兜底规则：连续两次「相同工具 + 相同参数且成功」视为重复劳动，
        强制 finish，防止 LLM 反复执行同一动作。
        """
        history: list[str] = []
        last_success: tuple[str, frozenset[tuple[str, str]]] | None = None
        self.state.current_agent = self.agent.name
        for step in range(1, self.max_steps + 1):
            # 第一步：读取当前状态，拼装上下文（含 Repository Map）
            context = self.context_builder.build(
                user_task=self.state.task or task,
                state=self.state,
                memory=self.memory,
                current_task=task,
                repo_map=self.repo_map_provider() if self.repo_map_provider else "",
                history=history,
            )
            # 步数压力提示：让 LLM 在预算内收敛，避免无意义重复
            context += f"\n\n## Progress\nStep {step}/{self.max_steps} for this task. " \
                       "Finish as soon as the goal is met; avoid repeating successful steps."
            # 第二步：Agent 思考；第三步：决定行动
            # 快路径：step_fn 一次调用完成「思考+决策」；慢路径：reason + decide 两次调用
            if self.step_fn is not None:
                thought, action = self.step_fn(
                    self.agent.name, self.agent.role_prompt(), task, context
                )
            else:
                thought = self.agent.reason(task, context)
                action = self.decide_fn(thought)
            if action.kind == "finish":
                history.append(f"step {step}: finish ({action.note})")
                self.state.mark_completed(task)
                self._persist(history[-1])
                return LoopResult(steps=step, finished=True, history=tuple(history))
            # 第四步：执行工具
            result = self._execute(action)
            status = "ok" if result.ok else "fail"
            brief_args = {k: v for k, v in action.args.items() if k != "content"}
            args_text = ", ".join(f"{k}={v[:60]}" for k, v in brief_args.items())
            entry = f"step {step}: {action.kind} -> {status}"
            if args_text:
                entry += f" [{args_text}]"
            if not result.ok:
                # 失败原因反馈给下一轮，LLM 才能针对性修正
                entry += f": {result.output[:200]}"
            history.append(entry)
            if not result.ok:
                self.state.record_error(f"{action.kind}: {result.output[:200]}")
            self._persist(entry)
            # 兜底：连续两次相同成功动作 → 强制 finish
            if result.ok:
                action_key = (action.kind, frozenset(action.args.items()))
                if action_key == last_success:
                    finish_entry = (
                        f"step {step}: auto-finish "
                        f"(repeated identical successful action: {action.kind})"
                    )
                    history.append(finish_entry)
                    self._persist(finish_entry)
                    self.state.mark_completed(task)
                    return LoopResult(steps=step, finished=True, history=tuple(history))
                last_success = action_key
        return LoopResult(steps=self.max_steps, finished=False, history=tuple(history))

    def _execute(self, action: Action) -> ToolResult:
        # LLM 可能决策出未注册的工具名：转为失败记录，不炸掉循环
        try:
            tool = self.agent.find_tool(action.kind)
        except KeyError as exc:
            return ToolResult.failure(f"unknown tool: {exc}")
        return tool.run(**action.args)

    def _persist(self, entry: str) -> None:
        if self.memory is not None:
            self.memory.append_history(self.agent.name, entry)
