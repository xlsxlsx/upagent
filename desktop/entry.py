"""UpAgent desktop executable entry point.

Starts the local server and opens the browser UI. Run:

    python -m desktop.entry --workspace D:/my/project

Flags:
    --host 127.0.0.1   bind address
    --port 8765        port
    --no-browser       do not open the browser
"""

from __future__ import annotations

import argparse
import contextlib
import logging
import os
import sys
import threading
import webbrowser
from pathlib import Path

from desktop.runner import ChatRunner
from desktop.server import DesktopApp, create_server


def _exe_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def _frontend_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "desktop" / "frontend"
    return Path(__file__).resolve().parent / "frontend"


def _load_env() -> Path | None:
    from agent.llm.config import load_dotenv

    candidates = [_exe_dir() / ".env", Path.cwd() / ".env"]
    for path in candidates:
        if path.is_file():
            load_dotenv(path)
            return path
    return None


def _provider_factory():
    from agent.llm.config import config_from_env
    from agent.llm.provider import OpenAICompatibleProvider

    config = config_from_env()
    return OpenAICompatibleProvider(
        api_key=config.api_key,
        base_url=config.base_url,
        model=config.model,
        timeout=config.timeout,
    )


def _status_provider() -> dict[str, object]:
    from agent.llm.config import config_from_env

    try:
        config = config_from_env(require_key=False)
        return {
            "model": config.model,
            "base_url": config.base_url,
            "key_configured": bool(config.api_key),
        }
    except Exception:  # noqa: BLE001 - status must never crash the UI
        return {"model": "unknown", "base_url": "", "key_configured": False}


def _setup_logging() -> None:
    log_path = _exe_dir() / "upagent.log"
    logging.basicConfig(
        filename=str(log_path),
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--workspace", default=None, help="workspace directory")
    parser.add_argument("--no-browser", action="store_true", help="do not open the browser")
    args = parser.parse_args(argv)

    _setup_logging()
    env_path = _load_env()
    workspace = (
        Path(args.workspace).resolve()
        if args.workspace
        else Path(os.path.expanduser("~")).resolve()
    )
    workspace.mkdir(parents=True, exist_ok=True)

    app = DesktopApp(
        workspace,
        provider_factory=_provider_factory,
        status_provider=_status_provider,
    )
    runner = ChatRunner(app.broker, get_workspace=lambda: app.workspace)
    server = create_server(
        app,
        host=args.host,
        port=args.port,
        frontend_dir=_frontend_dir(),
        start_chat=lambda run_id, goal, tech_stack: runner.start(run_id, goal, tech_stack, app),
    )
    url = f"http://{args.host}:{args.port}"
    logging.info("UpAgent listening on %s (workspace=%s, env=%s)", url, workspace, env_path)

    if not args.no_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    with contextlib.suppress(KeyboardInterrupt):
        server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
