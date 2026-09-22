"""Final Audit（dev-notes/new.md「十一、Audit Agent 重构」）。

audit_agent 编排五个 checker（代码/安全/架构/性能/文档）；
scoring 折算 Function/Security/Maintainability 三维评分。
"""

from agent.audit.architecture_check import check_architecture
from agent.audit.audit_agent import AuditAgent
from agent.audit.code_quality import check_code_quality
from agent.audit.documentation_check import check_documentation
from agent.audit.performance_check import check_performance
from agent.audit.scoring import Scorecard, compute_scores, recommend
from agent.audit.security_scan import scan_security
from agent.audit.types import AuditFinding, AuditReport

__all__ = [
    "AuditAgent",
    "AuditFinding",
    "AuditReport",
    "Scorecard",
    "check_architecture",
    "check_code_quality",
    "check_documentation",
    "check_performance",
    "compute_scores",
    "recommend",
    "scan_security",
]