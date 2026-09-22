"""agent/ 升级模块测试（dev-notes/new.md 八阶段升级路线）。

覆盖：codebase 代码智能层、planner 升级、Event Bus、Supervisor、
三层记忆、Patch/TestRunner 工具、Reflection 升级、审计评分。
全部使用桩函数与假工具，不依赖真实 LLM 与网络。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from agent.audit.audit_agent import AuditAgent
from agent.audit.scoring import Scorecard, compute_scores, recommend
from agent.codebase.analyzer import analyze_file, analyze_tree
from agent.codebase.dependency_graph import DependencyGraph
from agent.codebase.repository_map import RepositoryMap
from agent.codebase.search import CodeSearch
from agent.codebase.symbol_index import SymbolIndex
from agent.communication.event import Event, EventBus, EventType
from agent.core.agent import Agent
from agent.core.context import ContextBuilder
from agent.core.loop import Action
from agent.core.state import ProjectState
from agent.memory.store import MemoryStore
from agent.memory.tiers import KnowledgeMemory, MemoryTiers, ProjectMemory, ShortTermMemory
from agent.planner.dependency_planner import execution_order, plan_dependencies
from agent.planner.execution_planner import create_execution_plan
from agent.planner.risk_planner import assess_risks
from agent.reflection.error_analyzer import analyze_output
from agent.reflection.reflector import Reflector
from agent.reflection.retry_policy import RetryPolicy
from agent.router.router import AgentRouter
from agent.supervisor.supervisor import Supervisor
from agent.tools.base import ToolResult
from agent.tools.patch import PatchTool
from agent.tools.terminal import TerminalTool
from agent.tools.test_runner import PackageManagerTool, TestRunnerTool

# --- codebase：代码智能层 ---


def _sample_project(tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    (root / "auth").mkdir(parents=True)
    (root / "auth" / "user.py").write_text(
        '"""User module."""\nimport token_util\n\n\nclass User:\n    pass\n\n\n'
        "def login():\n    pass\n\n\ndef register():\n    pass\n",
        encoding="utf-8",
    )
    (root / "token_util.py").write_text("def issue_token():\n    return 'jwt'\n", encoding="utf-8")
    (root / "broken.py").write_text("def broken(:\n", encoding="utf-8")
    return root


def test_analyzer_extracts_structure(tmp_path: Path) -> None:
    root = _sample_project(tmp_path)
    summary = analyze_file(root / "auth" / "user.py", root)
    assert summary.classes == ("User",)
    assert summary.functions == ("login", "register")
    assert "token_util" in summary.imports
    assert summary.doc == "User module."


def test_analyzer_survives_syntax_error(tmp_path: Path) -> None:
    root = _sample_project(tmp_path)
    summaries = {s.path: s for s in analyze_tree(root)}
    assert summaries["broken.py"].parse_error
    assert summaries["auth/user.py"].functions == ("login", "register")


def test_symbol_index_locates_definitions(tmp_path: Path) -> None:
    index = SymbolIndex.from_root(_sample_project(tmp_path))
    assert index.locate("login") == ["auth/user.py"]
    assert index.defines("issue_token") and not index.defines("nonexistent")


def test_dependency_graph_impact(tmp_path: Path) -> None:
    graph = DependencyGraph.from_root(_sample_project(tmp_path))
    assert "token_util" in graph.imports["auth"]
    assert graph.impacted_by("token_util") == {"auth"}
    assert "auth -> token_util" in graph.render()


def test_repository_map_render_and_write(tmp_path: Path) -> None:
    root = _sample_project(tmp_path)
    repo_map = RepositoryMap.scan(root)
    text = repo_map.render()
    assert "auth/user.py" in text and "functions: login, register" in text
    assert "## Internal Imports" in text
    path = repo_map.write()
    assert path.name == "project_map.md" and path.is_file()


def test_code_search_ranks_by_keyword_hits(tmp_path: Path) -> None:
    root = _sample_project(tmp_path)
    hits = CodeSearch(root=root).search(["login", "token"])
    assert hits and hits[0].path == "auth/user.py"  # 命中两个关键词，排最前
    assert CodeSearch(root=root).search([]) == []


# --- planner 升级 ---


def test_dependency_planner_topological_order() -> None:
    deps = plan_dependencies(["frontend", "backend", "database"])
    assert deps["backend"] == ("database",) and deps["frontend"] == ("backend",)
    order = execution_order(deps)
    assert order.index("database") < order.index("backend") < order.index("frontend")


def test_dependency_planner_detects_cycle() -> None:
    with pytest.raises(ValueError, match="cycle"):
        execution_order({"a": ("b",), "b": ("a",)})


def test_risk_planner_rules_and_fallback() -> None:
    risks = assess_risks("开发支付与登录功能")
    names = {r.name for r in risks}
    assert "payment security" in names and "authentication security" in names
    fallback = assess_risks("写一个 hello world")
    assert fallback[0].level == "low"


def test_execution_plan_orders_domains_and_renders() -> None:
    plan = create_execution_plan("开发电商商城平台")
    assert plan.order.index("database") < plan.order.index("backend")
    implementation = next(n for n in plan.tree.flatten() if n.task_type == "implementation")
    types = [child.task_type for child in implementation.children]
    assert types.index("database") < types.index("backend") < types.index("frontend")
    text = plan.render()
    assert "## Dependencies" in text and "## Risks" in text


# --- communication：Event Bus ---


def test_event_bus_publish_subscribe_history() -> None:
    bus = EventBus()
    received: list[Event] = []
    bus.subscribe(EventType.ARCHITECTURE_COMPLETED, received.append)
    event = Event(EventType.ARCHITECTURE_COMPLETED, source="Architect", payload="architecture.md")
    assert bus.publish(event) == 1
    assert received == [event]
    # 无订阅者事件也留档
    assert bus.publish(Event(EventType.TESTING_FAILED, source="Tester")) == 0
    assert len(bus.history()) == 2


# --- supervisor ---


def _make_router(tmp_path: Path, responses: list[str]) -> AgentRouter:
    roles = tmp_path / "roles"
    roles.mkdir(exist_ok=True)
    (roles / "any.md").write_text("# Any\n职责：全栈。\n", encoding="utf-8")
    script = list(responses)

    def reason_fn(role_prompt: str, task: str, context: str) -> str:
        return script.pop(0) if len(script) > 1 else script[0]

    agent = Agent(name="Any", role="any.md", reason_fn=reason_fn, roles_dir=roles)
    router = AgentRouter(llm_route_fn=lambda title, names: "Any")
    router.register(agent)
    return router


def test_supervisor_completes_whole_tree(tmp_path: Path) -> None:
    router = _make_router(tmp_path, ["done"])
    supervisor = Supervisor(
        router=router,
        decide_fn=lambda thought: Action.finish("ok"),
        state=ProjectState(),
        memory=MemoryStore(root=tmp_path / "memory"),
    )
    result = supervisor.run("开发电商商城平台")
    assert result.finished and not result.failed
    assert "Requirement" in result.completed
    # 每个完成的任务都发布了事件
    assert len(supervisor.events.history()) == len(result.completed)


def test_supervisor_stops_on_stuck_task_and_records_failure(tmp_path: Path) -> None:
    router = _make_router(tmp_path, ["keep going"])
    state = ProjectState()
    memory = MemoryStore(root=tmp_path / "memory")
    supervisor = Supervisor(
        router=router,
        decide_fn=lambda thought: Action(kind="missing_tool"),  # 永不 finish
        state=state,
        memory=memory,
        max_retries=1,
    )
    result = supervisor.run("写一个工具")
    assert not result.finished and result.failed
    assert any("task stuck" in err for err in state.errors)
    assert "task stuck" in memory.recent_failures()


# --- memory：三层记忆 ---


def test_short_term_memory_keeps_recent(tmp_path: Path) -> None:
    short = ShortTermMemory(limit=3)
    for i in range(5):
        short.note(f"note {i}")
    assert short.recall().splitlines() == ["- note 2", "- note 3", "- note 4"]
    short.clear()
    assert short.recall() == ""


def test_project_memory_dedupes_facts(tmp_path: Path) -> None:
    project = ProjectMemory(tmp_path / "facts.md")
    project.remember("数据库使用 PostgreSQL")
    project.remember("数据库使用 PostgreSQL")
    project.remember("认证使用 JWT")
    assert project.recall().count("PostgreSQL") == 1
    assert "JWT" in project.recall()


def test_context_builder_injects_tiers_and_repo_map(tmp_path: Path) -> None:
    tiers = MemoryTiers(
        short_term=ShortTermMemory(),
        project=ProjectMemory(tmp_path / "facts.md"),
        knowledge=KnowledgeMemory(tmp_path / "know.md"),
    )
    tiers.short_term.note("正在修改登录")
    tiers.knowledge.remember("JWT 最佳实践：短过期 + 刷新令牌")
    context = ContextBuilder(agent_root=tmp_path).build(
        user_task="修登录",
        state=ProjectState(task="修登录"),
        tiers=tiers,
        repo_map="- auth/user.py (functions: login)",
    )
    assert "## Repository Map" in context and "auth/user.py" in context
    assert "## Short-Term Memory" in context and "正在修改登录" in context
    assert "## Knowledge Memory" in context
    assert "## Project Memory" not in context  # 空层不注入


# --- tools：Patch / TestRunner / PackageManager ---


def test_patch_preview_and_apply(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    patch = PatchTool(workspace=tmp_path)
    preview = patch.run(operation="preview", path="a.py", old="x = 1\n", new="x = 2\n")
    assert preview.ok and "-x = 1" in preview.output and "+x = 2" in preview.output
    applied = patch.run(operation="apply", path="a.py", old="x = 1\n", new="x = 2\n")
    assert applied.ok
    assert (tmp_path / "a.py").read_text(encoding="utf-8") == "x = 2\n"


def test_patch_rejects_stale_base_and_escape(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("x = 3\n", encoding="utf-8")
    patch = PatchTool(workspace=tmp_path)
    stale = patch.run(operation="apply", path="a.py", old="x = 1\n", new="x = 2\n")
    assert not stale.ok and "stale base" in stale.output
    escape = patch.run(operation="apply", path="../out.py", old="", new="x")
    assert not escape.ok and "escapes workspace" in escape.output


def test_patch_review_gate(tmp_path: Path) -> None:
    patch = PatchTool(workspace=tmp_path, review_fn=lambda diff: False)
    rejected = patch.run(operation="apply", path="new.py", old="", new="x = 1\n")
    assert not rejected.ok and "rejected by review" in rejected.output
    assert not (tmp_path / "new.py").exists()


class _FakeTerminal(TerminalTool):
    """返回固定输出的假 terminal（继承以复用类型）。"""

    def __init__(self, ok: bool, output: str) -> None:
        super().__init__()
        self._result = ToolResult(ok=ok, output=output)

    def run(self, **kwargs: str) -> ToolResult:
        return self._result


def test_test_runner_parses_summary() -> None:
    runner = TestRunnerTool(terminal=_FakeTerminal(False, "2 passed, 1 failed in 0.1s"))
    result = runner.run()
    assert not result.ok
    assert "tests failed" in result.output and "1 failed" in result.output


def test_package_manager_blocks_non_install_commands() -> None:
    manager = PackageManagerTool(terminal=_FakeTerminal(True, "ok"))
    assert manager.run(command="pip install requests").ok
    blocked = manager.run(command="pip uninstall requests")
    assert not blocked.ok and "only install/list" in blocked.output


# --- reflection 升级 ---

_PYTEST_OUTPUT = """\
============ FAILURES ============
  File "src/auth/user.py", line 10, in login
    assert token
