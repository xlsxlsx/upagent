"""UpAgent desktop application package.

Zero-dependency local web UI (stdlib HTTP server + vanilla frontend) that drives
the `agent` pipeline: task chat, file tree, and file editor.
"""

from desktop.server import ChatBroker, ChatEvent, DesktopApp, create_server

__all__ = ["ChatBroker", "ChatEvent", "DesktopApp", "create_server"]
