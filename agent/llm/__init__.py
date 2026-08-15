"""LLM 接入层（new.md 的 LLM 注入点落地）。

- config.py     .env / 环境变量 → LLMConfig（密钥不入库）
- provider.py   OpenAI 兼容 /chat/completions 客户端（DeepSeek 等）
- bindings.py   把 provider 适配到 ReasonFn / DecideFn / ReviewFn / DecomposeFn
"""

from agent.llm.bindings import (
    make_decide_fn,
    make_decompose_fn,
    make_reason_fn,
    make_review_fn,
    make_route_fn,
)
from agent.llm.config import (
    DEFAULT_BASE_URL,
    DEFAULT_MODEL,
    LLMConfig,
    config_from_env,
    load_dotenv,
)
from agent.llm.provider import (
    ChatMessage,
    LLMError,
    LLMProvider,
    OpenAICompatibleProvider,
    parse_json_response,
)

__all__ = [
    "ChatMessage",
    "DEFAULT_BASE_URL",
    "DEFAULT_MODEL",
    "LLMConfig",
    "LLMError",
    "LLMProvider",
    "OpenAICompatibleProvider",
    "config_from_env",
    "load_dotenv",
    "make_decide_fn",
    "make_decompose_fn",
    "make_reason_fn",
    "make_review_fn",
    "make_route_fn",
    "parse_json_response",
]