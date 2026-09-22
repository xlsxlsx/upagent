"""安全扫描器（dev-notes/new.md「十一、Audit Agent 重构」）。

静态危险模式扫描：拼接 SQL、硬编码密钥、eval/exec、
shell=True 拼接、innerHTML 赋值。复用 scanning.scan_lines。
"""

from __future__ import annotations

import re
from pathlib import Path

from agent.audit.scanning import Pattern, scan_lines

# 危险模式表：(名称, 严重级别, 正则)，与原 audit_agent._PATTERNS 保持一致
_PATTERNS: list[Pattern] = [
    (
        "SQL string concat",
        "critical",
        re.compile(
            r"""(execute|cursor\.\w+)\([^)]*(["']\s*\+|\.format\(|f["'].*(SELECT|INSERT|UPDATE|DELETE))""",
            re.IGNORECASE,
        ),
    ),
    (
        "hardcoded secret",
        "critical",
        re.compile(r"""(password|secret|api_key|token)\s*=\s*["'][^"']{8,}["']""", re.IGNORECASE),
    ),
    ("eval/exec usage", "high", re.compile(r"\b(eval|exec)\s*\(")),
    ("shell=True with format", "high", re.compile(r"""shell\s*=\s*True.*(\+|format\(|f["'])""")),
    ("innerHTML assignment", "high", re.compile(r"\.innerHTML\s*=")),
]


def scan_security(
    project_root: Path,
    max_files: int = 500,
    extra_patterns: list[Pattern] | None = None,
) -> list:
    """扫描安全危险模式，产出 security 类发现。

    extra_patterns 保持旧语义：非 low 严重级归入 security 类，
    low 级别归入 code 类（与拆分前 audit_agent 行为一致）。
    """
    findings = scan_lines(project_root, _PATTERNS, max_files, category="security")
    for name, severity, pattern in extra_patterns or []:
        category = "security" if severity != "low" else "code"
        findings.extend(
            scan_lines(project_root, [(name, severity, pattern)], max_files, category=category)
        )
    return findings