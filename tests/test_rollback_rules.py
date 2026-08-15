"""回退规则测试（workflow/task_lifecycle.md 回退规则）。

覆盖：
- TaskTree.rollback_to：从问题阶段起重置为待办，更早阶段保持完成
- Supervisor 任务失败 → 按 ROLLBACK_TARGETS 自动回退 → 重做后续阶段
- 回退预算耗尽 → 记 failure_memory 并停止
- 终审不通过 → 自动回退重做；多次拒绝 → 停止并记录

全部使用桩函数与假工具，不依赖真实 LLM 与网络。
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from agent.communication.event import EventType
from agent.core.agent import Agent
from agent.core.loop import Action, Thought
from agent.core.request import UserRequest
from agent.core.state import PhaseStatus, ProjectState
from agent.memory.store import MemoryStore
from agent.planner.decomposition import decompose
from agent.planner.task_tree import TaskNode
from agent.router.router import AgentRouter
from agent.supervisor.supervisor import ROLLBACK_TARGETS, Supervisor

# --- 工具 ---


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


def _decide_with_failures(failures: dict[str, int]) -> Callable[[Thought], Action]:
    """按任务标题控制失败次数：失败时返回不收敛的行动。"""

    def decide_fn(thought: Thought) -> Action:
        if failures.get(thought.task, 0) > 0:
            failures[thought.task] -= 1
            return Action(kind="missing_tool")  # 永不 finish → 该轮执行失败
        return Action.finish("ok")

    return decide_fn


def _supervisor(tmp_path: Path, decide_fn, **kwargs) -> Supervisor:
    return Supervisor(
        router=_make_router(tmp_path),
        decide_fn=decide_fn,
        state=ProjectState(),
        memory=MemoryStore(root=tmp_path / "memory"),
        **kwargs,
    )


# --- TaskTree.rollback_to ---


def test_task_tree_rollback_to_resets_subtree() -> None:
    tree = decompose("开发电商商城平台")
    for node in tree.flatten():
        node.status = PhaseStatus.DONE
    reset = tree.rollback_to("implementation")
    assert "Testing" in reset and "Security Audit" in reset and "Frontend" in reset
    by_type = {node.task_type: node for node in tree.flatten()}
    assert by_type["requirement"].status == PhaseStatus.DONE  # 更早阶段保持完成
    assert by_type["architecture"].status == PhaseStatus.DONE
    assert by_type["testing"].status == PhaseStatus.PENDING
    assert by_type["deploy"].status == PhaseStatus.PENDING
    assert tree.next_task().task_type == "frontend"  # 从开发阶段第一个叶子重做


def test_task_tree_rollback_unknown_type_noop() -> None:
    tree = decompose("写一个工具")
    assert tree.rollback_to("nonexistent") == []
    assert tree.next_task() is not None


# --- 回退映射 ---


def test_rollback_targets_mapping() -> None:
    assert ROLLBACK_TARGETS["testing"] == "implementation"
    assert ROLLBACK_TARGETS["security"] == "architecture"  # 审计失败 → 回架构
    assert ROLLBACK_TARGETS["deploy"] == "implementation"
    assert ROLLBACK_TARGETS["backend"] == "implementation"
    assert "requirement" not in ROLLBACK_TARGETS  # 无更早阶段可回退
    assert "architecture" not in ROLLBACK_TARGETS


# --- Supervisor：任务失败自动回退 ---

# AgentLoop.max_steps 默认值：整轮执行不收敛需要消耗完这个步数
_STEPS_PER_RUN = 25

# AgentLoop.max_steps 默认值：整轮执行不收敛需要消耗完这个步数 = 25


def test_supervisor_rolls_back_and_recovers(tmp_path: Path) -> None:
    failures = {"Testing": _STEPS_PER_RUN}  # 首轮 Testing 不收敛，回退后第二轮通过
    supervisor = _supervisor(tmp_path, _decide_with_failures(failures), max_retries=0)
    result = supervisor.run("开发电商商城平台")
    assert result.finished and not result.failed
    assert result.rollbacks == 1
    assert "Testing" in result.completed  # 回退后重做成功
    # 事件与决策日志都记录了回退
    types = {e.type for e in supervisor.events.history()}
    assert EventType.PHASE_ROLLED_BACK in types
    assert "rollback" in supervisor.memory.recent_decisions()


def test_supervisor_rolls_back_on_review_failure_then_recovers(tmp_path: Path) -> None:
    review_results = {"Testing": 1}  # 审查失败一次，回退后重做通过审查

    def review_fn(node: TaskNode, summary: str) -> bool:
        if review_results.get(node.title, 0) > 0:
            review_results[node.title] -= 1
            return False
        return True

    supervisor = _supervisor(
        tmp_path,
        _decide_with_failures({}),
        max_retries=0,
        review_fn=review_fn,
    )
    result = supervisor.run("开发电商商城平台")
    assert result.finished and result.rollbacks == 1
    assert EventType.REVIEW_FAILED in {e.type for e in supervisor.events.history()}


def test_supervisor_rollback_budget_exhausted_stops(tmp_path: Path) -> None:
    failures = {"Testing": 100}  # 永不收敛
    supervisor = _supervisor(
        tmp_path, _decide_with_failures(failures), max_retries=0, max_rollbacks=1
    )
    result = supervisor.run("开发电商商城平台")
    assert not result.finished and result.failed == "Testing"
    assert result.rollbacks == 1  # 只回退了一次，第二次失败即停
    failures_text = supervisor.memory.recent_failures()
    assert "task stuck" in failures_text and "1 rollbacks" in failures_text


# --- Supervisor：终审不通过自动回退 ---


def test_supervisor_acceptance_rejection_rolls_back_and_recovers(tmp_path: Path) -> None:
    calls = {"count": 0}

    def acceptance_fn(plan) -> bool:
        calls["count"] += 1
        return calls["count"] > 1  # 第一次拒绝，回退后通过

    supervisor = _supervisor(
        tmp_path, _decide_with_failures({}), max_rollbacks=2, acceptance_fn=acceptance_fn
    )
    result = supervisor.run_request(
        UserRequest(
            goal="开发电商商城平台", tech_stack="FastAPI + MySQL"
        )
    )
    assert result.finished and result.accepted
    assert result.rollbacks == 1
    events = supervisor.events.history()
    assert events[-1].type == EventType.DELIVERY_ACCEPTED
    assert EventType.PHASE_ROLLED_BACK in {e.type for e in events}


def test_supervisor_acceptance_rejection_exhausts_budget(tmp_path: Path) -> None:
    supervisor = _supervisor(
        tmp_path,
        _decide_with_failures({}),
        max_rollbacks=1,
        acceptance_fn=lambda plan: False,  # 终审永不通过
    )
    result = supervisor.run_request(
        UserRequest(
            goal="开发电商商城平台", tech_stack="FastAPI + MySQL"
        )
    )
    assert result.finished and not result.accepted
    assert result.rollbacks == 1
    rejected = [e for e in supervisor.events.history() if e.type == EventType.DELIVERY_REJECTED]
    assert len(rejected) == 2  # 两次尝试各拒绝一次
    assert "final acceptance failed repeatedly" in supervisor.memory.recent_failures()
    assert "final acceptance failed repeatedly" in " ".join(supervisor.state.errors)