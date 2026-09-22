"""Agent Loop — 最核心部分（dev-notes/new.md「2. Agent Loop」）。

    while task_not_finished:
        context = memory.load()
        thought = agent.reason(task, context)
        action  = planner.decide(thought)
        result  = execute(action)
        memory.save(result)

循环协议由 AgentLoop 实现；「决定行动」由可注入的 decide_fn 提供
（默认由 planner.Planner.decide 承担），执行由 Agent 的工具完成。

Code Intelligence：repo_map_provider / code_snapshot_provider 在每步组装
上下文时注入（Repository Map / Existing Code）。
收敛与成本：Action.parallel 支持无依赖工具并行（ThreadPoolExecutor，
零依赖）；写文件动作自动捕获 unified diff 供 review 聚焦变更。
"""

from __future__ import annotations

import difflib
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from agent.core.agent import Agent, Thought
from agent.core.context import ContextBuilder
from agent.core.state import ProjectState
from agent.tools.base import Tool, ToolResult

if TYPE_CHECKING:
    from agent.memory.store import MemoryStore

# 仓库地图提供者：每次编码前读取项目结构（codebase/repository_map.py）
RepoMapProvider = Callable[[], str]
# 现有代码快照提供者：任务文本 -> 检索到的相关代码（codebase/search.py）
CodeSnapshotProvider = Callable[[str], str]

# 单文件 diff 最多保留行数（超出截断），控制上下文体积
_MAX_DIFF_LINES = 60
# diff 文本总字符上限
_MAX_DIFF_CHARS = 4000
# 并行工具默认最大并发数
_DEFAULT_MAX_PARALLEL = 8


@dataclass(frozen=True)
class Action:
    """一次可执行的行动：调用哪个工具、带什么参数。

    kind="finish" 表示当前任务完成，退出循环。
    parallel 支持一次提交多个「无依赖」子动作，由 AgentLoop 并发执行
    （子动作路径重叠时自动退化为顺序执行）。
    """

    kind: str  # 工具名，或 "finish"
    args: dict[str, str] = field(default_factory=dict)
    note: str = ""
    parallel: tuple[Action, ...] = ()  # 无依赖子动作组（AgentLoop 并发执行）

    @classmethod
    def finish(cls, note: str = "") -> Action:
        return cls(kind="finish", note=note)


# 决策函数：思考 → 行动（生产环境由 Planner/LLM 提供）
DecideFn = Callable[[Thought], Action]
# 一步式（思考+决策合并）：(agent_name, role_prompt, task, context) -> (Thought, Action)
StepFn = Callable[[str, str, str, str], tuple[Thought, Action]]

# 工具参数中表示文件路径的键名（收集 touched paths，用于终审审计范围）
_PATH_ARG_KEYS = ("path", "file", "file_path", "output_path")


def _action_paths(action: Action) -> tuple[str, ...]:
    """从动作参数中提取文件路径（去重保序）。"""
    paths: list[str] = []
    for key in _PATH_ARG_KEYS:
        value = action.args.get(key)
        if isinstance(value, str) and value.strip():
            paths.append(value.strip())
    return tuple(paths)


def _action_key(action: Action) -> tuple:
    """动作指纹：识别「重复成功动作」的兜底强制 finish。"""
    if action.parallel:
        return ("parallel", tuple(_action_key(sub) for sub in action.parallel))
    return (action.kind, frozenset(action.args.items()))


def _shared_paths(batch: tuple[Action, ...]) -> bool:
    """启发式依赖检测：任一路径出现在多个子动作中即视为有依赖。"""
    seen: set[str] = set()
    for action in batch:
        for path in _action_paths(action):
            if path in seen:
                return True
            seen.add(path)
    return False


@dataclass(frozen=True)
class LoopResult:
    """一轮循环运行的结果。"""

    steps: int
    finished: bool
    history: tuple[str, ...]
    touched_paths: tuple[str, ...] = ()  # 本次循环成功动作写入的文件路径
    diff: str = ""  # 本任务实际改动的 unified diff（review 聚焦变更）


