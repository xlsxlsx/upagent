"""执行计划（new.md「五、重构 Planner」execution_planner.py）。

把任务拆解、依赖关系、风险识别汇总成一份完整执行计划：

    project: ecommerce
    phases: requirement / architecture / ...
    tech_stack: Python FastAPI + PostgreSQL + React
    dependencies: backend depends database ...
    risk: payment security

供 Supervisor 调度与留档（render 输出 Markdown）。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from agent.planner.decomposition import decompose
from agent.planner.dependency_planner import execution_order, plan_dependencies
from agent.planner.risk_planner import AssessFn, Risk, assess_risks
from agent.planner.task_tree import TaskTree


@dataclass(frozen=True)
class ExecutionPlan:
    """一次任务的完整执行计划。"""

    task: str
    tree: TaskTree
    dependencies: dict[str, tuple[str, ...]]
    order: tuple[str, ...]  # 实现子域的依赖序
    risks: tuple[Risk, ...]
    tech_stack: str = ""  # 用户声明的技术栈（注入 Context 与文档）

    def render(self) -> str:
        """渲染为 Markdown，写入 memory/project_memory 或留档。"""
        lines = [f"# Execution Plan: {self.task}", ""]
        if self.tech_stack.strip():
            lines += ["## Tech Stack", "", self.tech_stack.strip(), ""]
        lines += ["## Task Tree", "", self.tree.render()]
        if self.dependencies:
            lines += ["", "## Dependencies", ""]
            for domain in sorted(self.dependencies):
                deps = self.dependencies[domain]
                lines.append(f"- {domain} depends: {', '.join(deps) if deps else '(none)'}")
            lines += ["", f"Execution order: {' -> '.join(self.order)}"]
        lines += ["", "## Risks", ""]
        for risk in self.risks:
            lines.append(f"- [{risk.level.upper()}] {risk.name}: {risk.mitigation}")
        return "\n".join(lines) + "\n"


def create_execution_plan(
    task: str,
    tech_stack: str | None = None,
    assess_fn: AssessFn | None = None,
    decompose_fn: Callable[..., TaskTree] = decompose,
) -> ExecutionPlan:
    """拆解 + 依赖排序 + 风险识别，一步生成执行计划。

    tech_stack 参与子域识别（见 decomposition._match_domains）。
    """
    try:
        tree = decompose_fn(task, tech_stack)
    except TypeError:
        tree = decompose_fn(task)
    implementation = next(
        (node for node in tree.flatten() if node.task_type == "implementation"), None
    )
    domains = [child.task_type for child in implementation.children] if implementation else []
    dependencies = plan_dependencies(domains)
    order = tuple(execution_order(dependencies)) if dependencies else ()
    # 按依赖序重排 Implementation 子节点，确保 next_task 顺序正确
    if implementation is not None and order:
        rank = {domain: index for index, domain in enumerate(order)}
        implementation.children.sort(key=lambda node: rank.get(node.task_type, len(rank)))
    risks = tuple(assess_risks(task, assess_fn))
    return ExecutionPlan(
        task=task,
        tree=tree,
        dependencies=dependencies,
        order=order,
        risks=risks,
        tech_stack=tech_stack or "",
    )