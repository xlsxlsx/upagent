"""audit 拆分测试：五个 checker 独立可用，编排器保持兼容。"""

from __future__ import annotations

import re
from pathlib import Path

from agent.audit.architecture_check import check_architecture
from agent.audit.audit_agent import AuditAgent
from agent.audit.code_quality import check_code_quality
from agent.audit.documentation_check import check_documentation
from agent.audit.performance_check import check_performance
from agent.audit.security_scan import scan_security
from agent.audit.types import AuditFinding, AuditReport


def test_code_quality_finds_todo_in_py_and_js(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("# TODO: later\nx = 1\n", encoding="utf-8")
    (tmp_path / "b.js").write_text("// FIXME: broken\nconst y = 2;\n", encoding="utf-8")
    findings = check_code_quality(tmp_path)
    locations = {f.location for f in findings}
    assert "a.py:1" in locations and "b.js:1" in locations
    assert all(f.severity == "low" and f.category == "code" for f in findings)


def test_security_scan_finds_critical_and_high(tmp_path: Path) -> None:
    (tmp_path / "bad.py").write_text(
        'password = "supersecret123"\n'
        'cursor.execute("SELECT * FROM t WHERE id=" + uid)\n'
        "eval(user_input)\n",
        encoding="utf-8",
    )
    findings = scan_security(tmp_path)
    names = {f.description for f in findings}
    assert "hardcoded secret" in names
    assert "SQL string concat" in names
    assert "eval/exec usage" in names
    assert all(f.category == "security" for f in findings)
    assert {"critical", "high"} <= {f.severity for f in findings}


def test_architecture_check_required_docs(tmp_path: Path) -> None:
    missing = check_architecture(tmp_path)
    assert len(missing) == 4
    assert all(f.category == "architecture" and f.severity == "medium" for f in missing)
    for name in ("architecture.md", "test_report.md", "security_report.md", "deployment.md"):
        (tmp_path / name).write_text("# ok\n", encoding="utf-8")
    assert check_architecture(tmp_path) == []


def test_documentation_check_readme_api(tmp_path: Path) -> None:
    missing = check_documentation(tmp_path)
    assert {f.location for f in missing} == {"README.md", "api.md"}
    (tmp_path / "README.md").write_text("# project\n", encoding="utf-8")
    assert [f.location for f in check_documentation(tmp_path)] == ["api.md"]


def test_performance_check_detects_loop_query(tmp_path: Path) -> None:
    (tmp_path / "svc.py").write_text(
        "for user in users:\n"
        "    cursor.execute('SELECT * FROM orders WHERE user_id = %s' % user)\n",
        encoding="utf-8",
    )
    findings = check_performance(tmp_path)
    assert findings and findings[0].category == "performance"
    assert findings[0].severity == "medium"
    assert "N+1" in findings[0].description


def test_audit_agent_orchestrates_checkers(tmp_path: Path) -> None:
    (tmp_path / "bad.py").write_text(
        'password = "supersecret123"\n# TODO: later\n', encoding="utf-8"
    )
    report = AuditAgent(project_root=tmp_path).audit()
    assert isinstance(report, AuditReport)
    categories = {f.category for f in report.findings}
    assert {"security", "code", "architecture"} <= categories
    assert not report.passed  # critical 阻塞交付
    assert "## Score" in report.to_markdown()
    path = AuditAgent(project_root=tmp_path).write_report(report)
    assert path.is_file() and "Conclusion: FAIL" in path.read_text(encoding="utf-8")


def test_audit_agent_passes_with_clean_project(tmp_path: Path) -> None:
    for name in ("architecture.md", "test_report.md", "security_report.md", "deployment.md"):
        (tmp_path / name).write_text("# ok\n", encoding="utf-8")
    report = AuditAgent(project_root=tmp_path).audit()
    assert report.passed


def test_audit_agent_extra_patterns_category(tmp_path: Path) -> None:
    (tmp_path / "x.py").write_text("danger_call()\n", encoding="utf-8")
    agent = AuditAgent(
        project_root=tmp_path,
        extra_patterns=[("custom danger", "high", re.compile(r"danger_call"))],
    )
    report = agent.audit()
    custom = [f for f in report.findings if f.description == "custom danger"]
    assert custom and custom[0].category == "security"
    assert isinstance(custom[0], AuditFinding)