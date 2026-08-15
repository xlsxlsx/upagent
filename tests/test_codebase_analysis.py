"""codebase 扩展测试：JS/TS 启发式分析 + embedding 检索骨架。"""

from __future__ import annotations

from pathlib import Path

import pytest
from agent.codebase.analyzer import analyze_file, analyze_tree
from agent.codebase.search import CodeSearch
from agent.codebase.vector_index import VectorIndex, cosine, rag_keywords


def _dummy_embed(text: str) -> list[float]:
    """确定性伪嵌入：26 个英文字母的出现频次，零依赖可复现。"""
    vec = [0.0] * 26
    for ch in text.lower():
        if "a" <= ch <= "z":
            vec[ord(ch) - ord("a")] += 1.0
    return vec


def test_cosine_math() -> None:
    assert cosine([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)
    assert cosine([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)
    assert cosine([], []) == 0.0
    assert cosine([1.0], [1.0, 2.0]) == 0.0


def test_rag_keywords_extracts_and_dedupes() -> None:
    assert rag_keywords("修改 login 逻辑与 auth token") == ["login", "auth", "token"]
    assert rag_keywords("") == []


def test_analyze_js_file(tmp_path: Path) -> None:
    root = tmp_path / "web"
    (root / "components").mkdir(parents=True)
    (root / "components" / "Button.jsx").write_text(
        "/** Primary button component. */\n"
        "import React from 'react';\n"
        "import { login } from '../auth/service';\n"
        "export default class Button extends React.Component {}\n"
        "export function renderButton() {}\n"
        "export const onClick = (e) => e;\n",
        encoding="utf-8",
    )
    summary = analyze_file(root / "components" / "Button.jsx", root)
    assert not summary.parse_error
    assert "Button" in summary.classes
    assert {"renderButton", "onClick"} <= set(summary.functions)
    assert {"react", "auth"} <= set(summary.imports)
    assert summary.doc == "Primary button component."
    assert summary.to_dict()["file"] == "components/Button.jsx"


def test_analyze_tree_includes_js_and_ts(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("def hello():\n    pass\n", encoding="utf-8")
    (tmp_path / "b.ts").write_text("export function world() {}\n", encoding="utf-8")
    summaries = {s.path: s for s in analyze_tree(tmp_path)}
    assert "a.py" in summaries and "b.ts" in summaries
    assert "world" in summaries["b.ts"].functions


def test_vector_index_retrieval(tmp_path: Path) -> None:
    files = [
        ("auth/service.py", "def login():\n    verify token and session\n"),
        ("ui/page.js", "const page = () => <div>home</div>;\n"),
    ]
    index = VectorIndex.from_files(files, _dummy_embed)
    hits = index.retrieve("login token")
    assert hits and hits[0].path == "auth/service.py"
    assert index.retrieve("") == []


def test_code_search_vector_branch(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text(
        "def login():\n    token = check_session()\n", encoding="utf-8"
    )
    (tmp_path / "b.py").write_text("def home():\n    return 'index'\n", encoding="utf-8")
    vector_hits = CodeSearch(root=tmp_path, embed_fn=_dummy_embed).search(["login", "token"])
    assert vector_hits and vector_hits[0].path == "a.py"
    assert CodeSearch(root=tmp_path, embed_fn=_dummy_embed).search([]) == []
    keyword_hits = CodeSearch(root=tmp_path).search(["login"])
    assert keyword_hits and keyword_hits[0].path == "a.py"