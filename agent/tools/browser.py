"""Browser Tool（对应 agent/tools/browser.md 的能力与限制）。

只读抓取网页内容（查文档、核对 CVE 公告）。
限制：仅 http/https、只 GET、限制响应体大小；
不向外部提交项目代码或密钥（无 POST 能力即物理隔离）。
"""

from __future__ import annotations

import urllib.error
import urllib.request
from dataclasses import dataclass

from agent.tools.base import Tool, ToolResult

_MAX_BYTES = 512 * 1024  # 单页最多读 512 KB
_TIMEOUT = 30.0


@dataclass
class BrowserTool(Tool):
    """只读网页抓取。"""

    name: str = "browser"

    def run(self, **kwargs: str) -> ToolResult:
        url = kwargs.get("url", "").strip()
        if not url:
            return ToolResult.failure("browser: missing 'url' argument")
        if not url.startswith(("http://", "https://")):
            return ToolResult.failure(f"browser: only http/https allowed: {url}")
        try:
            request = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(request, timeout=_TIMEOUT) as response:
                body: bytes = response.read(_MAX_BYTES)
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            # ValueError：畸形 URL（如 http://[bad）由 Request/urlopen 抛出
            return ToolResult.failure(f"browser: fetch failed: {exc}")
        return ToolResult.success(body.decode("utf-8", errors="replace"))
