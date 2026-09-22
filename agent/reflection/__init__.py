"""Reflection（dev-notes/new.md「11. Reflection Agent」+「十、Reflection 升级」）。

闭环：Test 失败 → error_analyzer 诊断 → Reflector 出修复任务 →
Developer 重跑 → RetryPolicy 决定 继续修/换方法/上报。
"""

from agent.reflection.error_analyzer import Diagnosis, analyze_output
from agent.reflection.fixer import Fixer, FixPlan
from agent.reflection.reflector import Reflector
from agent.reflection.retry_policy import RetryPolicy

__all__ = ["Diagnosis", "FixPlan", "Fixer", "Reflector", "RetryPolicy", "analyze_output"]
