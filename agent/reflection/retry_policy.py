"""重试策略（dev-notes/new.md「十、Reflection 升级」retry_policy.py）。

Rule 6：同一错误连续出现两次必须换方法，不允许原地死磕。

RetryPolicy 记录每类错误的出现次数并给出下一步动作：
    retry          继续修（首次出现）
    change_method  换方法（同类错误第二次出现）
    escalate       上报/停止（超过总预算或同类错误第三次）
"""

from __future__ import annotations

import hashlib
from collections import Counter
from dataclasses import dataclass, field


def _signature(error_type: str, message: str) -> str:
    """错误签名：类型 + 消息前缀，同类错误归并。"""
    raw = f"{error_type}:{message[:80]}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


@dataclass
class RetryPolicy:
    """基于错误签名的重试决策。"""

    max_total: int = 6  # 总修复预算
    _seen: Counter[str] = field(default_factory=Counter)
    _total: int = 0

    def next_action(self, error_type: str, message: str = "") -> str:
        """记录一次失败并返回下一步动作。"""
        self._total += 1
        if self._total > self.max_total:
            return "escalate"
        sig = _signature(error_type, message)
        self._seen[sig] += 1
        occurrences = self._seen[sig]
        if occurrences >= 3:
            return "escalate"
        if occurrences == 2:
            return "change_method"
        return "retry"

    def reset(self) -> None:
        self._seen.clear()
        self._total = 0
