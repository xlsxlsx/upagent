"""依赖图（dev-notes/new.md「四、Code Intelligence Layer」dependency_graph.py）。

谁导入了谁 → 修改影响面。修改一个模块前先问：
impacted_by(module) 有哪些文件会受影响。

以「项目内顶层模块/包名」为节点（外部第三方导入被忽略）。
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from agent.codebase.analyzer import FileSummary, analyze_tree


def _module_of(path: str) -> str:
    """文件相对路径 → 顶层模块/包名：auth/user.py → auth、app/service.ts → app。"""
    first = path.split("/", 1)[0]
    return first.rsplit(".", 1)[0] if "." in first else first


@dataclass
class DependencyGraph:
    """项目内部 import 关系图。"""

    # 模块 → 它导入的项目内模块
    imports: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))
    # 模块 → 导入它的项目内模块（反向边）
    imported_by: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))

    @classmethod
    def build(cls, summaries: list[FileSummary]) -> DependencyGraph:
        graph = cls()
        internal = {_module_of(s.path) for s in summaries}
        for summary in summaries:
            source = _module_of(summary.path)
            for target in summary.imports:
                if target in internal and target != source:
                    graph.imports[source].add(target)
                    graph.imported_by[target].add(source)
        return graph

    @classmethod
    def from_root(cls, root: Path) -> DependencyGraph:
        return cls.build(analyze_tree(root))

    def impacted_by(self, module: str) -> set[str]:
        """修改 module 会影响的全部模块（沿 imported_by 传递闭包）。"""
        seen: set[str] = set()
        frontier = [module]
        while frontier:
            current = frontier.pop()
            for dependent in self.imported_by.get(current, ()):
                if dependent not in seen:
                    seen.add(dependent)
                    frontier.append(dependent)
        return seen

    def render(self) -> str:
        """人类可读的「A imports B」清单，供 project_map.md 使用。"""
        lines = [
            f"{source} -> {target}"
            for source in sorted(self.imports)
            for target in sorted(self.imports[source])
        ]
        return "\n".join(lines)
