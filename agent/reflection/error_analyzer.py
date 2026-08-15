"""错误分析器（new.md「十、Reflection 升级」error_analyzer.py）。

闭环第一步：读取错误 → 定位文件 → 分析原因。

从测试/运行输出中提取结构化诊断：错误类型、涉及文件、
关键消息，供 fixer/Reflector 生成聚焦的修复任务。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Traceback 中的文件行：File "path", line N
_TB_FILE = re.compile(r'File "([^"]+)", line (\d+)')
# pytest 失败行：FAILED tests/test_x.py::test_y - AssertionError: ...
_PYTEST_FAILED = re.compile(r"FAILED\s+(\S+?)::(\S+)")
# 最后一行错误：ValueError: bad input
_ERROR_LINE = re.compile(r"^(\w+(?:Error|Exception|Warning)):\s*(.*)$")


@dataclass(frozen=True)
class Diagnosis:
    """一次失败的结构化诊断。"""

    error_type: str  # 如 AssertionError / ValueError / unknown
    files: tuple[str, ...]  # 涉及的文件（按出现顺序去重）
    failed_tests: tuple[str, ...]  # 失败用例（pytest 节点 id）
    message: str  # 关键错误消息

    def summary(self) -> str:
        parts = [f"error: {self.error_type}"]
        if self.failed_tests:
            parts.append("failed tests: " + ", ".join(self.failed_tests))
        if self.files:
            parts.append("files: " + ", ".join(self.files))
        if self.message:
            parts.append(f"message: {self.message}")
        return "\n".join(parts)


def analyze_output(output: str) -> Diagnosis:
    """从原始输出提取诊断信息；提取不到时给 unknown 兜底。"""
    files: list[str] = []
    for match in _TB_FILE.finditer(output):
        path = match.group(1)
        # 过滤解释器/三方库内部帧，聚焦项目文件
        if "site-packages" not in path and path not in files:
            files.append(path)
    failed_tests: list[str] = []
    for match in _PYTEST_FAILED.finditer(output):
        node = f"{match.group(1)}::{match.group(2)}"
        if node not in failed_tests:
            failed_tests.append(node)
        if match.group(1) not in files:
            files.append(match.group(1))
    error_type = "unknown"
    message = ""
    for line in reversed(output.splitlines()):
        found = _ERROR_LINE.match(line.strip())
        if found:
            error_type = found.group(1)
            message = found.group(2)[:200]
            break
    return Diagnosis(
        error_type=error_type,
        files=tuple(files[:10]),
        failed_tests=tuple(failed_tests[:10]),
        message=message,
    )
