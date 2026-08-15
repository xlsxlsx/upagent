"""依赖规划（new.md「五、重构 Planner」dependency_planner.py）。

    backend depends database
    frontend depends backend

给出实现子域之间的依赖关系与满足依赖的执行顺序（拓扑排序）。
"""

from __future__ import annotations

from graphlib import TopologicalSorter

# 默认子域依赖：key 依赖 value 中的各项
DEFAULT_DEPENDENCIES: dict[str, tuple[str, ...]] = {
    "backend": ("database",),
    "frontend": ("backend",),
    "testing": ("frontend", "backend", "database"),
}


def plan_dependencies(
    domains: list[str],
    extra: dict[str, tuple[str, ...]] | None = None,
) -> dict[str, tuple[str, ...]]:
    """返回本次涉及子域间的依赖表（只保留双方都在场的边）。"""
    table = dict(DEFAULT_DEPENDENCIES)
    if extra:
        table.update(extra)
    present = set(domains)
    return {
        domain: tuple(dep for dep in table.get(domain, ()) if dep in present)
        for domain in domains
    }


def execution_order(dependencies: dict[str, tuple[str, ...]]) -> list[str]:
    """拓扑排序出执行顺序；成环时抛 ValueError（规划错误应尽早暴露）。"""
    sorter: TopologicalSorter[str] = TopologicalSorter()
    for domain, deps in dependencies.items():
        sorter.add(domain, *deps)
    try:
        return list(sorter.static_order())
    except Exception as exc:  # graphlib.CycleError
        raise ValueError(f"dependency cycle detected: {exc}") from exc
