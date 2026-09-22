"""LLM 接入层测试：config / provider / bindings，全部离线（mock httpx 与 fake provider）。

真实 DeepSeek 调用见 scripts/llm_demo.py（需 .env 配置密钥）。
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from agent.core.agent import Thought
from agent.core.loop import Action
from agent.llm.bindings import (
    make_decide_fn,
    make_decompose_fn,
    make_reason_fn,
    make_review_fn,
    make_route_fn,
)
from agent.llm.config import LLMConfig, config_from_env, load_dotenv
from agent.llm.provider import (
    ChatMessage,
    LLMError,
    OpenAICompatibleProvider,
    parse_json_response,
)
from agent.planner.task_tree import TaskNode

# --- config ---


def test_load_dotenv_reads_env_file(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "# comment\nDEEPSEEK_API_KEY=sk-test-123\nDEEPSEEK_MODEL=deepseek-v4-flash\n\n",
        encoding="utf-8",
    )
    assert load_dotenv(env_file) == env_file
    assert __import__("os").environ["DEEPSEEK_API_KEY"] == "sk-test-123"


def test_config_from_env_requires_key() -> None:
    with pytest.raises(ValueError, match="DEEPSEEK_API_KEY"):
        config_from_env({}, require_key=True)


def test_config_from_env_parses_values(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-x")
    monkeypatch.setenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    monkeypatch.setenv("DEEPSEEK_TIMEOUT", "30")
    config = config_from_env()
    assert isinstance(config, LLMConfig)
    assert config.api_key == "sk-x"
    assert config.model == "deepseek-v4-flash"
    assert config.timeout == 30.0


# --- provider ---


def _mock_client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_provider_complete_posts_chat_completions() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("authorization")
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": "hi"}}]})

    provider = OpenAICompatibleProvider(api_key="sk-test", client=_mock_client(handler))
    out = provider.complete([ChatMessage(role="user", content="hello")])
    assert out == "hi"
    assert captured["url"] == "https://api.deepseek.com/chat/completions"
    assert captured["auth"] == "Bearer sk-test"
    assert captured["body"]["model"] == "deepseek-v4-flash"
    assert captured["body"]["messages"] == [{"role": "user", "content": "hello"}]


def test_provider_raises_on_http_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "boom"})

    provider = OpenAICompatibleProvider(api_key="sk-test", client=_mock_client(handler))
    with pytest.raises(LLMError):
        provider.complete([ChatMessage(role="user", content="x")])


def test_provider_raises_on_empty_content() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": "  "}}]})

    provider = OpenAICompatibleProvider(api_key="sk-test", client=_mock_client(handler))
    with pytest.raises(LLMError):
        provider.complete([ChatMessage(role="user", content="x")])


def test_parse_json_response_tolerates_code_block() -> None:
    data = parse_json_response('```json\n{"kind": "finish"}\n```')
    assert data == {"kind": "finish"}
    assert parse_json_response('{"a": 1}') == {"a": 1}
    with pytest.raises(LLMError):
        parse_json_response("not json")


# --- bindings ---


class _FakeProvider:
    """返回固定文本的假 provider；记录收到的消息。"""

    def __init__(self, text: str) -> None:
        self.text = text
        self.calls: list[list[ChatMessage]] = []

    def complete(self, messages: list[ChatMessage], **kwargs) -> str:
        self.calls.append(messages)
        return self.text

    def complete_json(self, messages: list[ChatMessage], **kwargs) -> dict:
        self.calls.append(messages)
        return parse_json_response(self.text)


def _thought(agent: str = "Backend", content: str = "do the work") -> Thought:
    return Thought(agent_name=agent, task="write auth", content=content)


def test_reason_fn_builds_messages_and_returns_text() -> None:
    provider = _FakeProvider("思考：实现登录。")
    reason = make_reason_fn(provider)
    out = reason("role prompt", "task", "context")
    assert out == "思考：实现登录。"
    messages = provider.calls[0]
    assert messages[0].role == "system" and messages[0].content == "role prompt"
    assert messages[1].role == "user" and "task" in messages[1].content


def test_decide_fn_parses_tool_json() -> None:
    provider = _FakeProvider('{"kind": "file", "args": {"path": "a.py"}, "note": "write"}')
    decide = make_decide_fn(provider, tool_names=lambda name: ["file", "patch"])
    action = decide(_thought())
    assert isinstance(action, Action)
    assert action.kind == "file" and action.args == {"path": "a.py"}


def test_decide_fn_finish_json() -> None:
    provider = _FakeProvider('{"kind": "finish", "note": "done"}')
    decide = make_decide_fn(provider)
    action = decide(_thought())
    assert action.kind == "finish"


def test_decide_fn_falls_back_to_action_lines() -> None:
    provider = _FakeProvider("not json at all")
    decide = make_decide_fn(provider)
    thought = _thought(content="ACTION: terminal\nARG command=echo hi\n")
    action = decide(thought)
    assert action.kind == "terminal" and action.args == {"command": "echo hi"}


def test_review_fn_parses_passed() -> None:
    provider = _FakeProvider('{"passed": false, "comment": "缺少测试"}')
    review = make_review_fn(provider)
    assert review(TaskNode(title="x", task_type="backend"), "log") is False
    provider.text = '{"passed": true}'
    assert review(TaskNode(title="x", task_type="backend"), "log") is True


def test_review_fn_fails_open() -> None:
    provider = _FakeProvider("garbage")
    review = make_review_fn(provider)
    assert review(TaskNode(title="x", task_type="backend"), "log") is True


def test_route_fn_returns_agent() -> None:
    provider = _FakeProvider('{"agent": "Backend"}')
    route = make_route_fn(provider)
    assert route("写登录", ["Backend", "Frontend"]) == "Backend"


def test_decompose_fn_builds_tree() -> None:
    payload = {
        "tasks": [
            {"title": "Requirement", "task_type": "requirement"},
            {"title": "Architecture", "task_type": "architecture"},
            {"title": "Backend", "task_type": "backend"},
        ]
    }
    provider = _FakeProvider(json.dumps(payload))
    plan = make_decompose_fn(provider)("开发登录功能", tech_stack="FastAPI")
    titles = {node.title for node in plan.flatten()}
    assert {"Requirement", "Architecture", "Backend"} <= titles


def test_decompose_fn_falls_back_on_bad_json() -> None:
    provider = _FakeProvider("not json")
    plan = make_decompose_fn(provider)("开发登录功能", tech_stack="FastAPI")
    assert plan.root.children  # 规则拆解仍有节点


def test_provider_complete_records_finish_reason() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                'choices': [
                    {'message': {'content': 'x'}, 'finish_reason': 'length'}
                ]
            },
        )

    provider = OpenAICompatibleProvider(api_key='sk-test', client=_mock_client(handler))
    assert provider.last_finish_reason is None
    assert provider.complete([ChatMessage(role='user', content='x')]) == 'x'
    assert provider.last_finish_reason == 'length'


def test_provider_clears_finish_reason_on_http_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={'error': 'boom'})

    provider = OpenAICompatibleProvider(api_key='sk-test', client=_mock_client(handler))
    provider.last_finish_reason = 'length'
    with pytest.raises(LLMError):
        provider.complete([ChatMessage(role='user', content='x')])
    assert provider.last_finish_reason is None
