"""Database Tool（dev-notes/new.md「九、Tool 系统大改」中的 database）。

对齐 agent/tools/database.md 的能力与限制：

- 查询验证只读：SELECT / SHOW / DESCRIBE / EXPLAIN / PRAGMA；
  写语句与 SELECT INTO OUTFILE / FOR UPDATE 直接拒绝。
- Schema 变更只走迁移脚本（operation="migrate"），脚本必须位于工作区内。
- 凭证走环境变量（MYSQL_PWD / PGPASSWORD），不落到命令行与代码。

Agent 不传任意 shell 命令，只传结构化参数，工具自行拼装 CLI。
"""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from agent.tools.base import Tool, ToolResult

_READ_ONLY_PREFIXES = ("SELECT", "SHOW", "DESCRIBE", "DESC", "EXPLAIN", "PRAGMA")
# 即使以只读前缀开头，这些子句也会写文件/加写锁 → 一律拒绝
_FORBIDDEN_IN_QUERY = ("into outfile", "into dumpfile", "for update")
_IDENTIFIER = re.compile(r"^[A-Za-z0-9_]+$")
_HOST = re.compile(r"^[A-Za-z0-9._-]+$")
_PORT = re.compile(r"^[0-9]+$")
_ENGINES = ("mysql", "postgres")
_TIMEOUT = 60.0


def is_read_only_query(query: str) -> bool:
    """只读判定：前缀白名单 + 拒绝文件导出/写锁子句。"""
    head = query.strip().upper()
    if not head or not head.startswith(_READ_ONLY_PREFIXES):
        return False
    lowered = query.lower()
    return not any(token in lowered for token in _FORBIDDEN_IN_QUERY)


def validate_identifier(value: str, label: str) -> None:
    """标识符（库名/用户名）只允许字母数字下划线，防注入。"""
    if not _IDENTIFIER.fullmatch(value):
        raise ValueError(f"{label} must match [A-Za-z0-9_]+: {value!r}")


def build_command(
    engine: str,
    operation: str,
    *,
    database: str,
    query: str = "",
    host: str = "localhost",
    port: str = "",
    user: str = "",
) -> list[str]:
    """拼装 CLI 参数（不含凭证；凭证由调用方经环境变量注入）。"""
    if engine not in _ENGINES:
        raise ValueError(f"unsupported engine {engine!r}; choose from {_ENGINES}")
    if operation not in ("query", "migrate"):
        raise ValueError(f"unknown operation {operation!r}; choose query|migrate")
    validate_identifier(database, "database")
    if user:
        validate_identifier(user, "user")
    if port and not _PORT.fullmatch(port):
        raise ValueError(f"invalid port: {port!r}")
    if not _HOST.fullmatch(host):
        raise ValueError(f"invalid host: {host!r}")
    if operation == "query" and not is_read_only_query(query):
            raise ValueError(
                "only read-only queries allowed "
                f"(prefix: {', '.join(_READ_ONLY_PREFIXES)})"
            )
    if engine == "mysql":
        cmd = ["mysql", "--batch"]
        if host:
            cmd += ["--host", host]
        if port:
            cmd += ["--port", port]
        if user:
            cmd += ["--user", user]
        cmd += ["--database", database]
        if operation == "query":
            cmd += ["--execute", query]
        return cmd
    # postgres → psql
    cmd = ["psql", "--no-align", "--tuples-only"]
    if host:
        cmd += ["--host", host]
    if port:
        cmd += ["--port", port]
    if user:
        cmd += ["--username", user]
    cmd += ["--dbname", database]
    if operation == "query":
        cmd += ["--command", query]
    return cmd


@dataclass
class DatabaseTool(Tool):
    """结构化、只读优先的数据库访问。"""

    workspace: Path = field(default_factory=Path.cwd)
    name: str = "database"
    timeout: float = _TIMEOUT

    def run(self, **kwargs: str) -> ToolResult:
        engine = kwargs.get("engine", "mysql")
        operation = kwargs.get("operation", "query")
        database = kwargs.get("database", "")
        query = kwargs.get("query", "")
        migration = kwargs.get("migration", "")
        host = kwargs.get("host", "localhost")
        port = kwargs.get("port", "")
        user = kwargs.get("user", "")
        password = kwargs.get("password", "")
        try:
            cmd = build_command(
                engine,
                operation,
                database=database,
                query=query,
                host=host,
                port=port,
                user=user,
            )
        except ValueError as exc:
            return ToolResult.failure(f"database: {exc}")
        env = dict(os.environ)
        if password:
            env["MYSQL_PWD" if engine == "mysql" else "PGPASSWORD"] = password
        script = ""
        if operation == "migrate":
            script = self._read_migration(migration)
            if script is None:
                return ToolResult.failure(
                    f"database: migration script not found in workspace: {migration}"
                )
        return self._run(cmd, script, env)

    # --- 内部 ---

    def _read_migration(self, raw: str) -> str | None:
        """迁移脚本必须位于工作区内；返回脚本内容，越界/缺失返回 None。"""
        if not raw:
            return None
        root = self.workspace.resolve()
        path = (root / raw).resolve() if not Path(raw).is_absolute() else Path(raw).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            return None
        try:
            return path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return None

    def _run(self, cmd: list[str], stdin: str, env: dict[str, str]) -> ToolResult:
        try:
            proc = subprocess.run(
                cmd, input=stdin, text=True, capture_output=True, env=env, timeout=self.timeout
            )
        except (subprocess.TimeoutExpired, OSError) as exc:
            return ToolResult.failure(f"database: {exc}")
        output = (proc.stdout + proc.stderr).strip()
        if proc.returncode != 0:
            return ToolResult.failure(f"exit {proc.returncode}\n{output}")
        return ToolResult.success(output)