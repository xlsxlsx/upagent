"""run_project — 软件开发 Agent 的高层入口。

用户输入「最终目标 + 可能的技术栈」，Agent 完成：

    计划（ExecutionPlan，含技术栈与依赖/风险）
      → 执行（Supervisor 逐任务调度，带任务级审查门禁）
      → 审查（终审验收，默认 AuditAgent 产出 final_report.md）

用法::

    outcome = run_project(
        goal="开发一个类似 Steam 的游戏平台",
        tech_stack="Python FastAPI + PostgreSQL + React",
        router=router,              # 各角色 Agent 注册表
        decide_fn=planner.decide,   # 行动决策（LLM 或桩）
        output_dir=Path("project"),
    )
    print(outcome.result.finished, outcome.result.accepted)
    print(outcome.report_path)
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from agent.agents.team import build_team
from agent.audit.audit_agent import AuditAgent
from agent.communication.event import EventBus
from agent.core.loop import DecideFn, RepoMapProvider, StepFn
from agent.core.request import UserRequest
from agent.core.state import ProjectState
from agent.llm.bindings import (
    make_decide_fn,
    make_decompose_fn,
    make_reason_fn,
    make_review_fn,
    make_step_fn,
    render_tool_contracts,
)
from agent.llm.provider import LLMProvider
from agent.memory.store import MemoryStore
from agent.planner.decomposition import decompose
from agent.planner.execution_planner import ExecutionPlan
from agent.planner.task_tree import TaskTree
from agent.router.router import AgentRouter
from agent.supervisor.supervisor import (
    AcceptanceFn,
    Supervisor,
    SupervisorResult,
    TaskReviewFn,
)


@dataclass(frozen=True)
class ProjectOutcome:
    """一次 run_project 的完整结果。"""

    request: UserRequest
    result: SupervisorResult
    plan: ExecutionPlan
    report_path: str = ""  # 终审报告路径（若有）

    @property
    def accepted(self) -> bool:
        """任务树完成 且 终审通过。"""
        return self.result.finished and self.result.accepted

    def summary(self) -> str:
        lines = [
            f"goal: {self.request.goal}",
            f"tech_stack: {self.request.tech_stack or '(none)'}",
            f"finished: {self.result.finished}",
            f"accepted: {self.result.accepted}",
            f"completed: {len(self.result.completed)} tasks",
        ]
        if self.result.failed:
            lines.append(f"failed: {self.result.failed}")
        if self.result.plan_path:
            lines.append(f"plan: {self.result.plan_path}")
        if self.report_path:
            lines.append(f"report: {self.report_path}")
        return "\n".join(lines)


def default_acceptance(project_root: Path) -> AcceptanceFn:
    """默认终审：AuditAgent 扫描项目目录，全部通过才准予交付。

    生成的 final_report.md 落在 project_root 下。
    """

    def accept(plan: ExecutionPlan) -> bool:
        agent = AuditAgent(project_root=project_root)
        report = agent.audit(plan.tree)
        agent.write_report(report)  # 终审报告落在 project_root 下
        return report.passed

    return accept


def run_project(
    goal: str,
    tech_stack: str = "",
    *,
    router: AgentRouter,
    decide_fn: DecideFn,
    memory: MemoryStore | None = None,
    state: ProjectState | None = None,
    output_dir: Path | None = None,
    constraints: str = "",
    review_fn: TaskReviewFn | None = None,
    acceptance_fn: AcceptanceFn | None = None,
    repo_map_provider: RepoMapProvider | None = None,
    events: EventBus | None = None,
    decompose_fn: Callable[..., TaskTree] = decompose,
    max_steps: int = 10,
    step_fn: StepFn | None = None,
) -> ProjectOutcome:
    """一站式流水线：用户输入 → 计划 → 执行 → 审查 → 交付结论。"""
    request = UserRequest(
        goal=goal,
        tech_stack=tech_stack,
        constraints=constraints,
        output_dir=output_dir,
    )
    request.validate()
    state = state or ProjectState(task=goal)
    memory = memory or MemoryStore()
    if acceptance_fn is None and output_dir is not None:
        # 有产物目录时默认用 AuditAgent 终审，报告写进产物目录
        acceptance_fn = default_acceptance(output_dir)
    supervisor = Supervisor(
        router=router,
        decide_fn=decide_fn,
        state=state,
        memory=memory,
        events=events or EventBus(),
        review_fn=review_fn,
        acceptance_fn=acceptance_fn,
        repo_map_provider=repo_map_provider,
        decompose_fn=decompose_fn,
        max_steps=max_steps,
        step_fn=step_fn,
        output_dir=output_dir,
    )
    result = supervisor.run_request(request)
    assert supervisor.last_plan is not None  # run_request 一定创建了计划
    report_path = ""
    if output_dir is not None:
        candidate = output_dir / "final_report.md"
        if candidate.is_file():
            report_path = str(candidate)
    return ProjectOutcome(
        request=request,
        result=result,
        plan=supervisor.last_plan,
        report_path=report_path,
    )

def run_llm_project(
    goal: str,
    tech_stack: str = "",
    *,
    provider: LLMProvider,
    workspace: Path,
    output_dir: Path | None = None,
    constraints: str = "",
    memory: MemoryStore | None = None,
    events: EventBus | None = None,
    use_llm_review: bool = True,
    use_llm_decompose: bool = True,
    repo_map_provider: RepoMapProvider | None = None,
    acceptance_fn: AcceptanceFn | None = None,
    max_steps: int = 10,
    use_llm_step: bool = True,
) -> ProjectOutcome:
    """LLM 版端到端入口：思考 / 决策 / 审查 / 拆解全部由 provider 驱动。

    内部组装 build_team + 各注入点绑定；规则版能力（终审 AuditAgent、
    失败回退、RepoMap 注入）保持不变。示例见 scripts/llm_demo.py。
    """
    reason_fn = make_reason_fn(provider)
    router = build_team(workspace=workspace, memory=memory, reason_fn=reason_fn)
    tool_names = {name: list(agent.tool_names()) for name, agent in router.agents.items()}
    decide_fn = make_decide_fn(
        provider,
        tool_names.get,
        contracts=lambda name: render_tool_contracts(tool_names.get(name) or []),
    )
    step_fn = (
        make_step_fn(
            provider,
            tool_names.get,
            contracts=lambda name: render_tool_contracts(tool_names.get(name) or []),
            decide_fallback=decide_fn,
        )
        if use_llm_step
        else None
    )
    decompose_fn = make_decompose_fn(provider) if use_llm_decompose else decompose
    review_fn = make_review_fn(provider) if use_llm_review else None
    return run_project(
        goal,
        tech_stack,
        router=router,
        decide_fn=decide_fn,
        memory=memory,
        output_dir=output_dir,
        constraints=constraints,
        review_fn=review_fn,
        acceptance_fn=acceptance_fn,
        decompose_fn=decompose_fn,
        repo_map_provider=repo_map_provider,
        events=events,
        max_steps=max_steps,
        step_fn=step_fn,
    )