FAILED tests/test_auth.py::test_login - AssertionError: empty token
AssertionError: empty token
"""


def test_error_analyzer_extracts_diagnosis() -> None:
    diagnosis = analyze_output(_PYTEST_OUTPUT)
    assert diagnosis.error_type == "AssertionError"
    assert "src/auth/user.py" in diagnosis.files
    assert diagnosis.failed_tests == ("tests/test_auth.py::test_login",)
    assert "empty token" in diagnosis.message


def test_reflector_includes_diagnosis_in_fix_task() -> None:
    fix_task = Reflector().plan_fix("实现登录", _PYTEST_OUTPUT)
    assert "诊断:" in fix_task and "AssertionError" in fix_task


def test_retry_policy_escalates_repeated_errors() -> None:
    policy = RetryPolicy()
    assert policy.next_action("AssertionError", "empty token") == "retry"
    assert policy.next_action("AssertionError", "empty token") == "change_method"
    assert policy.next_action("AssertionError", "empty token") == "escalate"
    policy.reset()
    assert policy.next_action("AssertionError", "empty token") == "retry"


def test_retry_policy_total_budget() -> None:
    policy = RetryPolicy(max_total=2)
    policy.next_action("E1")
    policy.next_action("E2")
    assert policy.next_action("E3") == "escalate"  # 超总预算


# --- audit：评分报告 ---


def test_scoring_penalties_and_recommendation(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "bad.py").write_text('password = "supersecret123"\n', encoding="utf-8")
    report = AuditAgent(project_root=project).audit()
    scores = compute_scores(report.findings, report.completion_rate)
    assert scores.security < 100 and scores.function == 100
    assert "Critical" in recommend(report.findings, report.completion_rate)
    markdown = report.to_markdown()
    assert "## Score" in markdown and "## Recommendation" in markdown


def test_scoring_clean_project() -> None:
    scores = compute_scores((), 1.0)
    assert scores == Scorecard(function=100, security=100, maintainability=100)
    assert scores.overall == 100
    assert recommend((), 1.0) == "质量良好，可以交付"
