"""Supervisor Agent（new.md「六、Supervisor Agent」）。

                  Supervisor
                      |
        ----------------------------
        |             |            |
    Product      Architect     Developer
                      |
                  Reviewer

Supervisor 不干活，只负责：分配任务、判断完成、重试、决策。

run() 主循环：
    创建执行计划 → 逐个取任务树叶子 → Router 选 Agent →
    AgentLoop 执行 → 审查门禁（review_fn）→ 成功标记完成并发布事件 /
    失败重试 → 重试耗尽按回退规则回退（workflow/task_lifecycle.md）→
    回退预算耗尽记 failure_memory 并停止（Rule 6：不原地死磕）。

run_request() 在 run() 之上叠加「计划-执行-审查」完整闭环：
    用户输入（目标 + 技术栈）→ 技术栈感知的执行计划（落档）→
    逐任务执行 + 审查 → 终审验收（acceptance_fn）→ 不通过自动回退重做 →
    交付结论。
"""

from __future__ import annotations

import re
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path

from agent.communication.event import Event, EventBus, EventType
from agent.core.loop import AgentLoop, DecideFn, LoopResult, RepoMapProvider, StepFn
from agent.core.request import UserRequest
from agent.core.state import PhaseStatus, ProjectState
from agent.memory.store import MemoryStore
from agent.planner.decomposition import decompose
from agent.planner.execution_planner import ExecutionPlan, create_execution_plan
from agent.planner.task_tree import TaskNode, TaskTree
from agent.router.router import AgentRouter

# 任务审查函数：任务节点 + 执行摘要 -> 是否通过（默认跳过审查）
TaskReviewFn = Callable[[TaskNode, str], bool]
# 拆解函数：任务/技术栈 -> 任务树（默认规则版，可注入 LLM 版）
DecomposeFn = Callable[..., TaskTree]
# 终审验收函数：完整执行计划 -> 是否准予交付（默认不设门禁）
AcceptanceFn = Callable[[ExecutionPlan], bool]

# 回退规则（workflow/task_lifecycle.md）：阶段失败 → 回退起点。
# 如：安全审计发现架构级问题 → 回到 architecture 重走 4/5/6。
ROLLBACK_TARGETS: dict[str, str] = {
    "testing": "implementation",  # 测试失败 → 回到开发重做
    "security": "architecture",  # 审计失败 → 回到架构修订
    "deploy": "implementation",  # 交付失败 → 回到开发验证
    "implementation": "architecture",  # 开发反复失败 → 回到架构重新规划
    "frontend": "implementation",  # 开发子域失败 → 重做开发阶段
    "backend": "implementation",
    "database": "implementation",
    # requirement / architecture 失败 → 没有更早阶段可回退（重试耗尽即停）
}

# 任务标题中声明的产物文件路径（用于确定性验收，防 LLM 谎报完成）
_FILE_TOKEN_RE = re.compile(
    r"[A-Za-z0-9_\-./\\]+\.(?:py|js|ts|jsx|tsx|md|json|yml|yaml|toml|html|css|sql|txt)\b"
)


@dataclass(frozen=True)
class SupervisorResult:
    """一次调度运行的结果。"""

    finished: bool  # 任务树全部完成
    completed: tuple[str, ...]  # 完成的任务标题
    failed: str = ""  # 卡住的任务标题（若有）
    accepted: bool = True  # 终审是否通过（未配置终审 = True）
    plan_path: str = ""  # 执行计划落档路径（若有）
    report_path: str = ""  # 终审报告路径（若有）
    rollbacks: int = 0  # 本次运行发生的回退次数


