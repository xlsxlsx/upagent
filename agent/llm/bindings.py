"""LLM 绑定层：把 LLMProvider 适配到 agent 各注入点签名。

保持核心签名不变（ReasonFn / DecideFn / TaskReviewFn / DecomposeFn / LlmRouteFn），
LLM 输出全部要求 JSON；解析失败回退规则实现，保证流程不因模型抖动中断。
"""

from __future__ import annotations

from collections.abc import Callable

from agent.core.agent import ReasonFn, Thought
from agent.core.loop import Action, DecideFn
from agent.llm.provider import ChatMessage, LLMProvider
from agent.planner.decomposition import decompose
from agent.planner.planner import DecomposeFn, Planner
from agent.planner.task_tree import TaskNode, TaskTree
from agent.router.router import LlmRouteFn
from agent.supervisor.supervisor import TaskReviewFn

_DECIDE_SYSTEM = """你是任务执行调度器。根据 Agent 的思考决定下一步动作。
运行环境：Windows（cmd 兼容）。避免 Unix 专用命令（pwd 用 cd、ls 用 dir、cat 用 type、
python3 用 python）。终端工具执行的是 shell 命令，务必使用 Windows 可用命令。
可用工具：{tools}
工具参数契约：
{contracts}
- 若任务已完成，输出 {{"kind": "finish", "note": "完成说明"}}
- 否则输出 {{"kind": "<工具名>", "args": {{"参数名": "值"}}, "note": "目的"}}
只输出一个 JSON 对象，不要 Markdown 或额外文字。
收敛规则（务必遵守）：
1. 目标产物已存在且内容正确时，不要重复写入，直接 finish。
2. 能用一条 terminal 命令完成验证时不要先写文件再跑。
3. 每轮只做一件最有价值的事，避免无意义重复。"""

_DECIDE_USER = """Agent: {agent}
Task: {task}

Thought:
{thought}

只输出 JSON。"""

_REVIEW_SYSTEM = """你是代码审查员。根据任务与执行日志判断结果是否合格。
只输出 JSON：{{"passed": true 或 false, "comment": "一句话说明"}}"""

_REVIEW_USER = """Task: {title} (type={task_type})

Execution log:
{summary}

只输出 JSON。"""

_ROUTE_SYSTEM = """你是任务路由器。从候选 Agent 中选择最适合处理当前任务的一个。
只输出 JSON：{{"agent": "<候选名>"}}"""

_ROUTE_USER = """Task: {task}

Candidates: {candidates}

只输出 JSON。"""

# 常用工具的参数契约，帮助 LLM 输出正确 args
_TOOL_CONTRACTS: dict[str, str] = {
    "file": "operation(read|write|exists), path(必填), content(写入内容)",
    "patch": "operation(preview|apply), path(必填), old(原内容), new(新内容)",
    "terminal": "command(要执行的 shell 命令)",
    "git": "command(git 子命令及参数)",
    "test_runner": "command(测试运行命令)",
    "package_manager": "command(包管理命令)",
    "browser": "action(open|navigate|screenshot), url(可选)",
    "database": "operation(query|migrate), database(数据库名), query(SQL 或迁移脚本)",
    "docker": "command(docker 子命令)",
}


def render_tool_contracts(
    tool_names: list[str], contracts: dict[str, str] | None = None
) -> str:
    """把工具名列表渲染成带参数契约的说明文本。"""
    table = contracts or _TOOL_CONTRACTS
    lines = []
    for name in tool_names:
        detail = table.get(name, "（无参数说明，按直觉传入必要参数）")
        lines.append(f"- {name}: {detail}")
    return "\n".join(lines)


_DECOMPOSE_SYSTEM = """你是项目规划师。把用户目标拆成按执行顺序排列的任务树。
任务类型取值：requirement / architecture / backend / frontend / database /
testing / security / deploy / general。
只输出 JSON：{{"tasks": [{{"title": "任务标题", "task_type": "类型"}}]}}"""

_DECOMPOSE_USER = """Goal: {goal}

Tech stack: {tech_stack}

只输出 JSON。"""


