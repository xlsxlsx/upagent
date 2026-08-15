"""Agent Router（new.md「7. Agent Router」）。

决定哪个 Agent 干什么：

    if task.type == "database": return DatabaseAgent
    if task.type == "frontend": return FrontendAgent

默认按 task_type → Agent 的注册表匹配；更高级的做法是
注入 llm_route_fn，用 LLM 判断「这个任务需要谁」。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from agent.core.agent import Agent
from agent.planner.task_tree import TaskNode

# LLM 路由函数：(任务标题, 候选 Agent 名列表) -> 选中的 Agent 名
LlmRouteFn = Callable[[str, list[str]], str]

# task_type → 默认角色名映射（与 roles/ 对应）
DEFAULT_TYPE_MAP: dict[str, str] = {
    "general": "Backend",  # LLM 拆解出的通用开发任务交给 Backend（工具最全）
    "requirement": "ProductManager",
    "architecture": "Architect",
    "frontend": "Frontend",
    "backend": "Backend",
    "database": "Database",
    "testing": "Tester",
    "security": "Security",
    "review": "Reviewer",
    "deploy": "DevOps",
}


@dataclass
class AgentRouter:
    """task_type → Agent 的调度器。"""

    agents: dict[str, Agent] = field(default_factory=dict)
    type_map: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_TYPE_MAP))
    llm_route_fn: LlmRouteFn | None = None

    def register(self, agent: Agent) -> None:
        self.agents[agent.name] = agent

    def route(self, task: TaskNode) -> Agent:
        """为任务节点选择 Agent；规则未命中时回落到 LLM 判断。"""
        name = self.type_map.get(task.task_type, "")
        if name and name in self.agents:
            return self.agents[name]
        if self.llm_route_fn is not None:
            picked = self.llm_route_fn(task.title, list(self.agents))
            if picked in self.agents:
                return self.agents[picked]
        raise LookupError(
            f"no agent for task {task.title!r} (type={task.task_type!r}); "
            f"registered: {sorted(self.agents)}"
        )
