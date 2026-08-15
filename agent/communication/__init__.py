"""Multi-Agent Communication（new.md「8.」+「七、Event Bus 升级」）。

Agent 之间不能直接聊天：点对点走 Message，广播协作走 Event。
"""

from agent.communication.event import Event, EventBus, EventType
from agent.communication.message import Message, MessageBus, TaskResult

__all__ = ["Event", "EventBus", "EventType", "Message", "MessageBus", "TaskResult"]
