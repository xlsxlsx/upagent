"""符号索引（dev-notes/new.md「四、Code Intelligence Layer」symbol_index.py）。

符号名 → 定义位置列表，供「这个函数/类定义在哪」的快速查询。
基于 analyzer 的 FileSummary 构建，不重复解析。
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from agent.codebase.analyzer import FileSummary, analyze_tree


@dataclass
class SymbolIndex:
    """符号（类名 / 函数名）→ 定义所在文件的倒排索引。"""

    _defs: dict[str, list[str]] = field(default_factory=lambda: defaultdict(list))

    @classmethod
    def build(cls, summaries: list[FileSummary]) -> SymbolIndex:
        index = cls()
        for summary in summaries:
            for symbol in (*summary.classes, *summary.functions):
                index._defs[symbol].append(summary.path)
        return index

    @classmethod
    def from_root(cls, root: Path) -> SymbolIndex:
        return cls.build(analyze_tree(root))

    def locate(self, symbol: str) -> list[str]:
        """返回定义该符号的文件列表（可能多处同名）。"""
        return list(self._defs.get(symbol, []))

    def defines(self, symbol: str) -> bool:
        return symbol in self._defs

    def all_symbols(self) -> list[str]:
        return sorted(self._defs)
