"""性能检查器（dev-notes/new.md「十一、Audit Agent 重构」）。

零依赖轻量启发式（不做真实 profiling）：
- N+1 查询：循环头之后紧跟 DB 调用（execute/query/cursor）
- 循环内阻塞 sleep

均为 medium 级 performance 发现，提示而非阻断。
"""

from __future__ import annotations

import re
from pathlib import Path

from agent.audit.scanning import iter_source_files
from agent.audit.types import AuditFinding

# 循环体探测窗口（行数），避免深状态机
_LOOP_WINDOW = 3
_LOOP_HEAD = re.compile(r"^\s*(for|while)\s+")
_DB_CALL = re.compile(r"\b(execute|cursor|\.query)\s*\(|SELECT\s+\w+\s+FROM")
_SLEEP = re.compile(r"\btime\.sleep\s*\(|\bsleep\s*\(")


def check_performance(project_root: Path, max_files: int = 500) -> list[AuditFinding]:
    """扫描循环内 DB 调用与 sleep，产出 performance 类发现。"""
    findings: list[AuditFinding] = []
    for path in iter_source_files(project_root, max_files):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        loop_remaining = 0
        for lineno, line in enumerate(text.splitlines(), start=1):
            if _LOOP_HEAD.match(line):
                loop_remaining = _LOOP_WINDOW
            elif loop_remaining > 0:
                loop_remaining -= 1
                if _DB_CALL.search(line):
                    findings.append(
                        AuditFinding(
                            category="performance",
                            severity="medium",
                            location=f"{path.relative_to(project_root)}:{lineno}",
                            description="DB query inside loop (possible N+1)",
                        )
                    )
                if _SLEEP.search(line):
                    findings.append(
                        AuditFinding(
                            category="performance",
                            severity="medium",
                            location=f"{path.relative_to(project_root)}:{lineno}",
                            description="blocking sleep inside loop",
                        )
                    )
    return findings