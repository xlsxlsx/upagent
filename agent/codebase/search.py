"""代码检索（dev-notes/new.md「四、3. Embedding Code Search」的可落地版本）。

用户说「修改登录逻辑」→ 搜 login / auth / token / session →
找到 auth/service.py、middleware/token.py。

默认实现是关键词打分检索（纯标准库、零依赖）；
embedding 版通过注入 embed_fn 升级，接口不变。

make_snapshot_provider 把检索结果渲染成 Existing Code 快照，
接进 AgentLoop 主循环（Code Intelligence 骨架）。
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

# 轻量停用词：从任务标题提取检索关键词时过滤高频噪音词
_STOP_WORDS = frozenset(
    {
        "the", "and", "for", "with", "that", "this", "from", "into", "using",
        "have", "has", "are", "was", "were", "will", "should", "would", "could",
        "make", "implement", "create", "write", "build", "add", "update", "fix",
        "file", "files", "task", "code", "project", "test", "tests", "run",
        "python", "javascript", "typescript",
    }
)


@dataclass(frozen=True)
class SearchHit:
    """一条检索命中。"""

    path: str
    score: float
    preview: str  # 首个命中行


def keywords_from(text: str, max_terms: int = 8) -> list[str]:
    """从任务文本提取检索关键词（零依赖启发式）：停用词过滤 + 词频排序。"""
    tokens = re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", text.lower())
    freq: dict[str, int] = {}
    for token in tokens:
        if token in _STOP_WORDS:
            continue
        freq[token] = freq.get(token, 0) + 1
    ranked = sorted(freq.items(), key=lambda item: (-item[1], item[0]))
    return [word for word, _ in ranked[:max_terms]]


def render_snapshot(hits: list[SearchHit], max_chars: int = 3000) -> str:
    """把检索命中渲染成 Markdown 快照（注入上下文用），控制体积。"""
    lines: list[str] = []
    for hit in hits:
        lines.append(f"### {hit.path} (score={hit.score:.0f})")
        if hit.preview:
            lines.append(hit.preview)
    return "\n".join(lines)[:max_chars]


def make_snapshot_provider(
    root: Path,
    *,
    embed_fn: EmbedFn | None = None,
    limit: int = 5,
    max_chars: int = 3000,
) -> Callable[[str], str]:
    """构造 Existing Code 快照提供器：任务文本 -> 检索到的代码预览。"""

    search = CodeSearch(root, embed_fn=embed_fn)

    def snapshot(task: str) -> str:
        try:
            hits = search.search(keywords_from(task), limit=limit)
        except OSError:
            return ""
        if not hits:
            return ""
        return render_snapshot(hits, max_chars=max_chars)

    return snapshot


@dataclass
class CodeSearch:
    """项目内代码检索。默认关键词版；embed_fn 注入后可换向量版。"""

    root: Path
    embed_fn: EmbedFn | None = None
    _cache: dict[str, str] = field(default_factory=dict)
    _cache_meta: dict[str, tuple[int, int]] = field(default_factory=dict)
    _vector_index: object | None = field(init=False, default=None, repr=False)

    def refresh(self) -> None:
        """丢弃缓存强制重扫（文件被外部改动后调用）。"""
        self._cache.clear()
        self._cache_meta.clear()
        self._vector_index = None

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
        """遍历代码文件；缓存已读内容，磁盘变更时增量重读。"""
        root = self.root.resolve()
        if not self._cache:
            self._scan(root)
        else:
            changed = False
            for path in sorted(root.rglob("*")):
                rel_parts = path.relative_to(root).parts
                if any(part in _SKIP_DIRS for part in rel_parts):
                    continue
                if not path.is_file() or path.suffix not in _CODE_SUFFIXES:
                    continue
                try:
                    stat = path.stat()
                except OSError:
                    continue
                if stat.st_size > _MAX_FILE_BYTES:
                    continue
                rel = path.relative_to(root).as_posix()
                if self._cache_meta.get(rel) == (stat.st_size, stat.st_mtime_ns):
                    continue
                try:
                    self._cache[rel] = path.read_text(encoding="utf-8")
                    self._cache_meta[rel] = (stat.st_size, stat.st_mtime_ns)
                    changed = True
                except (OSError, UnicodeDecodeError):
                    continue
            if changed:
                self._vector_index = None  # 缓存变化后重建向量索引
        return list(self._cache.items())

    def _scan(self, root: Path) -> None:
        for path in sorted(root.rglob("*")):
            rel_parts = path.relative_to(root).parts
            if any(part in _SKIP_DIRS for part in rel_parts):
                continue
            if not path.is_file() or path.suffix not in _CODE_SUFFIXES:
                continue
            try:
                stat = path.stat()
                if stat.st_size > _MAX_FILE_BYTES:
                    continue
                rel = path.relative_to(root).as_posix()
                self._cache[rel] = path.read_text(encoding="utf-8")
                self._cache_meta[rel] = (stat.st_size, stat.st_mtime_ns)
            except (OSError, UnicodeDecodeError):
                continue

    @staticmethod
    def _first_match_line(text: str, term: str) -> str:
        pattern = re.compile(re.escape(term), re.IGNORECASE)
        for line in text.splitlines():
            if pattern.search(line):
                return line.strip()[:120]
        return ""
