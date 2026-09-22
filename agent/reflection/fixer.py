"""Fixer（dev-notes/new.md「十、Reflection 升级」fixer.py）。

闭环第二步：诊断 → 修复指引。把 error_analyzer 的结构化诊断
（Diagnosis）转成「修哪里、修什么、怎么验证」的补丁任务描述，
交给 Developer 执行。Reflector 复用本模块（plan_fix = 摘要 + Fixer 指引）。

analyze_fn 可注入 LLM 版根因分析；默认规则版不依赖任何模型。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from agent.reflection.error_analyzer import Diagnosis, analyze_output

# 分析函数：(原任务, 失败输出) -> 修复方案文本
AnalyzeFn = Callable[[str, str], str]


@dataclass(frozen=True)
class FixPlan:
    """一份聚焦的修复指引（Fixer 的结构化输出）。"""

    task: str  # 原始任务
    diagnosis: Diagnosis

    @property
    def files(self) -> tuple[str, ...]:
        """需要修改的文件（诊断中定位到的项目文件）。"""
        return self.diagnosis.files

    def to_task(self, note: str = "") -> str:
        """渲染为 Developer 可直接执行的修复任务描述。"""
        lines = [
            f"修复以下测试失败（原任务：{self.task}）。",
            "只修根因，不放宽断言、不跳过用例。",
            "诊断:",
            self.diagnosis.summary(),
        ]
        if note.strip():
            lines += ["失败摘要:", note.strip()]
        return "\n".join(lines)


class Fixer:
    """把失败输出变成修复任务描述；analyze_fn 可注入 LLM 版根因分析。"""

    def __init__(self, analyze_fn: AnalyzeFn | None = None) -> None:
        self.analyze_fn = analyze_fn

    def plan_fix(self, task: str, failure_output: str, note: str = "") -> str:
        """一次调用生成修复任务：诊断 → FixPlan → 任务文本。"""
        if self.analyze_fn is not None:
            return self.analyze_fn(task, failure_output)
        diagnosis = analyze_output(failure_output)
        return FixPlan(task=task, diagnosis=diagnosis).to_task(note=note)

    def build_plan(self, task: str, failure_output: str) -> FixPlan:
        """结构化版：返回 FixPlan（文件/错误类型/失败用例），供工具链消费。"""
        return FixPlan(task=task, diagnosis=analyze_output(failure_output))