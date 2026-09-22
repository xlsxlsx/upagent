"""文档检查器（dev-notes/new.md「十一、Audit Agent 重构」）。

项目使用文档完整性：README.md（入口说明）与 api.md（接口说明）。
medium 级 architecture 发现，不阻塞交付结论。
"""

from __future__ import annotations

from pathlib import Path

from agent.audit.types import AuditFinding

REQUIRED_DOCS = ("README.md", "api.md")


def check_documentation(docs_root: Path) -> list[AuditFinding]:
    """核对使用/接口文档是否存在。"""
    return [
        AuditFinding(
            category="architecture",
            severity="medium",
            location=name,
            description="project documentation missing",
        )
        for name in REQUIRED_DOCS
        if not (docs_root / name).is_file()
    ]