"""Token 预算与 usage 统计测试（零依赖、离线）。"""

from __future__ import annotations

import httpx
from agent.llm.provider import ChatMessage, OpenAICompatibleProvider
from agent.llm.usage import TokenBudget


def test_token_budget_arithmetic() -> None:
    budget = TokenBudget(limit=100, prompt_tokens=40, completion_tokens=30)
    assert budget.used == 70
    assert budget.remaining == 30
    assert not budget.depleted
    budget.record(prompt_tokens=20, completion_tokens=20)
    assert budget.used == 110
    assert budget.depleted
    assert budget.remaining == 0
    assert budget.summary() == "tokens used 110/100 (prompt 60, completion 50)"


def test_token_budget_zero_limit_is_depleted() -> None:
    budget = TokenBudget(limit=0)
    assert budget.depleted
    assert budget.ratio() == 1.0


def _mock_client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_provider_records_usage_into_budget() -> None:
    budget = TokenBudget(limit=10_000)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "hi"}}],
                "usage": {"prompt_tokens": 120, "completion_tokens": 30},
            },
        )

    provider = OpenAICompatibleProvider(
        api_key="sk-test", budget=budget, client=_mock_client(handler)
    )
    assert provider.complete([ChatMessage(role="user", content="hello")]) == "hi"
    assert provider.tokens_used == 150
    assert provider.last_usage == {"prompt_tokens": 120, "completion_tokens": 30}
    assert budget.used == 150


def test_provider_estimates_usage_when_api_omits_it() -> None:
    budget = TokenBudget(limit=10_000)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"choices": [{"message": {"content": "hello"}}]}
        )

    provider = OpenAICompatibleProvider(
        api_key="sk-test", budget=budget, client=_mock_client(handler)
    )
    provider.complete([ChatMessage(role="user", content="abcdefgh")])
    assert provider.tokens_used > 0
    assert provider.last_usage["completion_tokens"] == 1  # 5 字符 // 4

