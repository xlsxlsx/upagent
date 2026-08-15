"""三层记忆（new.md「八、Memory 升级」）。

- ShortTermMemory   短期：当前任务在做什么（进程内，任务结束即弃）
- ProjectMemory     项目长期：数据库用 PostgreSQL、认证用 JWT
                    （落盘 project_facts.md，与 project_memory.md 模板区分）
- KnowledgeMemory   跨项目：JWT 最佳实践、React 性能优化
                    （落盘 knowledge_memory.md）

MemoryTiers 聚合三层，context_sections() 供 ContextBuilder 注入。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from agent.core.agent import AGENT_ROOT

# 注入上下文时每层的最大字符数
_TIER_LIMIT = 2000


@dataclass
class ShortTermMemory:
    """当前任务的工作记忆：今天正在修改登录。"""

    notes: list[str] = field(default_factory=list)
    limit: int = 20  # 只保留最近 N 条

    def note(self, text: str) -> None:
        self.notes.append(text)
        del self.notes[: -self.limit]

    def recall(self) -> str:
        return "\n".join(f"- {n}" for n in self.notes)

    def clear(self) -> None:
        self.notes.clear()


@dataclass
class _FileMemory:
    """落盘的追加式记忆：一行一条事实。"""

    path: Path

    def remember(self, fact: str) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        existing = self._lines()
        if fact.strip() and fact.strip() not in existing:
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(f"- {fact.strip()}\n")

    def recall(self, limit_chars: int = _TIER_LIMIT) -> str:
        return "\n".join(f"- {line}" for line in self._lines())[:limit_chars]

    def _lines(self) -> list[str]:
        if not self.path.is_file():
            return []
        return [
            line.strip().removeprefix("- ")
            for line in self.path.read_text(encoding="utf-8").splitlines()
            if line.strip().startswith("- ")
        ]


class ProjectMemory(_FileMemory):
    """项目长期记忆：技术选型、约定等（跟着项目走）。"""


class KnowledgeMemory(_FileMemory):
    """跨项目知识记忆：最佳实践、通用经验（跟着 Agent 走）。"""


@dataclass
class MemoryTiers:
    """三层记忆聚合。"""

    short_term: ShortTermMemory = field(default_factory=ShortTermMemory)
    project: ProjectMemory = field(
        default_factory=lambda: ProjectMemory(AGENT_ROOT / "memory" / "project_facts.md")
    )
    knowledge: KnowledgeMemory = field(
        default_factory=lambda: KnowledgeMemory(AGENT_ROOT / "memory" / "knowledge_memory.md")
    )

    def context_sections(self) -> list[tuple[str, str]]:
        """非空层 → (标题, 内容)，供 ContextBuilder 注入。"""
        sections: list[tuple[str, str]] = []
        for title, body in (
            ("Short-Term Memory", self.short_term.recall()),
            ("Project Memory", self.project.recall()),
            ("Knowledge Memory", self.knowledge.recall()),
        ):
            if body:
                sections.append((title, body))
        return sections
