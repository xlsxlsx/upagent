"""消息协议（dev-notes/new.md「8. Multi-Agent Communication」）。

示例——Architect 派任务给 Backend::

    {"from": "architect", "to": "backend", "type": "task",
     "content": "实现用户认证API"}

Backend 完成后回执::

    {"status": "done", "files": ["user.py"]}

MessageBus 提供进程内投递：每个 Agent 一个收件箱，全量留档可审计。
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass, field
from enum import StrEnum


class MessageType(StrEnum):
    TASK = "task"  # 派发任务
    RESULT = "result"  # 任务回执
    REVIEW = "review"  # 评审意见
    QUESTION = "question"  # 澄清提问


@dataclass(frozen=True)
class Message:
    """Agent 间的一条消息。"""

    sender: str  # "from" 是关键字，用 sender/receiver 命名
    receiver: str
    type: MessageType
    content: str

    def to_dict(self) -> dict[str, str]:
        data = asdict(self)
        data["type"] = self.type.value
        return data


@dataclass(frozen=True)
class TaskResult:
    """任务完成回执。"""

    status: str  # "done" / "failed"
    files: tuple[str, ...] = ()
    detail: str = ""

    @property
    def ok(self) -> bool:
        return self.status == "done"


@dataclass
class MessageBus:
    """进程内消息总线：投递 + 收件箱 + 全量审计日志。"""

    _inboxes: dict[str, list[Message]] = field(default_factory=lambda: defaultdict(list))
    _log: list[Message] = field(default_factory=list)

    def send(self, message: Message) -> None:
        self._inboxes[message.receiver].append(message)
        self._log.append(message)

    def receive(self, agent_name: str) -> list[Message]:
        """取走并清空收件箱。"""
        messages = self._inboxes.get(agent_name, [])
        self._inboxes[agent_name] = []
        return messages

    def pending(self, agent_name: str) -> int:
        return len(self._inboxes.get(agent_name, []))

    def history(self) -> tuple[Message, ...]:
        return tuple(self._log)
