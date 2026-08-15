"""最终 Audit Agent（new.md「十一、Audit Agent 重构」）。

拆分后为编排器：聚合五个独立 checker 的发现，
保留原 AuditAgent 公共 API（audit / write_report / extra_patterns）。

checker 分工：
- code_quality.py        维护性：TODO/FIXME 遗留
- security_scan.py       安全：SQL 拼接 / 硬编码密钥 / eval 等
- architecture_check.py  架构：交付文档齐全性
- performance_check.py   性能：循环内 DB 调用 / sleep
- documentation_check.py 文档：README / api 文档
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from agent.audit.architecture_check import check_architecture
from agent.audit.code_quality import check_code_quality
from agent.audit.documentation_check import check_documentation
from agent.audit.performance_check import check_performance
from agent.audit.security_scan import scan_security
from agent.audit.types import AuditFinding, AuditReport
from agent.planner.task_tree import TaskTree

# 扫描模式类型（与 scanning.Pattern 对齐，兼容调用方传入）
Pattern = tuple[str, str, re.Pattern[str]]


@dataclass
class AuditAgent:
    """对项目目录做最终审计并产出 final_report.md。"""

    project_root: Path
    docs_root: Path | None = None  # 交付文档所在目录，默认取 project_root
    max_files: int = 500  # 扫描文件数上限
    extra_patterns: list[Pattern] = field(default_factory=list)

    def audit(self, tree: TaskTree | None = None) -> AuditReport:
        findings: list[AuditFinding] = []
        findings.extend(check_code_quality(self.project_root, self.max_files))
        findings.extend(scan_security(self.project_root, self.max_files, self.extra_patterns))
        findings.extend(check_architecture(self.docs_root or self.project_root))
        findings.extend(check_performance(self.project_root, self.max_files))
        findings.extend(check_documentation(self.docs_root or self.project_root))
        rate = self._completion_rate(tree)
        if rate < 1.0:
            findings.append(
                AuditFinding(
                    category="function",
                    severity="high",
                    location="task tree",
                    description=f"requirement completion {rate:.0%} < 100%",
                )
            )
        return AuditReport(findings=tuple(findings), completion_rate=rate)

    def write_report(self, report: AuditReport) -> Path:
        path = (self.docs_root or self.project_root) / "final_report.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(report.to_markdown(), encoding="utf-8")
        return path

    @staticmethod
    def _completion_rate(tree: TaskTree | None) -> float:
        if tree is None:
            return 1.0
        leaves = [node for node in tree.flatten() if not node.children]
        if not leaves:
            return 1.0
        done = sum(1 for node in leaves if node.is_done())
        return done / len(leaves)