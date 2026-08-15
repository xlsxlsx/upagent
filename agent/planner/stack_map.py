"""技术栈 → 领域检测（软件开发 Agent 的计划输入）。

用户说「Python FastAPI + PostgreSQL + React」，Planner 应该知道
这涉及 backend / database / frontend 三个领域，而不是靠猜。

与 decomposition 的任务关键词检测互补：
任务文本命中关键词 → 领域；技术栈命中关键词 → 领域。两者取并集。
"""

from __future__ import annotations

# 技术栈关键词 → 领域（顺序即优先级；子串匹配，保持全小写）
STACK_DOMAINS: dict[str, tuple[str, ...]] = {
    "frontend": (
        "react",
        "vue",
        "angular",
        "next.js",
        "nextjs",
        "svelte",
        "tailwind",
        "html",
        "css",
        "前端",
        "小程序",
    ),
    "backend": (
        "fastapi",
        "django",
        "flask",
        "express",
        "nestjs",
        "spring",
        "fastify",
        "laravel",
        "gin",
        "go",
        "rust",
        "api",
        "后端",
    ),
    "database": (
        "postgres",
        "postgresql",
        "mysql",
        "sqlite",
        "mongodb",
        "redis",
        "sql server",
        "数据库",
    ),
    "testing": (
        "pytest",
        "jest",
        "vitest",
        "cypress",
        "playwright",
        "mocha",
        "unittest",
    ),
    "devops": (
        "docker",
        "kubernetes",
        "k8s",
        "ci/cd",
        "github actions",
        "terraform",
        "nginx",
    ),
}


def detect_domains(tech_stack: str) -> list[str]:
    """技术栈文本 → 涉及领域列表（按 STACK_DOMAINS 顺序去重）。

    空技术栈返回空列表；未知技术栈不产生领域（任务关键词兜底）。
    """
    lowered = tech_stack.lower()
    seen: list[str] = []
    for domain, keywords in STACK_DOMAINS.items():
        if any(keyword in lowered for keyword in keywords) and domain not in seen:
            seen.append(domain)
    return seen