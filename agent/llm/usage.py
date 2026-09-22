"""Token 预算（dev-notes/software-development-agent-phase.md「收敛与成本」）。

Supervisor 收敛控制：把 token 消耗累计成单一计数器，重试预算与它挂钩：
- 用量 < 60%：完整重试预算
- 60%-80%：最多 1 次重试
- >= 80%：不再重试（当前尝试即最后一搏）
- 耗尽：停止调度新任务，写入 failure_memory

OpenAICompatibleProvider 在每次响应后调用 record() 累计 usage。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class TokenBudget:
    """累计 token 消耗与预算上限。"""

    limit: int
    prompt_tokens: int = 0
    completion_tokens: int = 0

    @property
    def used(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    @property
    def remaining(self) -> int:
        return max(0, self.limit - self.used)

    @property
    def depleted(self) -> bool:
        return self.used >= self.limit

    def ratio(self) -> float:
        """已用比例（0.0-1.0+）；limit<=0 视为已耗尽。"""
        if self.limit <= 0:
            return 1.0
        return min(1.0, self.used / self.limit)

    def record(self, prompt_tokens: int = 0, completion_tokens: int = 0) -> None:
        self.prompt_tokens += max(0, int(prompt_tokens))
        self.completion_tokens += max(0, int(completion_tokens))

    def summary(self) -> str:
        return (
            f"tokens used {self.used}/{self.limit} "
            f"(prompt {self.prompt_tokens}, completion {self.completion_tokens})"
        )

