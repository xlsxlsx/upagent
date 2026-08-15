"""检查器共享的逐行扫描工具（零依赖）。"""

from __future__ import annotations

import re
from pathlib import Path

from agent.audit.types import AuditFinding

# 参与静态扫描的代码文件后缀
CODE_SUFFIXES = {".py", ".js", ".ts", ".tsx", ".jsx", ".sql", ".html"}
# 跳过目录（与 codebase 分析保持一致，避免扫虚拟环境）
_SKIP_DIRS = {".git", ".venv", "__pycache__", "node_modules", ".mypy_cache", "dist", "build"}

# 正则模式：(名称, 严重级别, 正则)
Pattern = tuple[str, str, re.Pattern[str]]


def scan_lines(
    project_root: Path,
    patterns: list[Pattern],
    max_files: int = 500,
    *,
    category: str = "code",
) -> list[AuditFinding]:
    """对项目内代码文件逐行匹配正则 → 审计发现。"""
    findings: list[AuditFinding] = []
    for path in iter_source_files(project_root, max_files):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            for name, severity, pattern in patterns:
                if pattern.search(line):
                    findings.append(
                        AuditFinding(
                            category=category,
                            severity=severity,
                            location=f"{path.relative_to(project_root)}:{lineno}",
                            description=name,
                        )
                    )
    return findings


def iter_source_files(project_root: Path, max_files: int = 500) -> list[Path]:
    """列出项目内待扫描的代码文件（跳过虚拟环境/缓存目录）。"""
    files: list[Path] = []
    root = project_root.resolve()
    for path in sorted(root.rglob("*")):
        if len(files) >= max_files:
            break
        if not path.is_file() or path.suffix not in CODE_SUFFIXES:
            continue
        rel_parts = path.relative_to(root).parts
        if any(part in _SKIP_DIRS for part in rel_parts):
            continue
        files.append(path)
    return files