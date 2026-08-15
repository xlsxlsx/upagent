"""One-shot step_fn (reason+decide merged) and action-JSON parsing tests.

All offline with fake providers; real DeepSeek calls live in scripts/llm_demo.py.
"""

from __future__ import annotations

from pathlib import Path

from agent.core.agent import Agent, Thought
from agent.core.loop import Action, AgentLoop, LoopResult
from agent.core.state import ProjectState
from agent.llm.bindings import make_step_fn, parse_action_json
from agent.planner.task_tree import TaskNode
from agent.router.router import AgentRouter
from agent.supervisor.supervisor import Supervisor

# --- parse_action_json ---


def test_parse_action_json_plain_object() -> None:
    assert parse_action_json('{"kind": "finish", "note": "ok"}') == {
        "kind": "finish",
        "note": "ok",
    }


def test_parse_action_json_tolerates_action_fence() -> None:
    text = 'brief reasoning\n```action\n{"kind": "terminal", "args": {"command": "dir"}}\n```'
    data = parse_action_json(text)
    assert data == {"kind": "terminal", "args": {"command": "dir"}}


def test_parse_action_json_tolerates_json_fence() -> None:
    text = '```json\n{"kind": "finish"}\n```'
    assert parse_action_json(text) == {"kind": "finish"}


def test_parse_action_json_tolerates_dsml_wrapper() -> None:
    text = '<|DSML|result>\n{"kind": "finish", "note": "done"}\n</|DSML|result>'
    assert parse_action_json(text) == {"kind": "finish", "note": "done"}


def test_parse_action_json_balanced_scan_with_noise() -> None:
    text = 'prefix noise {"kind": "file", "args": {"path": "a.py"}} suffix'
    assert parse_action_json(text) == {"kind": "file", "args": {"path": "a.py"}}


def test_parse_action_json_garbage_returns_none() -> None:
    assert parse_action_json("no json here at all") is None


# --- make_step_fn ---


class _FixedProvider:
    """Returns a fixed text and counts complete() calls."""

    def __init__(self, text: str) -> None:
        self.text = text
        self.calls = 0

    def complete(self, messages, **kwargs) -> str:
        self.calls += 1
        return self.text


def test_step_fn_single_call_parses_action() -> None:
    text = (
        'short reasoning\n```action\n'
        '{"kind": "file", "args": {"path": "a.py"}, "note": "write"}\n```'
    )
    provider = _FixedProvider(text)
    step = make_step_fn(
        provider,
        tool_names=lambda name: ["file"],
        contracts=lambda name: "file: operation(read|write|exists), path, content",
    )
    thought, action = step("Backend", "role prompt", "write a.py", "context")
    assert provider.calls == 1
    assert isinstance(thought, Thought) and thought.agent_name == "Backend"
    assert action.kind == "file" and action.args == {"path": "a.py"}


def test_step_fn_falls_back_to_decide_fn() -> None:
    provider = _FixedProvider("garbage without json")
    fallback_calls: list[int] = []

    def decide_fallback(thought: Thought) -> Action:
        fallback_calls.append(1)
        return Action.finish("fallback used")

    step = make_step_fn(provider, decide_fallback=decide_fallback)
    thought, action = step("Backend", "role", "task", "context")
    assert fallback_calls == [1]
    assert action.kind == "finish" and action.note == "fallback used"


def test_step_fn_rule_fallback_without_decide() -> None:
    provider = _FixedProvider("garbage")
    step = make_step_fn(provider)
    thought, action = step("Backend", "role", "task", "context")
    assert isinstance(action, Action) and action.kind == "finish"


# --- AgentLoop fast path ---


def _loop_agent(tmp_path: Path) -> Agent:
    roles = tmp_path / "roles"
    roles.mkdir(exist_ok=True)
    (roles / "dev.md").write_text("# Dev\nwrite code.\n", encoding="utf-8")
    return Agent(
        name="Dev",
        role="dev.md",
        reason_fn=lambda role_prompt, task, context: "unused",
        roles_dir=roles,
    )


def test_loop_uses_step_fn_instead_of_reason_decide(tmp_path: Path) -> None:
    calls: list[tuple[str, str]] = []

    def step_fn(agent_name: str, role_prompt: str, task: str, context: str):
        calls.append((agent_name, task))
        thought = Thought(agent_name=agent_name, task=task, content="one-shot")
        return thought, Action.finish("done")

    agent = _loop_agent(tmp_path)
    loop = AgentLoop(
        agent=agent,
        decide_fn=lambda thought: Action(kind="never-called"),
        state=ProjectState(task="x"),
        step_fn=step_fn,
    )
    result = loop.run("write x")
    assert result.finished and result.steps == 1
    assert calls == [("Dev", "write x")]
    assert result.history == ("step 1: finish (done)",)


# --- Supervisor deterministic artifact witness ---


def _witness_supervisor(tmp_path: Path) -> Supervisor:
    return Supervisor(
        router=AgentRouter(),
        decide_fn=lambda thought: Action.finish("ok"),
        state=ProjectState(),
        output_dir=tmp_path,
    )


def test_review_witness_rejects_missing_file(tmp_path: Path) -> None:
    supervisor = _witness_supervisor(tmp_path)
    node = TaskNode(title="create hello.py and verify output", task_type="backend")
    result = LoopResult(steps=1, finished=True, history=("step 1: finish",))
    assert supervisor._review(node, result) is False
    assert any("missing artifact" in err for err in supervisor.state.errors)


def test_review_witness_passes_when_file_exists(tmp_path: Path) -> None:
    supervisor = _witness_supervisor(tmp_path)
    (tmp_path / "hello.py").write_text("print('hi')\n", encoding="utf-8")
    node = TaskNode(title="create hello.py and verify output", task_type="backend")
    result = LoopResult(steps=1, finished=True, history=("step 1: finish",))
    assert supervisor._review(node, result) is True


def test_review_witness_skips_titles_without_paths(tmp_path: Path) -> None:
    supervisor = _witness_supervisor(tmp_path)
    node = TaskNode(title="implement quick sort algorithm", task_type="backend")
    result = LoopResult(steps=1, finished=True, history=("step 1: finish",))
    assert supervisor._review(node, result) is True


def test_review_tests_gate_rejects_failing_pytest(tmp_path: Path) -> None:
    supervisor = _witness_supervisor(tmp_path)
    (tmp_path / "test_sample.py").write_text(
        "def test_fail():\n    assert False\n", encoding="utf-8"
    )
    node = TaskNode(title="write and run pytest", task_type="testing")
    result = LoopResult(steps=1, finished=True, history=("step 1: finish",))
    assert supervisor._review(node, result) is False
    assert any("tests failed" in err for err in supervisor.state.errors)


def test_review_tests_gate_accepts_green_pytest(tmp_path: Path) -> None:
    supervisor = _witness_supervisor(tmp_path)
    (tmp_path / "test_sample.py").write_text(
        "def test_pass():\n    assert True\n", encoding="utf-8"
    )
    node = TaskNode(title="write and run pytest", task_type="testing")
    result = LoopResult(steps=1, finished=True, history=("step 1: finish",))
    assert supervisor._review(node, result) is True


def test_review_tests_gate_skips_without_tests(tmp_path: Path) -> None:
    supervisor = _witness_supervisor(tmp_path)
    node = TaskNode(title="write and run pytest", task_type="testing")
    result = LoopResult(steps=1, finished=True, history=("step 1: finish",))
    assert supervisor._review(node, result) is True
