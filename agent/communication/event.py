"""Event Bus（new.md「七、Agent Communication 升级」）。

从「点对点消息」升级为「事件驱动」：

    Architect 发布:  EVENT: ARCHITECTURE_COMPLETED, payload: architecture.md
    Developer 订阅:  ARCHITECTURE_COMPLETED → 自动开始

EventBus 提供 subscribe/publish 与全量事件日志；
与 MessageBus 并存：点对点走 Message，广播协作走 Event。
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum


class EventType(StrEnum):
    """阶段完成事件（与八阶段生命周期对应）+ 通用事件。"""

    REQUIREMENT_COMPLETED = "requirement_completed"
    PLANNING_COMPLETED = "planning_completed"
    ARCHITECTURE_COMPLETED = "architecture_completed"
    DEVELOPMENT_COMPLETED = "development_completed"
    TESTING_COMPLETED = "testing_completed"
    TESTING_FAILED = "testing_failed"
    SECURITY_AUDIT_COMPLETED = "security_audit_completed"
    AUDIT_FAILED = "audit_failed"
    DELIVERY_COMPLETED = "delivery_completed"
    TASK_ASSIGNED = "task_assigned"
    # 计划-执行-审查 闭环事件
    PLAN_CREATED = "plan_created"
    REVIEW_PASSED = "review_passed"
    REVIEW_FAILED = "review_failed"
    DELIVERY_ACCEPTED = "delivery_accepted"
    DELIVERY_REJECTED = "delivery_rejected"
    PHASE_ROLLED_BACK = "phase_rolled_back"  # 阶段失败 → 回退到问题阶段


@dataclass(frozen=True)
class Event:
    """一个已发生的事件。payload 通常是交付物路径或摘要。"""

    type: EventType
    source: str  # 发布者（Agent 名）
    payload: str = ""


# 订阅回调：收到事件后执行
Handler = Callable[[Event], None]


@dataclass
class EventBus:
    """进程内事件总线：订阅 + 发布 + 全量留档。"""

    _handlers: dict[EventType, list[Handler]] = field(
        default_factory=lambda: defaultdict(list)
    )
    _log: list[Event] = field(default_factory=list)

    def subscribe(self, event_type: EventType, handler: Handler) -> None:
        self._handlers[event_type].append(handler)

    def publish(self, event: Event) -> int:
        """发布事件，同步调用全部订阅者；返回通知到的订阅者数量。"""
        self._log.append(event)
        handlers = list(self._handlers.get(event.type, ()))
        for handler in handlers:
            handler(event)
        return len(handlers)

    def history(self) -> tuple[Event, ...]:
        return tuple(self._log)