@dataclass
class AgentLoop:
    """主控制循环。"""

    agent: Agent
    decide_fn: DecideFn
    state: ProjectState
    memory: MemoryStore | None = None
    context_builder: ContextBuilder = field(default_factory=ContextBuilder)
    max_steps: int = 10  # 防失控上限（收敛控制）
    repo_map_provider: RepoMapProvider | None = None  # Code Intelligence 注入
    code_snapshot_provider: CodeSnapshotProvider | None = None  # Existing Code 注入
    step_fn: StepFn | None = None  # 一步式 reason+decide（LLM 版快路径，可选）
    step_observer: Callable[[str, str], None] | None = None  # 每步历史回调（前端流式展示）
    max_parallel: int = _DEFAULT_MAX_PARALLEL  # 并行工具最大并发数
    _diffs: list[str] = field(default_factory=list, init=False, repr=False)

    def run(self, task: str) -> LoopResult:
        """对单个任务执行 思考→决策→执行→记录 循环，直到 finish。

        兜底规则：连续两次「相同工具 + 相同参数且成功」视为重复劳动，
        强制 finish，防止 LLM 反复执行同一动作。
        """
        history: list[str] = []
        touched: list[str] = []
        self._diffs = []
        last_success: tuple | None = None
        self.state.current_agent = self.agent.name
        # 每步「五拍」：拼装上下文 → 思考/决策 → 判定 finish → 执行 → 记录。
        # 上下文每步从头 one-shot 拼接（无增量压缩，见 dev-notes 上下文策略回退记录）。
        for step in range(1, self.max_steps + 1):
            # 1) 拼装上下文：状态 + RepoMap + 失败记忆 + 历史 + Existing Code
            context = self.context_builder.build(
                user_task=self.state.task or task,
                state=self.state,
                memory=self.memory,
                current_task=task,
                repo_map=self.repo_map_provider() if self.repo_map_provider else "",
                code_snapshot=(
                    self.code_snapshot_provider(task)
                    if self.code_snapshot_provider
                    else ""
                ),
                history=history,
            )
            # 步数压力提示：让 LLM 在预算内收敛，避免无意义重复
            context += f"\n\n## Progress\nStep {step}/{self.max_steps} for this task. " \
                       "Finish as soon as the goal is met; avoid repeating successful steps."
            # 2) 思考 + 3) 决策：快路径 step_fn 一次调用（思考+决策合并）；
            #    慢路径 reason_fn + decide_fn 两次调用（兼容规则 Planner）
            if self.step_fn is not None:
                thought, action = self.step_fn(
                    self.agent.name, self.agent.role_prompt(), task, context
                )
            else:
                thought = self.agent.reason(task, context)
                action = self.decide_fn(thought)
            if action.kind == "finish":
                history.append(f"step {step}: finish ({action.note})")
                self.state.mark_completed(task)
                self._persist(history[-1])
                return self._result(step, True, history, touched)
            # 4) 执行工具（支持无依赖并行；写动作前后快照生成 diff 供 review）
            result = self._execute(action)
            status = "ok" if result.ok else "fail"
            brief_args = {k: v for k, v in action.args.items() if k != "content"}
            args_text = ", ".join(f"{k}={v[:60]}" for k, v in brief_args.items())
            if action.parallel:
                entry = f"step {step}: parallel x{len(action.parallel)} -> {status}"
            else:
                entry = f"step {step}: {action.kind} -> {status}"
            if args_text:
                entry += f" [{args_text}]"
            if action.parallel and result.output:
                entry += f" [{result.output[:200]}]"
            if not result.ok:
                # 失败原因反馈给下一轮，LLM 才能针对性修正
                entry += f": {result.output[:200]}"
            history.append(entry)
            if not result.ok:
                self.state.record_error(f"{action.kind}: {result.output[:200]}")
            self._persist(entry)
            # 5) 记录本步结果；成功动作收集写入路径（终审审计范围）
            if result.ok:
                for sub in action.parallel or (action,):
                    for path in _action_paths(sub):
                        if path not in touched:
                            touched.append(path)
            # 兜底：连续两次相同成功动作 → 强制 finish
            if result.ok:
                action_key = _action_key(action)
                if action_key == last_success:
                    finish_entry = (
                        f"step {step}: auto-finish "
                        f"(repeated identical successful action: {action.kind})"
                    )
                    history.append(finish_entry)
                    self._persist(finish_entry)
                    self.state.mark_completed(task)
                    return self._result(step, True, history, touched)
                last_success = action_key
        return self._result(self.max_steps, False, history, touched)

    def _result(
        self, steps: int, finished: bool, history: list[str], touched: list[str]
    ) -> LoopResult:
        return LoopResult(
            steps=steps,
            finished=finished,
            history=tuple(history),
            touched_paths=tuple(touched),
            diff="\n".join(self._diffs),
        )

    def _execute(self, action: Action) -> ToolResult:
        if action.parallel:
            return self._execute_parallel(action.parallel)
        return self._run_one(action)

    def _run_one(self, action: Action) -> ToolResult:
        # LLM 可能决策出未注册的工具名：转为失败记录，不炸掉循环
        try:
            tool = self.agent.find_tool(action.kind)
        except KeyError as exc:
            return ToolResult.failure(f"unknown tool: {exc}")
        before = self._capture_diffs(action, tool)
        result = tool.run(**action.args)
        if result.ok:
            diff = self._diff_after(before)
            if diff:
                self._diffs.append(diff)
        return result

    def _execute_parallel(self, batch: tuple[Action, ...]) -> ToolResult:
        """并发执行无依赖子动作；路径重叠时退化为顺序执行保证安全。"""
        if _shared_paths(batch):
            results = [self._run_one(action) for action in batch]
        else:
            workers = min(len(batch), max(1, self.max_parallel))
            with ThreadPoolExecutor(max_workers=workers) as pool:
                results = list(pool.map(self._run_one, batch))
        parts: list[str] = []
        for action, result in zip(batch, results, strict=True):
            tag = "ok" if result.ok else "fail"
            detail = f": {result.output[:120]}" if not result.ok else ""
            parts.append(f"{action.kind}->{tag}{detail}")
        return ToolResult(
            ok=all(result.ok for result in results),
            output=" | ".join(parts),
        )

    def _capture_diffs(self, action: Action, tool: Tool) -> dict[str, str]:
        """写动作前记录目标文件快照（只对声明 workspace 的写工具生效）。"""
        workspace = getattr(tool, "workspace", None)
        if workspace is None or action.kind not in ("file", "patch"):
            return {}
        op = action.args.get("operation", "")
        writes_new = (
            action.kind == "file"
            and op in ("", "write")
            and "content" in action.args
        ) or (action.kind == "patch" and op == "apply")
        before: dict[str, str] = {}
        for key in _PATH_ARG_KEYS:
            raw = action.args.get(key)
            if not raw:
                continue
            try:
                path = self._resolve_workspace_path(workspace, raw)
            except OSError:
                continue
            if path.is_file():
                try:
                    before[path.as_posix()] = path.read_text(
                        encoding="utf-8", errors="replace"
                    )
                except OSError:
                    continue
            elif writes_new:
                before[path.as_posix()] = ""
        return before

    @staticmethod
    def _resolve_workspace_path(workspace: object, raw: str) -> Path:
        root = Path(workspace).resolve()
        if Path(raw).is_absolute():
            return Path(raw).resolve()
        return (root / raw).resolve()

    def _diff_after(self, before: dict[str, str]) -> str:
        """与写后内容对比生成 unified diff（未变化返回空串）。"""
        chunks: list[str] = []
        for raw, old_text in before.items():
            path = Path(raw)
            try:
                new_text = (
                    path.read_text(encoding="utf-8", errors="replace")
                    if path.is_file()
                    else ""
                )
            except OSError:
                continue
            if old_text == new_text:
                continue
            diff = "".join(
                difflib.unified_diff(
                    old_text.splitlines(keepends=True),
                    new_text.splitlines(keepends=True),
                    fromfile=f"a/{path.name}",
                    tofile=f"b/{path.name}",
                )
            )
            lines = diff.splitlines(keepends=True)
            if len(lines) > _MAX_DIFF_LINES:
                lines = lines[:_MAX_DIFF_LINES] + ["... (diff truncated)\n"]
            chunks.append("".join(lines))
        combined = "\n".join(chunks)
        if len(combined) > _MAX_DIFF_CHARS:
            combined = combined[:_MAX_DIFF_CHARS] + "\n... (diff truncated)"
        return combined

    def _persist(self, entry: str) -> None:
        if self.memory is not None:
            self.memory.append_history(self.agent.name, entry)
        if self.step_observer is not None:
            self.step_observer(self.agent.name, entry)
