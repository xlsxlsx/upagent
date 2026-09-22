"""Embedding 代码检索骨架（dev-notes/new.md「四、3. Embedding Code Search」）。

零依赖实现：embed_fn（文本 → 向量）由外部注入，默认关键字检索不受影响。
- rag_keywords: 自然语言查询 → 去重关键词（供关键词版回退）
- cosine: 纯标准库余弦相似度
- VectorIndex: 对文件文本分块嵌入，查询时按余弦相似度排序

用法::

    index = VectorIndex.from_files(files, embed_fn)
    hits = index.retrieve("修改登录逻辑", limit=5)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from agent.codebase.search import EmbedFn, SearchHit

_CHUNK_SIZE = 1000  # 分块字符数


def rag_keywords(text: str) -> list[str]:
    """提取文本中的候选关键词（字母/下划线开头，长度 >= 3），保序去重。"""
    return list(dict.fromkeys(re.findall(r"[a-zA-Z_]\w{2,}", text.lower())))


def cosine(a: list[float], b: list[float]) -> float:
    """余弦相似度，纯标准库；维度不一致或零向量返回 0。"""
    if len(a) != len(b) or not a:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(y * y for y in b) ** 0.5
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def _chunk_preview(text: str) -> str:
    """分块文本的首个非空行作为预览。"""
    for line in text.splitlines():
        if line.strip():
            return line.strip()[:120]
    return ""


@dataclass(frozen=True)
class _Chunk:
    """一个文本分块及其向量。"""

    path: str
    offset: int
    vector: list[float]
    text: str

    @property
    def preview(self) -> str:
        return _chunk_preview(self.text)


@dataclass
class VectorIndex:
    """分块向量索引：build 后按余弦相似度检索。"""

    embed_fn: EmbedFn
    chunk_size: int = _CHUNK_SIZE
    _chunks: list[_Chunk] = field(default_factory=list, repr=False)

    @classmethod
    def from_files(
        cls,
        files: list[tuple[str, str]],
        embed_fn: EmbedFn,
        chunk_size: int = _CHUNK_SIZE,
    ) -> VectorIndex:
        """从 (path, text) 列表构建索引；embed_fn 返回空向量则跳过该块。"""
        index = cls(embed_fn=embed_fn, chunk_size=chunk_size)
        for path, text in files:
            for offset in range(0, len(text), chunk_size):
                chunk = text[offset : offset + chunk_size]
                vector = embed_fn(chunk)
                if vector:
                    index._chunks.append(_Chunk(path, offset, vector, chunk))
        return index

    def retrieve(self, query: str, limit: int = 5) -> list[SearchHit]:
        """查询文本 → 向量，返回相似度最高的 limit 个命中。"""
        if not query.strip() or not self._chunks:
            return []
        query_vector = self.embed_fn(query)
        scored = sorted(
            ((cosine(query_vector, c.vector), c) for c in self._chunks),
            key=lambda pair: (-pair[0], pair[1].path, pair[1].offset),
        )
        return [
            SearchHit(path=chunk.path, score=round(score, 6), preview=chunk.preview)
            for score, chunk in scored[:limit]
        ]