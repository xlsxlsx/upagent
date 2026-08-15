"""Code Intelligence Layer（new.md「四、Code Intelligence Layer」）。

LLM 不知道项目结构、文件关系、代码依赖、修改影响面，
容易生成垃圾代码。本包在每次编码前提供：

- analyzer.py         AST/正则分析：文件 → 类/函数/导入清单（Python + JS/TS）
- symbol_index.py     符号索引：符号名 → 定义位置
- dependency_graph.py 依赖图：谁导入了谁、改动影响面
- repository_map.py   仓库地图：生成 project_map.md
- search.py           代码检索：关键词版（embedding 版可注入替换）
- vector_index.py     Embedding 检索骨架：分块向量 + 余弦相似度
"""

from agent.codebase.analyzer import FileSummary, analyze_file, analyze_tree
from agent.codebase.dependency_graph import DependencyGraph
from agent.codebase.repository_map import RepositoryMap
from agent.codebase.search import CodeSearch, SearchHit
from agent.codebase.symbol_index import SymbolIndex
from agent.codebase.vector_index import VectorIndex, cosine, rag_keywords

__all__ = [
    "CodeSearch",
    "DependencyGraph",
    "FileSummary",
    "RepositoryMap",
    "SearchHit",
    "SymbolIndex",
    "VectorIndex",
    "analyze_file",
    "analyze_tree",
    "cosine",
    "rag_keywords",
]