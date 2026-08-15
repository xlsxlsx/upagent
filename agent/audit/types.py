"""审计共享类型（五个检查器与聚合器之间解耦）。"""

from __future__ import annotations

from dataclasses import dataclass

from agent.audit.scoring import compute_scores, recommend

# 严重级别排序（报告展示用，critical 最重）
SEVERITY_ORDER = ("critical", "high", "medium", "low")


@dataclass(frozen=True)
class AuditFinding:
    """一条审计发现。"""

    category: str  # function / code / security / architecture
    severity: str  # critical / high / medium / low
    location: str
    description: str


@dataclass(frozen=True)
class AuditReport:
    """终审报告。"""

    findings: tuple[AuditFinding, ...]
    completion_rate: float

    @property
    def passed(self) -> bool:
        """无 Critical/High 且需求全部完成才通过。"""
        blockers = [f for f in self.findings if f.severity in ("critical", "high")]
        return not blockers and self.completion_rate >= 1.0

    def to_markdown(self) -> str:
        scores = compute_scores(self.findings, self.completion_rate)
        lines = [
            "# Final Report",
            "",
            f"Requirement completion: {self.completion_rate:.0%}",
            f"Conclusion: {'PASS' if self.passed else 'FAIL'}",
            "",
            "## Score",
            "",
            scores.render(),
            f"Overall: {scores.overall}%",
            "",
            "## Findings",
            "",
        ]
        if not self.findings:
            lines.append("(none)")
        for finding in sorted(self.findings, key=lambda f: SEVERITY_ORDER.index(f.severity)):
            lines.append(
                f"- [{finding.severity.upper()}] {finding.category}: "
                f"{finding.description} @ {finding.location}"
            )
        lines += ["", "## Recommendation", "", recommend(self.findings, self.completion_rate)]
        return "\n".join(lines) + "\n"