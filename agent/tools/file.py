"""File Tool（dev-notes/new.md「9. Tool System」中的 file.py）。

读写文件，工作区约束：所有路径必须落在 workspace 根目录内，
防路径穿越（security_rule.md）。写入是 Developer Agent 修改代码的
主要通道。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from agent.tools.base import Tool, ToolResult


@dataclass
class FileTool(Tool):
    """工作区内的文件读写。"""

    workspace: Path = field(default_factory=Path.cwd)
    name: str = "file"

    def run(self, **kwargs: str) -> ToolResult:
        operation = kwargs.get("operation", "read")
        # 容错：传入 content 且未显式指定操作时视为写入（LLM 常省略 operation）
        if operation == "read" and kwargs.get("content") is not None:
            operation = "write"
        raw_path = kwargs.get("path", "")
        if not raw_path:
            return ToolResult.failure("file: missing 'path' argument")
        try:
            path = self._resolve(raw_path)
        except ValueError as exc:
            return ToolResult.failure(f"file: {exc}")
        if operation == "read":
            return self._read(path)
        if operation == "write":
            return self._write(path, kwargs.get("content", ""))
        if operation == "exists":
            return ToolResult.success(str(path.exists()))
        return ToolResult.failure(f"file: unknown operation {operation!r}")

    def _resolve(self, raw: str) -> Path:
        root = self.workspace.resolve()
        path = (root / raw).resolve() if not Path(raw).is_absolute() else Path(raw).resolve()
        if not path.is_relative_to(root):
            raise ValueError(f"path escapes workspace: {raw}")
        return path

    def _read(self, path: Path) -> ToolResult:
        if not path.is_file():
            return ToolResult.failure(f"file: not found: {path}")
        return ToolResult.success(path.read_text(encoding="utf-8"))

    def _write(self, path: Path, content: str) -> ToolResult:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return ToolResult.success(f"wrote {len(content)} chars to {path}")
