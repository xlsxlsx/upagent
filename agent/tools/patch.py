"""Patch Tool（new.md「九、特别增加：Patch Tool」）。

不让 Agent 直接写文件：生成 -old/+new 差异 → 审核 → 应用。
这是 Cursor 的核心工作方式。

操作：
- preview  按 old/new 文本生成 unified diff（不落盘）
- apply    校验 old 与当前文件一致后整体替换（原子应用）
           review_fn 注入后作为门禁：返回 False 则拒绝应用

沿用 FileTool 的工作区约束，防路径穿越。
"""

from __future__ import annotations

import difflib
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from agent.tools.base import Tool, ToolResult

# 审核函数：unified diff 文本 -> 是否放行（默认放行；生产接人工/LLM 审核）
ReviewFn = Callable[[str], bool]


def make_diff(old: str, new: str, path: str) -> str:
    """生成 unified diff 文本（-old +new）。"""
    return "".join(
        difflib.unified_diff(
            old.splitlines(keepends=True),
            new.splitlines(keepends=True),
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
        )
    )


@dataclass
class PatchTool(Tool):
    """先出 diff、审核后应用的受控写入通道。"""

    workspace: Path = field(default_factory=Path.cwd)
    review_fn: ReviewFn | None = None
    name: str = "patch"

    def run(self, **kwargs: str) -> ToolResult:
        operation = kwargs.get("operation", "preview")
        raw_path = kwargs.get("path", "")
        if not raw_path:
            return ToolResult.failure("patch: missing 'path' argument")
        try:
            path = self._resolve(raw_path)
        except ValueError as exc:
            return ToolResult.failure(f"patch: {exc}")
        old = kwargs.get("old", "")
        new = kwargs.get("new", "")
        if operation == "preview":
            return ToolResult.success(make_diff(old, new, raw_path))
        if operation == "apply":
            return self._apply(path, raw_path, old, new)
        return ToolResult.failure(f"patch: unknown operation {operation!r}")

    def _apply(self, path: Path, raw_path: str, old: str, new: str) -> ToolResult:
        # 校验基线：old 必须等于当前文件内容（新文件 old 为空）
        try:
            current = path.read_text(encoding="utf-8") if path.is_file() else ""
        except (OSError, UnicodeDecodeError) as exc:
            return ToolResult.failure(f"patch: cannot read {raw_path}: {exc}")
        if current != old:
            return ToolResult.failure(
                f"patch: stale base for {raw_path}; re-read the file and regenerate the patch"
            )
        diff = make_diff(old, new, raw_path)
        if not diff:
            return ToolResult.failure("patch: empty diff, nothing to apply")
        if self.review_fn is not None and not self.review_fn(diff):
            return ToolResult.failure(f"patch: rejected by review for {raw_path}")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(new, encoding="utf-8")
        except OSError as exc:
            return ToolResult.failure(f"patch: write failed: {exc}")
        return ToolResult.success(f"applied patch to {raw_path}\n{diff}")

    def _resolve(self, raw: str) -> Path:
        root = self.workspace.resolve()
        path = (root / raw).resolve() if not Path(raw).is_absolute() else Path(raw).resolve()
        if not path.is_relative_to(root):
            raise ValueError(f"path escapes workspace: {raw}")
        return path
