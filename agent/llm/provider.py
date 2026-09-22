
"""LLM Provider：OpenAI 兼容 /chat/completions（DeepSeek 等）。

- LLMProvider Protocol：complete / complete_json，便于测试注入 fake。
- OpenAICompatibleProvider：httpx 调用 {base_url}/chat/completions。
- parse_json_response：容忍模型返回 ```json 代码块。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Protocol

import httpx

from agent.llm.usage import TokenBudget


class LLMError(RuntimeError):
    """LLM 调用失败（网络、HTTP、解析）。"""


@dataclass(frozen=True)
class ChatMessage:
    """一条对话消息：system / user / assistant。"""

    role: str
    content: str

    def to_dict(self) -> dict[str, str]:
        return {"role": self.role, "content": self.content}


class LLMProvider(Protocol):
    """LLM 抽象：完整 / JSON 两种补齐入口。"""

    def complete(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float = 0.2,
        max_tokens: int = 2048,
    ) -> str: ...

    def complete_json(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float = 0.0,
        max_tokens: int = 2048,
    ) -> dict: ...


_JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def parse_json_response(text: str) -> dict:
    """解析模型 JSON 输出；容忍 ```json 包裹，失败抛 LLMError。"""
    stripped = text.strip()
    block = _JSON_BLOCK_RE.search(stripped)
    candidate = block.group(1).strip() if block else stripped
    try:
        data = json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise LLMError(f"LLM JSON parse failed: {exc}; text={stripped[:200]!r}") from exc
    if not isinstance(data, dict):
        raise LLMError(f"LLM JSON is not an object: {data!r}")
    return data


class OpenAICompatibleProvider:
    """通过 httpx 调用任意 OpenAI 兼容 chat completions 端点。"""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://api.deepseek.com",
        model: str = "deepseek-v4-flash",
        timeout: float = 120.0,
        client: httpx.Client | None = None,
        budget: TokenBudget | None = None,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self._client = client
        self.budget = budget  # token 预算累计器（Supervisor 收敛控制）
        self.last_finish_reason: str | None = None
        self.last_usage: dict[str, int] = {}

    def _http(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(timeout=self.timeout)
        return self._client

    def complete(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float = 0.2,
        max_tokens: int = 4096,
    ) -> str:
        payload = {
            "model": self.model,
            "messages": [m.to_dict() for m in messages],
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
        try:
            response = self._http().post(
                f"{self.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPError as exc:
            self.last_finish_reason = None
            raise LLMError(f"LLM request failed: {exc}") from exc
        try:
            message = data["choices"][0]["message"]
        except (KeyError, IndexError, TypeError) as exc:
            self.last_finish_reason = None
            raise LLMError(f"unexpected LLM response: {data!r}") from exc
        self.last_finish_reason = data["choices"][0].get("finish_reason")
        # 推理型模型可能把正文放在 reasoning_content（DeepSeek v4 等）
        content = message.get("content") or message.get("reasoning_content") or ""
        if not isinstance(content, str) or not content.strip():
            raise LLMError(
                f"LLM returned empty content (finish_reason={self.last_finish_reason or '?'})"
            )
        self._record_usage(data, messages, content)
        return content

    def complete_json(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ) -> dict:
        text = self.complete(messages, temperature=temperature, max_tokens=max_tokens)
        return parse_json_response(text)

    def _record_usage(
        self, data: dict, messages: list[ChatMessage], content: str
    ) -> None:
        """累计本次调用的 token 消耗；API 未返回 usage 时用 4 字符/token 粗估。"""
        usage = data.get("usage")
        if isinstance(usage, dict):
            prompt = int(usage.get("prompt_tokens") or 0)
            completion = int(usage.get("completion_tokens") or 0)
        else:
            prompt = sum(len(message.content) for message in messages) // 4
            completion = len(content) // 4
        self.last_usage = {"prompt_tokens": prompt, "completion_tokens": completion}
        if self.budget is not None:
            self.budget.record(prompt, completion)

    @property
    def tokens_used(self) -> int:
        """累计消耗 token 数（未配置 budget 时为 0）。"""
        return self.budget.used if self.budget is not None else 0
