"""LLM 配置：.env / 环境变量 → LLMConfig。

密钥只从 DEEPSEEK_API_KEY 环境变量或 .env 文件读取，
绝不硬编码进代码；.env 已在 .gitignore 中排除。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-v4-flash"
DEFAULT_TIMEOUT = 120.0

_ENV_API_KEY = "DEEPSEEK_API_KEY"
_ENV_BASE_URL = "DEEPSEEK_BASE_URL"
_ENV_MODEL = "DEEPSEEK_MODEL"
_ENV_TIMEOUT = "DEEPSEEK_TIMEOUT"


@dataclass(frozen=True)
class LLMConfig:
    """连接一个 OpenAI 兼容 LLM 服务所需的全部参数。"""

    api_key: str
    base_url: str = DEFAULT_BASE_URL
    model: str = DEFAULT_MODEL
    timeout: float = DEFAULT_TIMEOUT


def load_dotenv(path: Path | str | None = None) -> Path | None:
    """把 .env 中的 KEY=VALUE 写入 os.environ（不覆盖已存在的变量）。

    返回实际读取的 .env 路径；文件不存在返回 None。
    """
    target = Path(path) if path is not None else Path.cwd() / ".env"
    if not target.is_file():
        return None
    for raw in target.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value
    return target


def config_from_env(env: dict[str, str] | None = None, *, require_key: bool = True) -> LLMConfig:
    """从环境变量构造 LLMConfig；require_key 时缺少密钥抛 ValueError。"""
    env = env if env is not None else os.environ
    api_key = env.get(_ENV_API_KEY, "").strip()
    if require_key and not api_key:
        raise ValueError(
            "DEEPSEEK_API_KEY is not set: copy .env.example to .env and fill in the key, "
            "or export DEEPSEEK_API_KEY"
        )
    return LLMConfig(
        api_key=api_key,
        base_url=env.get(_ENV_BASE_URL, "").strip() or DEFAULT_BASE_URL,
        model=env.get(_ENV_MODEL, "").strip() or DEFAULT_MODEL,
        timeout=float(env.get(_ENV_TIMEOUT, str(DEFAULT_TIMEOUT))),
    )