def make_reason_fn(provider: LLMProvider) -> ReasonFn:
    """Agent 思考：角色 Prompt 作 system，任务 + 上下文作 user。"""

    def reason(role_prompt: str, task: str, context: str) -> str:
        messages = [
            ChatMessage(role="system", content=role_prompt),
            ChatMessage(
                role="user",
                content=(
                f"## Task\n{task}\n\n## Context\n{context}\n\n"
                "请给出你的推理过程与下一步计划。"
            ),
            ),
        ]
        return provider.complete(messages, temperature=0.3).strip()

    return reason


def make_decide_fn(
    provider: LLMProvider,
    tool_names: Callable[[str], list[str]] | None = None,
    contracts: Callable[[str], str] | None = None,
) -> DecideFn:
    """行动决策：LLM 输出 {kind, args, note}；失败回退解析思考中的 ACTION 行。"""

    def decide(thought: Thought) -> Action:
        tools = tool_names(thought.agent_name) if tool_names is not None else []
        details = contracts(thought.agent_name) if contracts is not None else ""
        system = _DECIDE_SYSTEM.format(
            tools=", ".join(tools) if tools else "(无)",
            contracts=details or "(无工具)",
        )
        user = _DECIDE_USER.format(
            agent=thought.agent_name, task=thought.task, thought=thought.content
        )
        try:
            data = provider.complete_json(
                [
                    ChatMessage(role="system", content=system),
                    ChatMessage(role="user", content=user),
                ],
                temperature=0.0,
            )
        except Exception:
            return Planner().decide(thought)
        kind = str(data.get("kind") or "finish")
        raw_args = data.get("args")
        args = (
            {str(k): str(v) for k, v in raw_args.items()}
            if isinstance(raw_args, dict)
            else {}
        )
        note = str(data.get("note") or "")
        if kind.lower() == "finish":
            return Action.finish(note=note or thought.content[:100])
        return Action(kind=kind, args=args, note=note)

    return decide


def make_review_fn(provider: LLMProvider) -> TaskReviewFn:
    """任务级审查：LLM 判定 passed；调用失败时保守放行。"""

    def review(node: TaskNode, summary: str) -> bool:
        messages = [
            ChatMessage(role="system", content=_REVIEW_SYSTEM),
            ChatMessage(
                role="user",
                content=_REVIEW_USER.format(
                    title=node.title, task_type=node.task_type, summary=summary
                ),
            ),
        ]
        try:
            data = provider.complete_json(messages, temperature=0.0)
        except Exception:
            return True
        return bool(data.get("passed", True))

    return review


def make_route_fn(provider: LLMProvider) -> LlmRouteFn:
    """规则未命中时的 LLM 路由回退。"""

    def route(task_title: str, candidates: list[str]) -> str:
        messages = [
            ChatMessage(role="system", content=_ROUTE_SYSTEM),
            ChatMessage(
                role="user",
                content=_ROUTE_USER.format(task=task_title, candidates=", ".join(candidates)),
            ),
        ]
        try:
            data = provider.complete_json(messages, temperature=0.0)
        except Exception:
            return ""
        return str(data.get("agent") or "")

    return route


def make_decompose_fn(
    provider: LLMProvider,
    fallback: Callable[..., TaskTree] = decompose,
) -> DecomposeFn:
    """LLM 拆解任务树；失败回退规则 decompose。"""

    def plan_tasks(task: str, tech_stack: str | None = None) -> TaskTree:
        messages = [
            ChatMessage(role="system", content=_DECOMPOSE_SYSTEM),
            ChatMessage(
                role="user",
                content=_DECOMPOSE_USER.format(goal=task, tech_stack=tech_stack or "(none)"),
            ),
        ]
        try:
            data = provider.complete_json(messages, temperature=0.2)
            return _build_tree(task, data)
        except Exception:
            if tech_stack:
                return fallback(task, tech_stack=tech_stack)
            return fallback(task)

    return plan_tasks


def _build_tree(goal: str, data: dict) -> TaskTree:
    """LLM 的 {tasks: [...]} → TaskTree；结构非法时抛 ValueError 触发回退。"""
    items = data.get("tasks")
    if not isinstance(items, list) or not items:
        raise ValueError("LLM returned empty task list")
    root = TaskNode(title=goal, task_type="root")
    for item in items:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        task_type = str(item.get("task_type") or "general").strip() or "general"
        if title:
            root.add(TaskNode(title=title, task_type=task_type))
    if not root.children:
        raise ValueError("LLM task tree has no nodes")
    return TaskTree(root=root)