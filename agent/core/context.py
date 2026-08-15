"""Context 管理（new.md「4. Context」）。

LLM 不知道整个项目，所以每次推理前要拼装上下文：

    Context = 用户需求 + 项目文件 + 历史决策 + 当前任务 + 代码状态

ContextBuilder 从 agent/ 配置、ProjectState 与 MemoryStore
组装出给单个 Agent 的完整输入。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from agent.core.agent import AGENT_ROOT

if TYPE_CHECKING:
    from agent.core.state import ProjectState
    from agent.memory.store import MemoryStore
    from agent.memory.tiers import MemoryTiers

# 每个知识文件注入的最大字符数，防止上下文爆炸
_KNOWLEDGE_LIMIT = 4000


@dataclass
class ContextBuilder:
    """为 Agent 拼装推理上下文。"""

    agent_root: Path = AGENT_ROOT
    knowledge_files: list[str] = field(default_factory=list)

    def build(
        self,
        *,
        user_task: str,
        state: ProjectState,
        memory: MemoryStore | None = None,
        tiers: MemoryTiers | None = None,
        current_task: str = "",
        code_snapshot: str = "",
        repo_map: str = "",
        history: list[str] | None = None,
    ) -> str:
        """按 new.md 的五要素组装上下文文本；history 注入最近执行步骤。"""
        sections: list[str] = [
            _section("User Task", user_task),
            _section("Project State", state.summary()),
        ]
        if repo_map:
            # Code Intelligence：编码前先看项目地图（codebase/repository_map.py）
            sections.append(_section("Repository Map", repo_map))
        if memory is not None:
            decisions = memory.recent_decisions()
            if decisions:
                sections.append(_section("Past Decisions", decisions))
            failures = memory.recent_failures()
            if failures:
                sections.append(_section("Known Failures", failures))
        if tiers is not None:
            # 三层记忆：短期 / 项目长期 / 跨项目（memory/tiers.py）
            for title, body in tiers.context_sections():
                sections.append(_section(title, body))
        for name in self.knowledge_files:
            content = self._read_knowledge(name)
            if content:
                sections.append(_section(f"Knowledge: {name}", content))
        if history:
            # 最近执行步骤（含失败原因），让 LLM 看到上一步反馈并自我纠错
            sections.append(_section("Recent Steps", "\n".join(history[-10:])))
        if current_task:
            sections.append(_section("Current Task", current_task))
        if code_snapshot:
            sections.append(_section("Existing Code", code_snapshot))
        return "\n\n".join(sections)

    def _read_knowledge(self, name: str) -> str:
        path = self.agent_root / "knowledge" / name
        if not path.is_file():
            return ""
        return path.read_text(encoding="utf-8")[:_KNOWLEDGE_LIMIT]


def _section(title: str, body: str) -> str:
    return f"## {title}\n{body.strip()}"
