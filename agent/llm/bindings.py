"""LLM 绑定层：把 LLMProvider 适配到 agent 各注入点签名。

保持核心签名不变（ReasonFn / DecideFn / TaskReviewFn / DecomposeFn / LlmRouteFn），
LLM 输出全部要求 JSON；解析失败回退规则实现，保证流程不因模型抖动中断。
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable

from agent.core.agent import ReasonFn, Thought
from agent.core.loop import Action, DecideFn, StepFn
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
收敛规则（务必遵守，这是最高优先级）：
1. 完成判据 = 任务目标已达成（产物已写入且验证通过）。达成后必须立即输出 finish。
2. 若最近的执行记录显示目标产物已成功写入/验证，本轮直接 finish，绝不重复同一操作。
3. 能用一条 terminal 命令完成验证时不要先写文件再跑。
4. 每轮只做一件最有价值的事；连续两轮做同一件事意味着你应该 finish。
5. 步骤预算有限：多轮重复 = 失败，宁可提前 finish 也不要超预算。"""

_DECIDE_USER = """Agent: {agent}
Task: {task}

Thought:
{thought}

根据 Thought 中引用的最近执行记录判断：
- 若目标已完成（产物写入 + 验证通过），输出 {{"kind": "finish", "note": "..."}}
- 否则只执行下一步必要动作
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


_DECOMPOSE_SYSTEM = """你是项目规划师。把用户目标拆成按执行顺序排列的任务树。约束（最高优先级）：
1. 任务总数不超过 4 个；小型目标 2-3 个即可。任务粒度要粗：同类型强相关的步骤必须
   合并为一个任务（例如「实现冒泡/快速/归并」合并为「实现三种排序」，
   「写测试+运行测试」合并为「编写测试并运行通过」）。
2. 每个任务标题必须写明关键产物文件的相对路径（如 sorting.py、
   tests/test_sorting.py），便于验收核对。
3. 标题使用祈使句，说明产出与验证方式。
任务类型取值：requirement / architecture / backend / frontend / database /
testing / security / deploy / general。
只输出 JSON：{{"tasks": [{{"title": "任务标题", "task_type": "类型"}}]}}"""

_DECOMPOSE_USER = """Goal: {goal}

Tech stack: {tech_stack}

只输出 JSON。"""


_STEP_SYSTEM = """{role}

# Tools (Windows cmd environment)
Available tools: {tools}

Tool contracts:
{contracts}

# Action format
Think briefly (at most 80 words, no long reasoning), then output exactly ONE action
as a JSON object inside an ```action fence:
```action
{{"kind": "<tool name or finish>", "args": {{"param": "value"}}, "note": "why"}}
```

# Rules (highest priority)
1. Windows commands only: use cd / dir / type / findstr / python,
   not pwd / ls / cat / grep / python3.
2. kind=finish ONLY when the goal is verifiably done (artifacts written and validated).
   If recent steps already show success, finish immediately instead of repeating.
3. One most-valuable action per step; the step budget is limited (see progress).
4. If the last identical action failed, change approach instead of retrying verbatim.
5. Bias toward action: as soon as you know what to write, write it with the file tool.
   Pure inspection (dir/type) is allowed at most 2 steps per task;
   from step 3 onward, either write the artifact or finish.
6. A successful terminal inspection is NOT progress: do not loop dir/type.
   Finish only when the declared artifact file actually exists.
7. If a pytest/test run fails, FIX the implementation or the test file with the
   file/patch tool next; never re-run the same failing command more than twice.
8. Do not blindly overwrite an existing file: read it first (file read) and keep
   the good parts when editing."""


_STEP_USER = """## Task
{task}

## Context
{context}

Give your brief reasoning, then exactly one action JSON inside an ```action fence.
If you already have enough information, produce the artifact in THIS step."""


_ACTION_FENCE_RE = re.compile(r"```(?:action|json)?\s*(.*?)```", re.DOTALL)
_DSML_TAG_RE = re.compile(r"<\s*/?\s*[^>]*DSML[^>]*>", re.IGNORECASE)


def parse_action_json(text: str) -> dict | None:
    """从 LLM 输出中提取动作 JSON，容忍 ```action/```json 围栏、DSML 包裹与前后杂文。
    解析失败返回 None（由调用方走回退路径）。"""
    stripped = _DSML_TAG_RE.sub("", text)
    for block in _ACTION_FENCE_RE.findall(stripped):
        candidate = block.strip()
        try:
            data = json.loads(candidate)
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(data, dict):
            return data
    start = stripped.find("{")
    while start != -1:
        depth = 0
        in_string = False
        escaped = False
        for index in range(start, len(stripped)):
            char = stripped[index]
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
                continue
            if char == '"':
                in_string = True
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    try:
                        data = json.loads(stripped[start:index + 1])
                    except (json.JSONDecodeError, TypeError):
                        break
                    return data if isinstance(data, dict) else None
        start = stripped.find("{", start + 1)
    return None


def _action_from_data(data: dict, thought: Thought) -> Action | None:
    """{kind, args, note} -> Action；finish/空 kind 按 finish 处理，非法 kind 返回 None。"""
    kind = str(data.get("kind") or "finish").strip()
    raw_args = data.get("args")
    args = (
        {str(k): str(v) for k, v in raw_args.items()}
        if isinstance(raw_args, dict)
        else {}
    )
    note = str(data.get("note") or "")
    if kind.lower() == "finish":
        return Action.finish(note=note or thought.content[:100])
    if not kind:
        return None
    return Action(kind=kind, args=args, note=note)


def make_step_fn(
    provider: LLMProvider,
    tool_names: Callable[[str], list[str]] | None = None,
    contracts: Callable[[str], str] | None = None,
    decide_fallback: DecideFn | None = None,
) -> StepFn:
    """一步式（reason+decide 合并）：一次 LLM 调用输出简短推理 + 动作 JSON。
    解析失败时回退 decide_fallback（再失败走规则 Planner）。
    相比「reason 长推理 + decide 二次调用」，可把单步延迟从 ~25s 降到 ~2s。"""

    def step(
        agent_name: str, role_prompt: str, task: str, context: str
    ) -> tuple[Thought, Action]:
        tools = tool_names(agent_name) if tool_names is not None else []
        details = contracts(agent_name) if contracts is not None else ""
        system = _STEP_SYSTEM.format(
            role=role_prompt,
            tools=", ".join(tools) if tools else "(none)",
            contracts=details or "(none)",
        )
        user = _STEP_USER.format(task=task, context=context)
        thought = Thought(agent_name=agent_name, task=task, content="")
        try:
            text = provider.complete(
                [ChatMessage(role="system", content=system),
                 ChatMessage(role="user", content=user)],
                temperature=0.2,
                max_tokens=2048,
            ).strip()
        except Exception:
            text = ""
        thought = Thought(agent_name=agent_name, task=task, content=text)
        data = parse_action_json(text) if text else None
        if data is not None:
            action = _action_from_data(data, thought)
            if action is not None:
                return thought, action
        if decide_fallback is not None:
            try:
                return thought, decide_fallback(thought)
            except Exception:
                pass
        return thought, Planner().decide(thought)

    return step


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
                max_tokens=512,
            )
        except Exception:
            return Planner().decide(thought)
        action = _action_from_data(data, thought)
        return action if action is not None else Planner().decide(thought)

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
            data = provider.complete_json(messages, temperature=0.0, max_tokens=512)
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
            data = provider.complete_json(messages, temperature=0.0, max_tokens=256)
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
            data = provider.complete_json(messages, temperature=0.2, max_tokens=1024)
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
