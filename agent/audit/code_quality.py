"""代码质量检查器（new.md「十一、第八阶段：Audit Agent 重构」）。

聚焦维护性初级信号：遗留 TODO/FIXME 注释。
复用 scanning.scan_lines 逐行扫描，零依赖正则。
"""

from __future__ import annotations

import re
from pathlib import Path

from agent.audit.scanning import Pattern, scan_lines

# 支持 Python(#)、JS/TS(//、/* */) 三种注释形态
TODO_PATTERN = re.compile(r"(#|//|/\*)\s*(TODO|FIXME)")

_PATTERNS: list[Pattern] = [
    ("TODO/FIXME left", "low", TODO_PATTERN),
]


def check_code_quality(project_root: Path, max_files: int = 500) -> list:
    """扫描 TODO/FIXME 遗留注释，产出 code 类发现。"""
    return scan_lines(project_root, _PATTERNS, max_files, category="code")