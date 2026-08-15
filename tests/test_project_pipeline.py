"""软件开发 Agent 流水线测试（计划 → 执行 → 审查）。

覆盖：
- UserRequest 用户输入模型（目标 + 技术栈）
- 技术栈 → 领域检测与执行计划落档
- AgentLoop 注入 Repository Map
- Supervisor 任务级审查门禁与终审验收
- run_project 端到端（桩 LLM + 假工具）

全部使用桩函数与假工具，不依赖真实 LLM 与网络。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from agent.communication.event import EventBus, EventType
from agent.core.agent import Agent
from agent.core.loop import Action, AgentLoop
from agent.core.request import UserRequest
from agent.core.state import ProjectState
from agent.memory.store import MemoryStore
from agent.planner.decomposition import decompose
from agent.planner.execution_planner import create_execution_plan
from agent.planner.planner import Planner
from agent.planner.stack_map import detect_domains
from agent.planner.task_tree import TaskTree
from agent.router.router import AgentRouter
from agent.runner import ProjectOutcome, run_project
from agent.supervisor.supervisor import Supervisor

# --- UserRequest ---


def test_user_request_validation_and_render() -> None:
    request = UserRequest(goal=" 开发电商平台 ", tech_stack="FastAPI + MySQL")
    request.validate()
    text = request.render()
    assert "开发电商平台" in text and "FastAPI + MySQL" in text


def test_user_request_requires_goal() -> None:
    with pytest.raises(ValueError, match="goal"):
        UserRequest(goal="  ").validate()


def test_user_request_rejects_oversized_input() -> None:
    with pytest.raises(ValueError, match="too long"):
        UserRequest(goal="x" * 3000).validate()


# --- 技术栈 → 领域 ---


def test_tech_stack_detects_domains() -> None:
    domains = detect_domains("Python FastAPI + PostgreSQL + React + Docker")
    assert domains == ["frontend", "backend", "database", "devops"]
    assert detect_domains("") == []
    assert detect_domains("某个自研引擎") == []


def test_decompose_merges_task_keywords_and_tech_stack() -> None:
    tree = decompose("搭建个人博客", tech_stack="FastAPI + MySQL + React")
    types = {node.task_type for node in tree.flatten()}
    assert {"frontend", "backend", "database"} <= types


def test_decompose_without_tech_stack_keeps_keyword_behavior() -> None:
    tree = decompose("开发一个类似 Steam 的游戏平台")
    types = {node.task_type for node in tree.flatten()}
    assert "frontend" in types and "backend" in types and "database" in types


# --- 执行计划 ---


def test_execution_plan_includes_tech_stack_and_renders() -> None:
    plan = create_execution_plan("开发电商平台", tech_stack="FastAPI + PostgreSQL + React")
    assert plan.tech_stack == "FastAPI + PostgreSQL + React"
    text = plan.render()
    assert "## Tech Stack" in text and "FastAPI" in text and "## Risks" in text
    # 依赖序：database → backend → frontend
    assert plan.order.index("database") < plan.order.index("backend") < plan.order.index("frontend")


def test_planner_create_plan_with_tech_stack() -> None:
    planner = Planner()
    tree = planner.create_plan("搭建博客", tech_stack="FastAPI + MySQL")
    assert {node.task_type for node in tree.flatten()} >= {"backend", "database"}


def test_planner_create_plan_compatible_with_legacy_decompose_fn() -> None:
    # 注入的单参数拆解函数：传 tech_stack 时优雅回退，不抛 TypeError
    planner = Planner(decompose_fn=lambda task: decompose(task))
    tree = planner.create_plan("搭建博客", tech_stack="React")
    assert isinstance(tree, TaskTree)
    assert tree.root.title == "搭建博客"


# --- AgentLoop：Repository Map 注入 ---


def test_agentloop_injects_repo_map_into_context(tmp_path: Path) -> None:
    roles = tmp_path / "roles"
    roles.mkdir()
    (roles / "dev.md").write_text("# Dev\n职责：写码。\n", encoding="utf-8")
    captured: list[str] = []

    def reason_fn(role_prompt: str, task: str, context: str) -> str:
        captured.append(context)
        return "ACTION: finish"

    agent = Agent(name="Dev", role="dev.md", reason_fn=reason_fn, roles_dir=roles)
    loop = AgentLoop(
        agent=agent,
        decide_fn=lambda thought: Action.finish("done"),
        state=ProjectState(task="t"),
        repo_map_provider=lambda: "- auth/user.py (functions: login)",
    )
    result = loop.run("写登录接口")
    assert result.finished
    assert captured and "## Repository Map" in captured[0]
    assert "auth/user.py" in captured[0]


# --- Supervisor：审查门禁 ---


def _make_router(tmp_path: Path) -> AgentRouter:
    roles = tmp_path / "roles"
    roles.mkdir(exist_ok=True)
    (roles / "any.md").write_text("# Any\n职责：全栈。\n", encoding="utf-8")
    agent = Agent(
        name="Any",
        role="any.md",
        reason_fn=lambda role_prompt, task, context: "done",
        roles_dir=roles,
    )
    router = AgentRouter(llm_route_fn=lambda title, names: "Any")
    router.register(agent)
    return router


def _supervisor(tmp_path: Path, **kwargs) -> Supervisor:
    return Supervisor(
        router=_make_router(tmp_path),
        decide_fn=lambda thought: Action.finish("ok"),
        state=ProjectState(),
        memory=MemoryStore(root=tmp_path / "memory"),
        **kwargs,
    )


def test_supervisor_review_gate_rejects_and_retries(tmp_path: Path) -> None:
    supervisor = _supervisor(tmp_path, max_retries=1, review_fn=lambda node, summary: False)
    result = supervisor.run("开发电商商城平台")
    assert not result.finished and result.failed
    types = {event.type for event in supervisor.events.history()}
    assert EventType.REVIEW_FAILED in types
    assert "review failed" in " ".join(supervisor.state.errors)
    # 审查失败计入重试预算，耗尽后写入失败记忆
    assert "task stuck" in supervisor.memory.recent_failures()


def test_supervisor_review_gate_passes_and_publishes(tmp_path: Path) -> None:
    supervisor = _supervisor(tmp_path, review_fn=lambda node, summary: True)
    result = supervisor.run("开发电商商城平台")
    assert result.finished and not result.failed
    types = {event.type for event in supervisor.events.history()}
    assert EventType.REVIEW_PASSED in types


def test_supervisor_acceptance_gate_rejects_delivery(tmp_path: Path) -> None:
    supervisor = _supervisor(tmp_path, acceptance_fn=lambda plan: False)
    result = supervisor.run_request(
        UserRequest(goal="开发电商商城平台", tech_stack="FastAPI + MySQL")
    )
    assert result.finished and not result.accepted
    events = supervisor.events.history()
    assert events[-1].type == EventType.DELIVERY_REJECTED


def test_supervisor_run_request_writes_plan(tmp_path: Path) -> None:
    output = tmp_path / "out"
    supervisor = _supervisor(
        tmp_path,
        output_dir=output,
        acceptance_fn=lambda plan: True,
    )
    result = supervisor.run_request(
        UserRequest(goal="开发电商商城平台", tech_stack="FastAPI + PostgreSQL + React")
    )
    assert result.finished and result.accepted
    assert result.plan_path
    plan_text = (output / "execution_plan.md").read_text(encoding="utf-8")
    assert "## Tech Stack" in plan_text and "FastAPI" in plan_text
    # 技术栈感知：任务树包含 frontend/backend/database
    types = {node.task_type for node in supervisor.last_plan.tree.flatten()}
    assert {"frontend", "backend", "database"} <= types


# --- run_project 端到端 ---


def _write_delivery_docs(root: Path) -> None:
    for name in ("architecture.md", "test_report.md", "security_report.md", "deployment.md"):
        (root / name).write_text("# ok\n", encoding="utf-8")


def test_run_project_end_to_end_with_default_acceptance(tmp_path: Path) -> None:
    output = tmp_path / "out"
    output.mkdir()
    _write_delivery_docs(output)  # 让 AuditAgent 终审通过
    events = EventBus()
    outcome = run_project(
        "开发电商商城平台",
        "Python FastAPI + PostgreSQL + React",
        router=_make_router(tmp_path),
        decide_fn=lambda thought: Action.finish("ok"),
        output_dir=output,
        memory=MemoryStore(root=tmp_path / "memory"),
        events=events,
    )
    assert isinstance(outcome, ProjectOutcome)
    assert outcome.result.finished
    assert outcome.accepted
    assert len(outcome.result.completed) >= 6  # 八阶段任务树全部完成
    assert outcome.plan.tech_stack == "Python FastAPI + PostgreSQL + React"
    assert (output / "execution_plan.md").is_file()
    assert outcome.report_path and Path(outcome.report_path).is_file()
    assert "Conclusion: PASS" in Path(outcome.report_path).read_text(encoding="utf-8")
    # 事件留档包含计划与验收
    types = {e.type for e in events.history()}
    assert EventType.PLAN_CREATED in types and EventType.DELIVERY_ACCEPTED in types


def test_run_project_rejects_without_goal() -> None:
    with pytest.raises(ValueError, match="goal"):
        run_project("", router=AgentRouter(), decide_fn=lambda thought: Action.finish())