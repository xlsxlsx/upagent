"""Reflector（dev-notes/new.md「11. Reflection Agent」）。

Devin 类 Agent 的关键：代码失败 → 分析为什么失败 →
生成修复方案 → 重新执行。

    Developer: 我写完了
    Tester:    失败
    Developer: 修改
    Tester:    通过

analyze_fn 注入 LLM 版根因分析；默认规则版复用 Fixer：
先用 error_analyzer 提取结构化诊断（错误类型/涉及文件/失败用例），
再附失败摘要，生成一个聚焦的修复任务描述。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from agent.reflection.error_analyzer import analyze_output
from agent.reflection.fixer import FixPlan

# 分析函数：(原任务, 失败输出) -> 修复方案文本
AnalyzeFn = Callable[[str, str], str]

# 测试输出中值得保留的失败信号行
_FAILURE_MARKERS = ("FAILED", "ERROR", "Error", "assert", "Traceback", "exit ")
_MAX_LINES = 15


@dataclass
class Reflector:
    """失败分析器：把失败输出转成下一轮修复任务。"""

    analyze_fn: AnalyzeFn | None = None

    def plan_fix(self, task: str, failure_output: str) -> str:
        """生成修复任务描述，交回 Developer 循环执行。"""
        if self.analyze_fn is not None:
            return self.analyze_fn(task, failure_output)
        diagnosis = analyze_output(failure_output)
        return FixPlan(task=task, diagnosis=diagnosis).to_task(note=self._digest(failure_output))

    @staticmethod
    def _digest(output: str) -> str:
        lines = [
            line
            for line in output.splitlines()
            if any(marker in line for marker in _FAILURE_MARKERS)
        ]
        picked = lines[:_MAX_LINES] if lines else output.splitlines()[-_MAX_LINES:]
        return "\n".join(picked)