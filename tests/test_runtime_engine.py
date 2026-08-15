"""agent/ 运行时引擎测试（new.md 可执行系统）。

全部使用桩 reason_fn / 假工具，不依赖真实 LLM 与网络。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from agent.agents.developer import DeveloperAgent
from agent.audit.audit_agent import AuditAgent
from agent.communication.message import Message, MessageBus, MessageType, TaskResult
from agent.core.agent import Agent, Thought
from agent.core.context import ContextBuilder
from agent.core.loop import Action, AgentLoop
from agent.core.state import PHASES, PhaseStatus, ProjectState
from agent.memory.store import MemoryStore
from agent.planner.decomposition import decompose
from agent.planner.planner import Planner
from agent.planner.task_tree import TaskNode, TaskTree
from agent.reflection.reflector import Reflector
from agent.router.router import AgentRouter
from agent.tools.base import Tool, ToolResult
from agent.tools.file import FileTool
from agent.tools.git import GitTool
from agent.tools.terminal import TerminalTool

# --- 测试用假工具 ---


class EchoTool(Tool):
    name = "echo"

    def __init__(self) -> None:
        self.calls: list[dict[str, str]] = []

    def run(self, **kwargs: str) -> ToolResult:
        self.calls.append(dict(kwargs))
        return ToolResult.success(kwargs.get("text", ""))


class FailTool(Tool):
    name = "boom"

    def run(self, **kwargs: str) -> ToolResult:
        return ToolResult.failure("boom exploded")


class ScriptedTerminal(Tool):
    """按脚本返回测试结果的假 terminal。"""

    name = "terminal"

    def __init__(self, results: list[ToolResult]) -> None:
        self.results = list(results)

    def run(self, **kwargs: str) -> ToolResult:
        if len(self.results) > 1:
            return self.results.pop(0)
        return self.results[0]


def make_agent(
    tmp_path: Path,
    responses: list[str],
    tools: list[Tool] | None = None,
) -> Agent:
    """构造带临时角色文件与脚本化 reason_fn 的 Agent。"""
    roles = tmp_path / "roles"
    roles.mkdir(exist_ok=True)
    (roles / "dev.md").write_text("# Dev\n职责：写码。\n", encoding="utf-8")
    script = list(responses)

    def reason_fn(role_prompt: str, task: str, context: str) -> str:
        assert "职责" in role_prompt
        return script.pop(0) if len(script) > 1 else script[0]

    return Agent(
        name="Dev",
        role="dev.md",
        tools=tools or [],
        reason_fn=reason_fn,
        roles_dir=roles,
    )


# --- core.agent ---


def test_agent_role_prompt_and_reason(tmp_path: Path) -> None:
    agent = make_agent(tmp_path, ["thinking..."])
    thought = agent.reason("do it", "ctx")
    assert thought == Thought(agent_name="Dev", task="do it", content="thinking...")


def test_agent_missing_role_file_raises(tmp_path: Path) -> None:
    agent = Agent(name="X", role="nope.md", roles_dir=tmp_path)
    with pytest.raises(FileNotFoundError):
        agent.role_prompt()


def test_agent_find_tool(tmp_path: Path) -> None:
    echo = EchoTool()
    agent = make_agent(tmp_path, ["x"], tools=[echo])
    assert agent.find_tool("echo") is echo
    with pytest.raises(KeyError):
        agent.find_tool("missing")


# --- core.state ---


def test_state_phase_advance_and_rollback() -> None:
    state = ProjectState(task="t")
    assert state.phase == PHASES[0]
    state.advance_phase()
    state.advance_phase()
    assert state.phase == "architecture"
    state.rollback_to("planning")
    assert state.phase == "planning"
    with pytest.raises(ValueError):
        state.rollback_to("delivery")  # 不能向前回退
    with pytest.raises(ValueError):
        state.rollback_to("nonsense")


def test_state_save_load_roundtrip(tmp_path: Path) -> None:
    state = ProjectState(task="build", phase="testing", current_agent="Tester")
    state.mark_completed("api")
    state.record_error("oops")
    path = tmp_path / "state.json"
    state.save(path)
    loaded = ProjectState.load(path)
    assert loaded == state
    assert "build" in loaded.summary()


# --- core.context ---


def test_context_builder_sections(tmp_path: Path) -> None:
    knowledge = tmp_path / "knowledge"
    knowledge.mkdir()
    (knowledge / "coding_standard.md").write_text("规范内容", encoding="utf-8")
    builder = ContextBuilder(agent_root=tmp_path, knowledge_files=["coding_standard.md"])
    state = ProjectState(task="build site")
    context = builder.build(
        user_task="build site",
        state=state,
        current_task="write api",
        code_snapshot="def f(): ...",
    )
    assert "## User Task" in context
    assert "## Project State" in context
    assert "## Knowledge: coding_standard.md" in context
    assert "## Current Task" in context
    assert "## Existing Code" in context


# --- core.loop ---


def test_loop_runs_tool_then_finishes(tmp_path: Path) -> None:
    echo = EchoTool()
    agent = make_agent(
        tmp_path,
        ["ACTION: echo\nARG text=hello", "全部完成"],
        tools=[echo],
    )
    state = ProjectState(task="demo")
    loop = AgentLoop(agent=agent, decide_fn=Planner().decide, state=state)
    result = loop.run("demo")
    assert result.finished and result.steps == 2
    assert echo.calls == [{"text": "hello"}]
    assert "demo" in state.completed


def test_loop_records_tool_failure(tmp_path: Path) -> None:
    agent = make_agent(tmp_path, ["ACTION: boom", "done"], tools=[FailTool()])
    state = ProjectState(task="demo")
    result = AgentLoop(agent=agent, decide_fn=Planner().decide, state=state).run("demo")
    assert result.finished
    assert state.errors and "boom" in state.errors[0]


def test_loop_max_steps_guard(tmp_path: Path) -> None:
    # 参数每步不同，避免触发「重复成功动作自动 finish」兜底，验证步数上限
    agent = make_agent(
        tmp_path,
        [
            "ACTION: echo\nARG text=again1",
            "ACTION: echo\nARG text=again2",
            "ACTION: echo\nARG text=again3",
        ],
        tools=[EchoTool()],
    )
    loop = AgentLoop(
        agent=agent,
        decide_fn=Planner().decide,
        state=ProjectState(task="x"),
        max_steps=3,
    )
    result = loop.run("x")
    assert not result.finished and result.steps == 3


def test_loop_auto_finishes_on_repeated_success(tmp_path: Path) -> None:
    # 连续两次相同工具 + 相同参数且成功 → 规则兜底强制 finish
    agent = make_agent(tmp_path, ["ACTION: echo\nARG text=again"], tools=[EchoTool()])
    state = ProjectState(task="x")
    loop = AgentLoop(
        agent=agent,
        decide_fn=Planner().decide,
        state=state,
        max_steps=10,
    )
    result = loop.run("x")
    assert result.finished and result.steps == 2
    assert "auto-finish" in result.history[-1]
    assert "x" in state.completed


def test_loop_auto_finish_ignores_failures(tmp_path: Path) -> None:
    # 失败动作不计数：ok 与 fail 交替不会触发兜底
    agent = make_agent(
        tmp_path,
        ["ACTION: boom", "ACTION: echo\nARG text=ok"],
        tools=[EchoTool(), FailTool()],
    )
    result = AgentLoop(
        agent=agent, decide_fn=Planner().decide, state=ProjectState(task="x")
    ).run("x")
    assert result.finished


def test_loop_unknown_tool_records_error_not_crash(tmp_path: Path) -> None:
    agent = make_agent(tmp_path, ["ACTION: ghost", "done"], tools=[EchoTool()])
    state = ProjectState(task="x")
    result = AgentLoop(agent=agent, decide_fn=Planner().decide, state=state).run("x")
    assert result.finished
    assert state.errors and "unknown tool" in state.errors[0]


# --- planner ---


def test_planner_decide_parses_action() -> None:
    thought = Thought("A", "t", "先看一下\nACTION: file\nARG path=a.py\nARG operation=read")
    action = Planner().decide(thought)
    assert action == Action(kind="file", args={"path": "a.py", "operation": "read"})


def test_planner_decide_defaults_to_finish() -> None:
    action = Planner().decide(Thought("A", "t", "没有更多要做的了"))
    assert action.kind == "finish"


def test_decompose_builds_lifecycle_tree() -> None:
    tree = decompose("开发一个类似 Steam 的游戏平台网站")
    titles = [node.title for node in tree.flatten()]
    assert "Requirement" in titles and "Architecture" in titles
    assert "Implementation" in titles and "Deploy" in titles
    impl = next(n for n in tree.flatten() if n.title == "Implementation")
    assert {c.task_type for c in impl.children} >= {"frontend", "backend"}


def test_task_tree_next_task_depth_first() -> None:
    root = TaskNode(title="ROOT", task_type="root")
    a = root.add(TaskNode(title="A", task_type="backend"))
    b = root.add(TaskNode(title="B", task_type="testing"))
    tree = TaskTree(root=root)
    assert tree.next_task() is a
    a.status = PhaseStatus.DONE
    assert tree.next_task() is b
    b.status = PhaseStatus.DONE
    assert tree.next_task() is None
    assert tree.is_finished()
    assert "[x] A" in tree.render()


# --- router ---


def test_router_routes_by_type_map(tmp_path: Path) -> None:
    backend = make_agent(tmp_path, ["x"])
    backend.name = "Backend"
    router = AgentRouter()
    router.register(backend)
    assert router.route(TaskNode(title="写 API", task_type="backend")) is backend


def test_router_llm_fallback_and_error(tmp_path: Path) -> None:
    helper = make_agent(tmp_path, ["x"])
    helper.name = "Helper"
    router = AgentRouter(llm_route_fn=lambda title, names: "Helper")
    router.register(helper)
    assert router.route(TaskNode(title="奇怪任务", task_type="unknown")) is helper
    empty = AgentRouter()
    with pytest.raises(LookupError):
        empty.route(TaskNode(title="没人接", task_type="unknown"))


# --- communication ---


def test_message_bus_delivery_and_log() -> None:
    bus = MessageBus()
    msg = Message(sender="architect", receiver="backend", type=MessageType.TASK, content="实现认证")
    bus.send(msg)
    assert bus.pending("backend") == 1
    received = bus.receive("backend")
    assert received == [msg]
    assert bus.pending("backend") == 0
    assert bus.history() == (msg,)
    assert msg.to_dict()["type"] == "task"


def test_task_result_ok() -> None:
    assert TaskResult(status="done", files=("user.py",)).ok
    assert not TaskResult(status="failed").ok


# --- memory ---


def test_memory_store_decisions_and_failures(tmp_path: Path) -> None:
    store = MemoryStore(root=tmp_path)
    store.append_decision("用 SQLite", "本地开发用 SQLite", "零依赖", "Architect")
    store.append_failure("端口冲突", "8000 被占用", "启动前检查端口", "DevOps")
    assert "D-1" in store.recent_decisions()
    assert "用 SQLite" in store.recent_decisions()
    assert "F-1" in store.recent_failures()


def test_memory_store_skips_template_code_block(tmp_path: Path) -> None:
    log = tmp_path / "decision_log.md"
    log.write_text(
        "# Decision Log\n\n```markdown\n## D-0: 模板示例\n```\n\n## D-1: 真实决策\n内容\n",
        encoding="utf-8",
    )
    recent = MemoryStore(root=tmp_path).recent_decisions()
    assert "真实决策" in recent and "模板示例" not in recent


def test_memory_store_numbering_ignores_template(tmp_path: Path) -> None:
    # 真实模板里的「## D-<编号>」在代码块内，不得计入编号
    template = "# Decision Log\n\n```markdown\n## D-<编号>: <决策标题>\n```\n\n---\n"
    (tmp_path / "decision_log.md").write_text(template, encoding="utf-8")
    store = MemoryStore(root=tmp_path)
    store.append_decision("首条", "d", "r", "Architect")
    text = (tmp_path / "decision_log.md").read_text(encoding="utf-8")
    assert "## D-1: 首条" in text and "## D-2" not in text


def test_memory_store_history_jsonl(tmp_path: Path) -> None:
    store = MemoryStore(root=tmp_path)
    store.append_history("Dev", "step 1: finish")
    store.append_history("Dev", "step 2: finish")
    records = store.load_history()
    assert len(records) == 2
    assert records[0] == {"agent": "Dev", "entry": "step 1: finish"}


# --- tools ---


def test_terminal_tool_blocks_dangerous_command(tmp_path: Path) -> None:
    tool = TerminalTool(cwd=tmp_path)
    result = tool.run(command="rm -rf /")
    assert not result.ok and "blocked" in result.output
    assert not tool.run(command="").ok


def test_terminal_tool_runs_echo(tmp_path: Path) -> None:
    result = TerminalTool(cwd=tmp_path).run(command="echo hi")
    assert result.ok and "hi" in result.output


def test_file_tool_write_read_and_escape(tmp_path: Path) -> None:
    tool = FileTool(workspace=tmp_path)
    assert tool.run(operation="write", path="pkg/mod.py", content="x = 1\n").ok
    read = tool.run(operation="read", path="pkg/mod.py")
    assert read.ok and read.output == "x = 1\n"
    assert tool.run(operation="exists", path="pkg/mod.py").output == "True"
    escape = tool.run(operation="read", path="../outside.txt")
    assert not escape.ok and "escapes workspace" in escape.output


def test_git_tool_whitelist_and_commit_prefix(tmp_path: Path) -> None:
    tool = GitTool(cwd=tmp_path)
    assert not tool.run(subcommand="push").ok  # 白名单外
    bad = tool.run(subcommand="commit", message="随便写的信息")
    assert not bad.ok and "must start with" in bad.output


def test_browser_tool_rejects_bad_input() -> None:
    from agent.tools.browser import BrowserTool

    tool = BrowserTool()
    assert not tool.run(url="").ok
    assert not tool.run(url="ftp://example.com").ok
    malformed = tool.run(url="http://[bad")  # 畸形 URL 不应抛异常
    assert not malformed.ok and "fetch failed" in malformed.output


# --- reflection ---


def test_reflector_default_digest() -> None:
    output = "collected 3 items\nFAILED tests/test_a.py::test_x - assert 1 == 2\nok line"
    fix_task = Reflector().plan_fix("实现登录", output)
    assert "FAILED tests/test_a.py::test_x" in fix_task
    assert "实现登录" in fix_task


def test_reflector_uses_injected_analyzer() -> None:
    reflector = Reflector(analyze_fn=lambda task, out: f"fix:{task}")
    assert reflector.plan_fix("t", "whatever") == "fix:t"


# --- developer agent ---


def _make_developer(
    tmp_path: Path,
    terminal: ScriptedTerminal,
    with_reflector: bool = True,
) -> DeveloperAgent:
    inner = make_agent(tmp_path, ["实现完成，无需更多操作"], tools=[terminal])
    return DeveloperAgent(
        inner=inner,
        planner=Planner(),
        state=ProjectState(task="feature"),
        memory=MemoryStore(root=tmp_path / "mem"),
        reflector=Reflector() if with_reflector else None,
        context_builder=ContextBuilder(agent_root=tmp_path),
    )


def test_developer_pass_first_attempt(tmp_path: Path) -> None:
    dev = _make_developer(tmp_path, ScriptedTerminal([ToolResult.success("1 passed")]))
    result = dev.develop("实现功能")
    assert result.finished and result.test_passed and result.attempts == 1


def test_developer_reflection_fix_loop(tmp_path: Path) -> None:
    terminal = ScriptedTerminal(
        [ToolResult.failure("FAILED test_a"), ToolResult.success("2 passed")]
    )
    result = _make_developer(tmp_path, terminal).develop("实现功能")
    assert result.finished and result.test_passed and result.attempts == 2


def test_developer_every_fix_round_is_verified(tmp_path: Path) -> None:
    # 2 次失败 + 1 次成功：第二轮修复后的重测必须被执行到
    terminal = ScriptedTerminal(
        [
            ToolResult.failure("FAILED test_a"),
            ToolResult.failure("FAILED test_a"),
            ToolResult.success("3 passed"),
        ]
    )
    result = _make_developer(tmp_path, terminal).develop("实现功能")
    assert result.finished and result.test_passed and result.attempts == 3


def test_developer_fix_rounds_exhausted_records_failure(tmp_path: Path) -> None:
    dev = _make_developer(tmp_path, ScriptedTerminal([ToolResult.failure("FAILED forever")]))
    result = dev.develop("实现功能")
    assert result.finished and not result.test_passed
    assert result.detail == "fix rounds exhausted"
    failures = (tmp_path / "mem" / "failure_memory.md").read_text(encoding="utf-8")
    assert "tests still failing" in failures


# --- audit ---


def test_audit_flags_dangerous_code_and_missing_docs(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "bad.py").write_text(
        'password = "supersecret123"\nresult = eval(user_input)\n',
        encoding="utf-8",
    )
    report = AuditAgent(project_root=project).audit()
    names = {f.description for f in report.findings}
    assert "hardcoded secret" in names and "eval/exec usage" in names
    assert "required delivery document missing" in names
    assert not report.passed
    markdown = report.to_markdown()
    assert "Conclusion: FAIL" in markdown and "[CRITICAL]" in markdown


def test_audit_passes_clean_project(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "good.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    for doc in ("architecture.md", "test_report.md", "security_report.md", "deployment.md"):
        (project / doc).write_text("# ok\n", encoding="utf-8")
    root = TaskNode(title="ROOT", task_type="root")
    root.add(TaskNode(title="A", task_type="backend", status=PhaseStatus.DONE))
    report = AuditAgent(project_root=project).audit(TaskTree(root=root))
    assert report.passed and report.completion_rate == 1.0
    assert "Conclusion: PASS" in report.to_markdown()


def test_audit_incomplete_tree_blocks_pass(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    root = TaskNode(title="ROOT", task_type="root")
    root.add(TaskNode(title="A", task_type="backend", status=PhaseStatus.DONE))
    root.add(TaskNode(title="B", task_type="testing"))
    report = AuditAgent(project_root=project).audit(TaskTree(root=root))
    assert report.completion_rate == 0.5
    assert any("completion" in f.description for f in report.findings)
    assert not report.passed


def test_audit_write_report(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    agent = AuditAgent(project_root=project)
    path = agent.write_report(agent.audit())
    assert path.name == "final_report.md"
    assert "# Final Report" in path.read_text(encoding="utf-8")