@dataclass
class Supervisor:
    """总调度：把执行计划推进到底，失败按回退规则自动回退。"""

    router: AgentRouter
    decide_fn: DecideFn
    state: ProjectState
    memory: MemoryStore | None = None
    events: EventBus = field(default_factory=EventBus)
    max_retries: int = 2  # 单个任务的重试次数（首跑之外）
    max_tasks: int = 100  # 防失控：一次 run 最多处理的任务数
    max_rollbacks: int = 2  # 回退预算：超过即记 failure_memory 并停止
    max_steps: int = 10  # 单任务循环步数上限（收敛控制，默认 10）
    step_fn: StepFn | None = None  # 一步式 reason+decide（LLM 快路径，可选）
    # 计划-执行-审查 闭环
    review_fn: TaskReviewFn | None = None  # 每个任务完成后的审查门禁
    acceptance_fn: AcceptanceFn | None = None  # 全部完成后的终审验收
    decompose_fn: DecomposeFn = decompose  # 计划拆解（规则版 / LLM 版）
    acceptance_rollback_target: str = "implementation"  # 终审不通过时的回退起点
    repo_map_provider: RepoMapProvider | None = None  # 编码前注入 Repository Map
    output_dir: Path | None = None  # 计划/报告落盘目录
    last_plan: ExecutionPlan | None = None  # 最近一次 run_request 的执行计划
    rollbacks_used: int = 0  # 本次运行已用回退次数（run/run_request 时清零）

    def run(self, task: str) -> SupervisorResult:
        plan = create_execution_plan(task)
        self.state.task = task
        self.rollbacks_used = 0
        result = self.execute(plan)
        return replace(result, rollbacks=self.rollbacks_used)

    def run_request(self, request: UserRequest) -> SupervisorResult:
        """完整闭环：用户输入（目标+技术栈）→ 计划 → 执行 → 审查 → 交付结论。"""
        request.validate()
        plan = create_execution_plan(
            request.goal, tech_stack=request.tech_stack, decompose_fn=self.decompose_fn
        )
        self.last_plan = plan
        self.state.task = request.goal
        self.rollbacks_used = 0
        plan_path = ""
        if self.output_dir is not None:
            plan_path = self._write_plan(plan)
            self.events.publish(
                Event(type=EventType.PLAN_CREATED, source="Supervisor", payload=plan_path)
            )
        while True:
            result = self.execute(plan)
            if not result.finished:
                return replace(result, plan_path=plan_path, rollbacks=self.rollbacks_used)
            if self.acceptance_fn is None:
                return replace(result, plan_path=plan_path, rollbacks=self.rollbacks_used)
            accepted = self.acceptance_fn(plan)
            self.events.publish(
                Event(
                    type=(
                        EventType.DELIVERY_ACCEPTED
                        if accepted
                        else EventType.DELIVERY_REJECTED
                    ),
                    source="Supervisor",
                    payload="final acceptance " + ("PASS" if accepted else "FAIL"),
                )
            )
            if accepted:
                return replace(
                    result, accepted=True, plan_path=plan_path, rollbacks=self.rollbacks_used
                )
            # 终审不通过 → 回退到问题阶段重做（预算内）
            if self.rollbacks_used >= self.max_rollbacks:
                self._record_acceptance_failure()
                return replace(
                    result, accepted=False, plan_path=plan_path, rollbacks=self.rollbacks_used
                )
            self.rollbacks_used += 1
            reset = plan.tree.rollback_to(self.acceptance_rollback_target)
            reason = f"final acceptance failed; rollback to {self.acceptance_rollback_target}"
            self.events.publish(
                Event(type=EventType.PHASE_ROLLED_BACK, source="Supervisor", payload=reason)
            )
            self._record_rollback(reset, reason)

    def execute(self, plan: ExecutionPlan) -> SupervisorResult:
        """逐叶子推进任务树；节点失败按回退规则回退，预算耗尽即停。"""
        completed: list[str] = []
        for _ in range(self.max_tasks):
            node = plan.tree.next_task()
            if node is None:
                return SupervisorResult(finished=True, completed=tuple(completed))
            if not self._run_node(node):
                if not self._rollback(plan, node):
                    self._record_stuck(node)
                    return SupervisorResult(
                        finished=False, completed=tuple(completed), failed=node.title
                    )
                # 回退后继续：重建已完成列表（部分节点已被重置为待办）
                completed = [n.title for n in plan.tree.flatten() if n.is_done()]
                continue
            completed.append(node.title)
            self.events.publish(
                Event(type=EventType.TASK_ASSIGNED, source="Supervisor", payload=node.title)
            )
        return SupervisorResult(finished=False, completed=tuple(completed), failed="(max_tasks)")

    # --- 内部 ---

    def _run_node(self, node: TaskNode) -> bool:
        """执行一个叶子任务：执行 + 审查门禁，最多 max_retries 次重试。"""
        try:
            agent = self.router.route(node)
        except LookupError:
            return False
        node.status = PhaseStatus.IN_PROGRESS
        loop = AgentLoop(
            agent=agent,
            decide_fn=self.decide_fn,
            state=self.state,
            memory=self.memory,
            repo_map_provider=self.repo_map_provider,
            max_steps=self.max_steps,
            step_fn=self.step_fn,
        )
        for _ in range(1 + self.max_retries):
            result = loop.run(node.title)
            if result.finished and self._review(node, result):
                node.status = PhaseStatus.DONE
                return True
        node.status = PhaseStatus.FAILED
        return False

    def _review(self, node: TaskNode, result: LoopResult) -> bool:
        """任务级审查门禁：先做确定性产物检查（标题声明的文件路径必须真实存在，
        防 LLM 谎报完成），再走 review_fn（返回 False 则本轮不算完成）。"""
        if not self._mentioned_files_exist(node.title):
            self.events.publish(
                Event(
                    type=EventType.REVIEW_FAILED,
                    source="Reviewer",
                    payload=f"{node.title} (missing artifact)",
                )
            )
            self.state.record_error(f"review failed (missing artifact): {node.title}")
            return False
        if not self._tests_pass(node):
            self.events.publish(
                Event(
                    type=EventType.REVIEW_FAILED,
                    source="Reviewer",
                    payload=f"{node.title} (tests failed)",
                )
            )
            self.state.record_error(f"review failed (tests failed): {node.title}")
            return False
        if self.review_fn is None:
            return True
        summary = "\n".join(result.history)
        passed = self.review_fn(node, summary)
        self.events.publish(
            Event(
                type=EventType.REVIEW_PASSED if passed else EventType.REVIEW_FAILED,
                source="Reviewer",
                payload=node.title,
            )
        )
        if not passed:
            self.state.record_error(f"review failed: {node.title}")
        return passed

    def _mentioned_files_exist(self, title: str) -> bool:
        """确定性验收：标题中提到的产物文件至少一个真实存在；无路径引用时不设限制。"""
        base = self.output_dir or Path.cwd()
        tokens = _FILE_TOKEN_RE.findall(title)
        if not tokens:
            return True
        return any(
            (base / token).is_file() or Path(token).is_file() for token in tokens
        )

    def _tests_pass(self, node: TaskNode) -> bool:
        """确定性验收（testing 任务）：产物目录里存在测试时，真实运行 pytest，
        全部通过才算合格；无测试/无产物目录时不设限制。"""
        if node.task_type != "testing" or self.output_dir is None:
            return True
        base = self.output_dir
        has_tests = (base / "tests").is_dir() or any(base.rglob("test_*.py"))
        if not has_tests:
            return True
        try:
            proc = subprocess.run(
                [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"],
                cwd=str(base),
                capture_output=True,
                text=True,
                timeout=120,
            )
        except (OSError, subprocess.TimeoutExpired):
            return False
        return proc.returncode == 0

    def _rollback(self, plan: ExecutionPlan, node: TaskNode) -> bool:
        """任务失败后的回退：按 ROLLBACK_TARGETS 找起点，预算内执行。"""
        target = ROLLBACK_TARGETS.get(node.task_type)
        if target is None or self.rollbacks_used >= self.max_rollbacks:
            return False
        reset = plan.tree.rollback_to(target)
        if not reset:
            return False
        self.rollbacks_used += 1
        reason = f"{node.title} (type={node.task_type}) failed; rollback to {target}"
        self.events.publish(
            Event(type=EventType.PHASE_ROLLED_BACK, source="Supervisor", payload=reason)
        )
        self._record_rollback(reset, reason)
        return True

    def _record_rollback(self, reset: list[str], reason: str) -> None:
        """把回退记入决策日志（memory/project_memory.md 系）。"""
        if self.memory is None:
            return
        self.memory.append_decision(
            title="rollback: " + reason[:80],
            decision=f"reset {len(reset)} nodes: {', '.join(reset[:8])}",
            reason=reason,
            role="Supervisor",
        )

    def _record_stuck(self, node: TaskNode) -> None:
        """回退预算耗尽：记失败教训（重复回退两次以上 → failure_memory）。"""
        self.state.record_error(f"task stuck: {node.title}")
        if self.memory is not None:
            self.memory.append_failure(
                title=f"task stuck: {node.title[:60]}",
                what=(
                    f"failed after {1 + self.max_retries} runs and "
                    f"{self.rollbacks_used} rollbacks (type={node.task_type})"
                ),
                lesson="回退到问题产生的阶段修复；重复回退两次以上应拆小任务或补充需求上下文后重新计划",
                role="Supervisor",
            )

    def _record_acceptance_failure(self) -> None:
        self.state.record_error("final acceptance failed repeatedly")
        if self.memory is not None:
            self.memory.append_failure(
                title="final acceptance failed repeatedly",
                what=f"rejected after {self.rollbacks_used} rollbacks",
                lesson="回退到更早阶段（architecture）或补充需求上下文后重新计划，不要原地重跑",
                role="Supervisor",
            )

    def _write_plan(self, plan: ExecutionPlan) -> str:
        """把执行计划渲染为 Markdown 落盘（output_dir/execution_plan.md）。"""
        path = self.output_dir / "execution_plan.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(plan.render(), encoding="utf-8")
        return str(path)
