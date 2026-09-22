"""AST 分析（dev-notes/new.md「四、2. AST 分析」）。

Python 文件 → ast 结构化摘要；JS/TS/TSX/JSX → 零依赖正则启发式。
两者输出统一的 FileSummary（classes/functions/imports/doc），
语法错误的文件降级为空摘要而非崩溃。
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path

# 跳过的目录：虚拟环境、缓存、版本库
_SKIP_DIRS = {".git", ".venv", "__pycache__", "node_modules", ".mypy_cache", "dist", "build"}

# 语言分派：Python 走 AST，JS 系走正则
_PY_SUFFIXES = {".py"}
_JS_SUFFIXES = {".js", ".ts", ".tsx", ".jsx"}
_SUPPORTED_SUFFIXES = _PY_SUFFIXES | _JS_SUFFIXES

# --- JS/TS 零依赖启发式 ---

_JS_FUNCTION_RE = re.compile(r"\b(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_$][\w$]*)\s*\(")
_JS_ARROW_RE = re.compile(
    r"\b(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*"
    r"(?:async\s*)?(?:\([^)]*\)|[A-Za-z_$][\w$]*)\s*=>"
)
_JS_FUNC_EXPR_RE = re.compile(
    r"\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?function\b"
)
_JS_CLASS_RE = re.compile(r"\b(?:export\s+)?(?:default\s+)?class\s+([A-Za-z_$][\w$]*)")
_JS_IMPORT_RE = re.compile(r"""import\s+.*?from\s+['"]([^'"]+)['"]""")
_JS_REQUIRE_RE = re.compile(r"""require\s*\(\s*['"]([^'"]+)['"]""")
_JS_DOC_RE = re.compile(r"/\*\*(.*?)\*/", re.DOTALL)


def _import_module(spec: str) -> str:
    """import 路径 → 顶层模块名：'../auth/service' → 'auth'、'react' → 'react'。"""
    cleaned = spec.strip().strip("'\"")
    if cleaned.startswith("."):
        cleaned = cleaned.lstrip("./")
    first = cleaned.split("/", 1)[0]
    return first.split(".", 1)[0]


def _js_doc(text: str) -> str:
    """取第一个 /** */ 注释块的首行内容作为摘要。"""
    match = _JS_DOC_RE.search(text)
    if not match:
        return ""
    lines = match.group(1).strip().splitlines()
    if not lines:
        return ""
    return lines[0].strip().lstrip("*").strip()


def _analyze_js(path: Path, root: Path) -> FileSummary:
    """JS/TS 正则启发式：类、函数、import、JSDoc 首行。"""
    rel = path.relative_to(root).as_posix()
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return FileSummary(path=rel, parse_error=True)

    classes = list(dict.fromkeys(_JS_CLASS_RE.findall(text)))
    functions = list(dict.fromkeys(_JS_FUNCTION_RE.findall(text)))
    functions.extend(
        name for name in _JS_ARROW_RE.findall(text) if name not in functions
    )
    functions.extend(
        name for name in _JS_FUNC_EXPR_RE.findall(text) if name not in functions
    )
    imports = list(
        dict.fromkeys(
            _import_module(spec)
            for match in (_JS_IMPORT_RE.findall(text) + _JS_REQUIRE_RE.findall(text))
            for spec in (match,)
        )
    )
    return FileSummary(
        path=rel,
        classes=tuple(classes),
        functions=tuple(functions),
        imports=tuple(imports),
        doc=_js_doc(text),
    )


@dataclass(frozen=True)
class FileSummary:
    """一个源文件的结构摘要。

    输出形如 dev-notes/new.md 的示例：

        {file: "user.py", functions: ["login", "register"]}
    """

    path: str  # 相对项目根的 POSIX 路径
    classes: tuple[str, ...] = ()
    functions: tuple[str, ...] = ()
    imports: tuple[str, ...] = ()  # 被导入的顶层模块名
    doc: str = ""
    parse_error: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "file": self.path,
            "classes": list(self.classes),
            "functions": list(self.functions),
            "imports": list(self.imports),
        }


def analyze_file(path: Path, root: Path) -> FileSummary:
    """按后缀分派分析；解析失败返回带 parse_error 标记的空摘要。"""
    rel = path.relative_to(root).as_posix()
    suffix = path.suffix.lower()
    if suffix in _JS_SUFFIXES:
        return _analyze_js(path, root)
    if suffix not in _PY_SUFFIXES:
        return FileSummary(path=rel, parse_error=True)
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError, OSError):
        return FileSummary(path=rel, parse_error=True)

    classes: list[str] = []
    functions: list[str] = []
    imports: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            classes.append(node.name)
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            functions.append(node.name)
        elif isinstance(node, ast.Import):
            imports.extend(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            imports.append(node.module.split(".")[0])
    doc = ast.get_docstring(tree) or ""
    return FileSummary(
        path=rel,
        classes=tuple(classes),
        functions=tuple(functions),
        imports=tuple(dict.fromkeys(imports)),  # 去重保序
        doc=doc.splitlines()[0] if doc else "",
    )


def analyze_tree(root: Path, max_files: int = 2000) -> list[FileSummary]:
    """递归分析项目内全部受支持源文件（跳过虚拟环境等目录）。"""
    summaries: list[FileSummary] = []
    root = root.resolve()
    for path in sorted(root.rglob("*")):
        if len(summaries) >= max_files:
            break
        if path.suffix.lower() not in _SUPPORTED_SUFFIXES:
            continue
        if any(part in _SKIP_DIRS for part in path.relative_to(root).parts):
            continue
        summaries.append(analyze_file(path, root))
    return summaries