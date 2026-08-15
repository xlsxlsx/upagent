"""代码检索（new.md「四、3. Embedding Code Search」的可落地版本）。

用户说「修改登录逻辑」→ 搜 login / auth / token / session →
找到 auth/service.py、middleware/token.py。

默认实现是关键词打分检索（纯标准库、零依赖）；
embedding 版通过注入 embed_fn 升级，接口不变。
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from agent.codebase.analyzer import _SKIP_DIRS

# embedding 函数：文本 -> 向量；注入后启用向量相似度检索
EmbedFn = Callable[[str], list[float]]

_CODE_SUFFIXES = {".py", ".js", ".ts", ".tsx", ".jsx", ".md", ".html", ".sql"}
_MAX_FILE_BYTES = 512 * 1024


@dataclass(frozen=True)
class SearchHit:
    """一条检索命中。"""

    path: str
    score: float
    preview: str  # 首个命中行


@dataclass
class CodeSearch:
    """项目内代码检索。默认关键词版；embed_fn 注入后可换向量版。"""

    root: Path
    embed_fn: EmbedFn | None = None
    _cache: dict[str, str] = field(default_factory=dict)
    _vector_index: object | None = field(init=False, default=None, repr=False)

    def search(self, keywords: list[str], limit: int = 5) -> list[SearchHit]:
        """多关键词打分；注入 embed_fn 后走向量相似度检索。"""
        query = " ".join(k for k in keywords if k.strip())
        if not query:
            return []
        if self.embed_fn is not None:
            return self._vector_search(query, limit)
        terms = [k.lower() for k in keywords if k.strip()]
        if not terms:
            return []
        hits: list[SearchHit] = []
        for path, text in self._iter_files():
            lowered = text.lower()
            matched = [t for t in terms if t in lowered]
            if not matched:
                continue
            # 不同关键词命中数为主（*100），总出现次数为辅
            occurrences = sum(lowered.count(t) for t in matched)
            score = len(matched) * 100 + occurrences
            hits.append(
                SearchHit(path=path, score=score, preview=self._first_match_line(text, matched[0]))
            )
        hits.sort(key=lambda h: (-h.score, h.path))
        return hits[:limit]

    def _vector_search(self, query: str, limit: int) -> list[SearchHit]:
        """向量检索：复用 _iter_files 缓存构建 VectorIndex（惰性、只建一次）。"""
        from agent.codebase.vector_index import VectorIndex

        if self._vector_index is None:
            self._vector_index = VectorIndex.from_files(self._iter_files(), self.embed_fn)
        return self._vector_index.retrieve(query, limit)

    def _iter_files(self) -> list[tuple[str, str]]:
        if not self._cache:
            root = self.root.resolve()
            for path in sorted(root.rglob("*")):
                rel_parts = path.relative_to(root).parts
                if any(part in _SKIP_DIRS for part in rel_parts):
                    continue
                if not path.is_file() or path.suffix not in _CODE_SUFFIXES:
                    continue
                try:
                    if path.stat().st_size > _MAX_FILE_BYTES:
                        continue
                    self._cache[path.relative_to(root).as_posix()] = path.read_text(
                        encoding="utf-8"
                    )
                except (OSError, UnicodeDecodeError):
                    continue
        return list(self._cache.items())

    @staticmethod
    def _first_match_line(text: str, term: str) -> str:
        pattern = re.compile(re.escape(term), re.IGNORECASE)
        for line in text.splitlines():
            if pattern.search(line):
                return line.strip()[:120]
        return ""
