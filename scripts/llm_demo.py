"""真实 LLM 端到端演示：run_llm_project 跑一个小任务。

密钥只从 .env / 环境变量读取（.env 已被 gitignore）。
用法::

    python scripts/llm_demo.py --goal "写一个 hello.py 打印 hello world" --tech-stack Python
    python scripts/llm_demo.py --accept-always   # 跳过 AuditAgent 终审（演示用）
"""

from __future__ import annotations

import argparse
import tempfile
from pathlib import Path

from agent.llm.config import config_from_env, load_dotenv
from agent.llm.provider import OpenAICompatibleProvider
from agent.runner import run_llm_project


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--goal", default="写一个 hello.py 打印 hello world，并运行验证")
    parser.add_argument("--tech-stack", default="Python")
    parser.add_argument("--out", type=Path, default=None, help="产物目录（默认系统临时目录）")
    parser.add_argument("--no-review", action="store_true", help="跳过 LLM 任务级审查")
    parser.add_argument("--accept-always", action="store_true", help="终审恒通过（仅演示流程用）")
    args = parser.parse_args()

    load_dotenv()
    config = config_from_env()
    provider = OpenAICompatibleProvider(
        api_key=config.api_key,
        base_url=config.base_url,
        model=config.model,
        timeout=config.timeout,
    )
    out = args.out or Path(tempfile.mkdtemp(prefix="llm-demo-"))
    out.mkdir(parents=True, exist_ok=True)
    print(f"provider: {config.model} @ {config.base_url}")
    print(f"output dir: {out}")

    outcome = run_llm_project(
        args.goal,
        args.tech_stack,
        provider=provider,
        workspace=out,
        output_dir=out,
        use_llm_review=not args.no_review,
        acceptance_fn=(lambda plan: True) if args.accept_always else None,
    )
    print("\n===== summary =====")
    print(outcome.summary())
    report = Path(outcome.report_path) if outcome.report_path else None
    if report and report.is_file():
        print("\n===== final report =====")
        print(report.read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()