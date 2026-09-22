"""Planner（dev-notes/new.md「5. Planner」）。

职责一：create_plan(task, tech_stack) → TaskTree（把大任务拆小）。
职责二：decide(thought) → Action（Agent Loop 的第三步）。

decide 的默认实现解析思考文本中的行动指令行：

    ACTION: <tool_name>
    ARG key=value
    ...
    （无 ACTION 行 → finish）

LLM 输出遵循该格式即可直接驱动循环；测试用桩思考文本同样适用。
"""

from __future__ import annotations

import inspect
from collections.abc import Callable
from dataclasses import dataclass, field

from agent.core.agent import Thought
from agent.core.loop import Action
from agent.planner.decomposition import decompose
from agent.planner.task_tree import TaskTree

DecomposeFn = Callable[[str], TaskTree]


@dataclass
class Planner:
    """任务规划器：拆解 + 行动决策。"""

    decompose_fn: DecomposeFn = field(default=decompose)

    def create_plan(self, task: str, tech_stack: str | None = None) -> TaskTree:
        """拆解任务；传入技术栈时优先让拆解函数感知技术栈。"""
        if tech_stack:
            parameters = inspect.signature(self.decompose_fn).parameters
            if "tech_stack" in parameters:
                return self.decompose_fn(task, tech_stack=tech_stack)
        return self.decompose_fn(task)

    def decide(self, thought: Thought) -> Action:
        """从思考文本解析行动；解析不到 ACTION 视为完成。"""
        kind = ""
        args: dict[str, str] = {}
        for raw in thought.content.splitlines():
            line = raw.strip()
            if line.upper().startswith("ACTION:"):
                kind = line.split(":", 1)[1].strip()
            elif line.upper().startswith("ARG ") and "=" in line:
                key, value = line[4:].split("=", 1)
                args[key.strip()] = value.strip()
        if not kind or kind.lower() == "finish":
            return Action.finish(note=thought.content[:100])
        return Action(kind=kind, args=args)