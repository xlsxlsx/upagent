"""Supervisor（dev-notes/new.md「六、Supervisor Agent」）。

task_manager / delegation 的职责（分配、判断完成、重试）
规模尚小，已并入 Supervisor 单类实现，接口稳定后再拆分。
"""

from agent.supervisor.supervisor import Supervisor, SupervisorResult

__all__ = ["Supervisor", "SupervisorResult"]
