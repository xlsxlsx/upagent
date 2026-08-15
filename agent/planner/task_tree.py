"""Task Tree（new.md「6. Task Tree」）。

Agent 不应该一次完成，应该按任务树推进：

    Build Game Platform
        ├── Requirement
        ├── Architecture
        ├── Implementation
        │     ├── Frontend
        │     ├── Backend
        │     └── Database
        ├── Testing
        ├── Security Audit
        └── Deploy

每个节点有类型（供 Router 分派）与状态；树提供
「下一个可做的任务」查询：父节点在全部子节点完成前不算完成。

回退（workflow/task_lifecycle.md 回退规则）：任一阶段失败 →
把「问题产生阶段」及其后的节点重置为 PENDING，重新按序通过门禁。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from agent.core.state import PhaseStatus


@dataclass
class TaskNode:
    """任务树节点。task_type 供 Agent Router 决定派给谁。"""

    title: str
    task_type: str = "general"  # frontend / backend / database / testing / security ...
    status: PhaseStatus = PhaseStatus.PENDING
    children: list[TaskNode] = field(default_factory=list)

    def add(self, child: TaskNode) -> TaskNode:
        self.children.append(child)
        return child

    def is_done(self) -> bool:
        if self.children:
            return all(child.is_done() for child in self.children)
        return self.status == PhaseStatus.DONE


@dataclass
class TaskTree:
    """以 ROOT 为根的任务树。"""

    root: TaskNode

    def next_task(self) -> TaskNode | None:
        """深度优先找第一个未完成的叶子（执行顺序 = 依赖顺序）。"""
        return _first_pending_leaf(self.root)

    def is_finished(self) -> bool:
        return self.root.is_done()

    def flatten(self) -> list[TaskNode]:
        nodes: list[TaskNode] = []
        _collect(self.root, nodes)
        return nodes

    def rollback_to(self, origin_type: str) -> list[str]:
        """回退：把 task_type == origin_type 的节点及其后全部重置为 PENDING。

        返回被重置（此前非 PENDING）的节点标题列表；未找到该类型
        返回空列表（调用方视为「无可回退」）。
        """
        nodes = self.flatten()
        start = next(
            (i for i, node in enumerate(nodes) if node.task_type == origin_type), None
        )
        if start is None:
            return []
        reset = [n.title for n in nodes[start:] if n.status != PhaseStatus.PENDING]
        for node in nodes[start:]:
            node.status = PhaseStatus.PENDING
        return reset

    def render(self) -> str:
        """渲染为文本树，供日志与 project_memory 展示。"""
        lines: list[str] = []
        _render(self.root, 0, lines)
        return "\n".join(lines)


def _first_pending_leaf(node: TaskNode) -> TaskNode | None:
    if node.children:
        for child in node.children:
            found = _first_pending_leaf(child)
            if found is not None:
                return found
        return None
    return None if node.status == PhaseStatus.DONE else node


def _collect(node: TaskNode, out: list[TaskNode]) -> None:
    out.append(node)
    for child in node.children:
        _collect(child, out)


def _render(node: TaskNode, depth: int, lines: list[str]) -> None:
    mark = "x" if node.is_done() else " "
    lines.append(f"{'  ' * depth}[{mark}] {node.title} ({node.task_type})")
    for child in node.children:
        _render(child, depth + 1, lines)