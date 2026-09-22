"""审计评分卡（dev-notes/new.md「十一、Audit Agent 重构」）。

把审计发现折算成三项分数（对应 FINAL_REPORT.md 格式）：

    Function:        需求完成率
    Security:        安全类发现扣分
    Maintainability: 代码质量/文档类发现扣分

按严重级别扣分：critical -25 / high -15 / medium -8 / low -3，
分数下限 0。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent.audit.types import AuditFinding

_PENALTY = {"critical": 25, "high": 15, "medium": 8, "low": 3}


@dataclass(frozen=True)
class Scorecard:
    """三维评分（0-100）。"""

    function: int
    security: int
    maintainability: int

    @property
    def overall(self) -> int:
        return round((self.function + self.security + self.maintainability) / 3)

    def render(self) -> str:
        return (
            f"Function: {self.function}%\n"
            f"Security: {self.security}%\n"
            f"Maintainability: {self.maintainability}%"
        )


def compute_scores(findings: tuple[AuditFinding, ...], completion_rate: float) -> Scorecard:
    """发现列表 + 完成率 → 评分卡。"""
    security = 100
    maintainability = 100
    for finding in findings:
        penalty = _PENALTY.get(finding.severity, 3)
        if finding.category == "security":
            security -= penalty
        else:
            maintainability -= penalty
    return Scorecard(
        function=round(max(0.0, min(completion_rate, 1.0)) * 100),
        security=max(0, security),
        maintainability=max(0, maintainability),
    )


def recommend(findings: tuple[AuditFinding, ...], completion_rate: float) -> str:
    """按最重问题给一句可执行建议。"""
    if any(f.severity == "critical" for f in findings):
        return "先修复全部 Critical 安全问题，回退 development 阶段重新走测试与审计"
    if completion_rate < 1.0:
        return "完成任务树中剩余节点后重新审计"
    if any(f.severity == "high" for f in findings):
        return "修复 High 级别问题后即可通过审计"
    if findings:
        return "处理 Medium/Low 遗留项（文档、TODO），可与交付并行"
    return "质量良好，可以交付"
