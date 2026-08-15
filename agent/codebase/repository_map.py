"""Repository Map（new.md「四、1. Repository Map」）。

类似 Cursor / Claude Code：生成 project_map.md，
Agent 每次编码前读取 → 注入 Context → LLM。

内容 = 目录树（带类/函数摘要）+ 内部依赖关系。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from agent.codebase.analyzer import FileSummary, analyze_tree
from agent.codebase.dependency_graph import DependencyGraph

# 注入上下文时的字符上限，防止大仓库撑爆 Prompt
_RENDER_LIMIT = 8000


@dataclass
class RepositoryMap:
    """项目结构地图：树形清单 + import 关系。"""

    root: Path
    summaries: list[FileSummary] = field(default_factory=list)

    @classmethod
    def scan(cls, root: Path) -> RepositoryMap:
        return cls(root=root, summaries=analyze_tree(root))

    def render(self, limit: int = _RENDER_LIMIT) -> str:
        """渲染为 Markdown 文本（超限截断并标注）。"""
        lines: list[str] = ["# Project Map", "", "## Files", ""]
        for summary in self.summaries:
            parts: list[str] = []
            if summary.classes:
                parts.append("classes: " + ", ".join(summary.classes))
            if summary.functions:
                parts.append("functions: " + ", ".join(summary.functions))
            if summary.parse_error:
                parts.append("(parse error)")
            detail = f"  ({'; '.join(parts)})" if parts else ""
            lines.append(f"- {summary.path}{detail}")
        graph = DependencyGraph.build(self.summaries)
        edges = graph.render()
        if edges:
            lines += ["", "## Internal Imports", "", edges]
        text = "\n".join(lines) + "\n"
        if len(text) > limit:
            text = text[:limit] + "\n... (truncated)\n"
        return text

    def write(self, path: Path | None = None) -> Path:
        """写出 project_map.md（默认放在项目根）。"""
        target = path or (self.root / "project_map.md")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(self.render(), encoding="utf-8")
        return target
