"""MemoryStore — 把 memory/*.md 变成可读写的运行时记忆。

对应三个记忆文件（agent/memory/）：
- decision_log.md   决策日志（只追加）
- failure_memory.md 失败教训（只追加）
- 运行历史          history.jsonl（本模块新增的机器可读流水）

写入遵循原有 Markdown 的条目模板；读取只取尾部若干条，
避免把整个日志灌进上下文。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from agent.core.agent import AGENT_ROOT

# 注入上下文时各取最近 N 条，控制体积
_RECENT_LIMIT = 5


@dataclass
class MemoryStore:
    """agent/memory/ 目录的读写门面。"""

    root: Path = field(default_factory=lambda: AGENT_ROOT / "memory")

    # --- 决策日志 ---

    def append_decision(self, title: str, decision: str, reason: str, role: str) -> None:
        """按 decision_log.md 的条目模板追加一条决策。"""
        number = self._next_number("decision_log.md", "## D-")
        entry = (
            f"\n## D-{number}: {title}\n\n"
            f"Decision:\n{decision}\n\n"
            f"Reason:\n{reason}\n\n"
            f"Status: Active\n\n"
            f"Date: {date.today().isoformat()}\n"
            f"Role: {role}\n"
        )
        self._append("decision_log.md", entry)

    def recent_decisions(self, limit: int = _RECENT_LIMIT) -> str:
        return self._tail_entries("decision_log.md", "## D-", limit)

    # --- 失败记忆 ---

    def append_failure(self, title: str, what: str, lesson: str, role: str) -> None:
        """按 failure_memory.md 的条目模板追加一条教训。"""
        number = self._next_number("failure_memory.md", "## F-")
        entry = (
            f"\n## F-{number}: {title}\n\n"
            f"What Happened:\n{what}\n\n"
            f"Lesson (可执行的规避动作):\n{lesson}\n\n"
            f"Date: {date.today().isoformat()}\n"
            f"Role: {role}\n"
        )
        self._append("failure_memory.md", entry)

    def recent_failures(self, limit: int = _RECENT_LIMIT) -> str:
        return self._tail_entries("failure_memory.md", "## F-", limit)

    # --- 运行历史（机器可读） ---

    def append_history(self, agent_name: str, entry: str) -> None:
        line = json.dumps({"agent": agent_name, "entry": entry}, ensure_ascii=False)
        path = self.root / "history.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")

    def load_history(self) -> list[dict[str, str]]:
        path = self.root / "history.jsonl"
        if not path.is_file():
            return []
        records: list[dict[str, str]] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                records.append(json.loads(line))
        return records

    # --- 内部工具 ---

    def _append(self, name: str, text: str) -> None:
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(text)

    def _next_number(self, name: str, marker: str) -> int:
        path = self.root / name
        if not path.is_file():
            return 1
        lines = path.read_text(encoding="utf-8").splitlines()
        # 与 _tail_entries 一致：模板示例在 ``` 代码块里，不计入编号
        count = sum(
            1
            for index, line in enumerate(lines)
            if line.startswith(marker) and not _inside_code_block(lines, index)
        )
        return count + 1

    def _tail_entries(self, name: str, marker: str, limit: int) -> str:
        """取文件尾部最近 limit 个条目（以 marker 开头分段）。"""
        path = self.root / name
        if not path.is_file():
            return ""
        lines = path.read_text(encoding="utf-8").splitlines()
        starts = [i for i, line in enumerate(lines) if line.startswith(marker)]
        # 跳过模板示例：模板都写在 ``` 代码块里，真实条目在分隔线之后
        real_starts = [i for i in starts if not _inside_code_block(lines, i)]
        if not real_starts:
            return ""
        begin = real_starts[-limit] if len(real_starts) >= limit else real_starts[0]
        return "\n".join(lines[begin:]).strip()


def _inside_code_block(lines: list[str], index: int) -> bool:
    fences = sum(1 for line in lines[:index] if line.strip().startswith("```"))
    return fences % 2 == 1
