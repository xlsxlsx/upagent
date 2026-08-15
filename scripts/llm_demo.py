"""真实 LLM 端到端演示：run_llm_project 跑一个小任务。

密钥只从 .env / 环境变量读取（.env 已被 gitignore）。
用法::

    python scripts/llm_demo.py --goal "写一个 hello.py 打印 hello world" --tech-stack Python
    python scripts/llm_demo.py --accept-always   # 跳过 AuditAgent 终审（演示用）
"""

from __future__ import annotations

import argparse
import tempfile
import time
from pathlib import Path

from agent.llm.config import config_from_env, load_dotenv
from agent.llm.provider import OpenAICompatibleProvider
from agent.runner import run_llm_project


class TimingProvider:
    """统计每次 LLM 调用的耗时（演示用，便于测量端到端耗时）。"""

    def __init__(self, inner) -> None:
        self.inner = inner
        self.calls = 0
        self.seconds = 0.0

    def complete(self, messages, **kwargs):
        started = time.perf_counter()
        try:
            return self.inner.complete(messages, **kwargs)
        finally:
            self.calls += 1
            self.seconds += time.perf_counter() - started

    def complete_json(self, messages, **kwargs):
        started = time.perf_counter()
        try:
            return self.inner.complete_json(messages, **kwargs)
        finally:
            self.calls += 1
            self.seconds += time.perf_counter() - started


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--goal", default="写一个 hello.py 打印 hello world，并运行验证")
    parser.add_argument("--tech-stack", default="Python")
    parser.add_argument("--out", type=Path, default=None, help="产物目录（默认系统临时目录）")
    parser.add_argument("--no-review", action="store_true", help="跳过 LLM 任务级审查")
    parser.add_argument("--accept-always", action="store_true", help="终审恒通过（仅演示流程用）")
    parser.add_argument("--max-steps", type=int, default=10, help="单任务步数上限（默认 10）")
    parser.add_argument("--two-phase", action="store_true",
                        help="回退到 reason+decide 两次调用（对比基线，默认一步式）")
    args = parser.parse_args()

    load_dotenv()
    config = config_from_env()
    provider = TimingProvider(OpenAICompatibleProvider(
        api_key=config.api_key,
        base_url=config.base_url,
        model=config.model,
        timeout=config.timeout,
    ))
    out = args.out or Path(tempfile.mkdtemp(prefix="llm-demo-"))
    out.mkdir(parents=True, exist_ok=True)
    step_mode = "two-phase" if args.two_phase else "one-shot"
    print(f"provider: {config.model} @ {config.base_url} (step={step_mode})")
    print(f"output dir: {out}")

    outcome = run_llm_project(
        args.goal,
        args.tech_stack,
        provider=provider,
        workspace=out,
        output_dir=out,
        use_llm_review=not args.no_review,
        acceptance_fn=(lambda plan: True) if args.accept_always else None,
        max_steps=args.max_steps,
        use_llm_step=not args.two_phase,
    )
    print("\n===== summary =====")
    print(outcome.summary())
    print(f"\nLLM calls: {provider.calls}, total LLM time: {provider.seconds:.1f}s")
    report = Path(outcome.report_path) if outcome.report_path else None
    if report and report.is_file():
        print("\n===== final report =====")
        print(report.read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
