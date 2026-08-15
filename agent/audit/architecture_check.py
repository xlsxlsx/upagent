"""架构检查器（new.md「十一、Audit Agent 重构」）。

交付文档齐全性检查：architecture.md / test_report.md /
security_report.md / deployment.md 缺一即记 architecture 发现。
"""

from __future__ import annotations

from pathlib import Path

from agent.audit.types import AuditFinding

# 交付必备文档（workflow/deployment.md 交付物清单）
REQUIRED_DOCS = ("architecture.md", "test_report.md", "security_report.md", "deployment.md")


def check_architecture(docs_root: Path) -> list[AuditFinding]:
    """核对交付文档是否齐全，缺失返回 medium 级 architecture 发现。"""
    return [
        AuditFinding(
            category="architecture",
            severity="medium",
            location=name,
            description="required delivery document missing",
        )
        for name in REQUIRED_DOCS
        if not (docs_root / name).is_file()
    ]