"""任务拆解（new.md「5. Planner」中的 decomposition）。

把大任务拆成任务树。默认拆解遵循八阶段生命周期骨架，
Implementation 按关键词识别出 frontend / backend / database 等子域；
技术栈（tech_stack）作为第二信号源：任务文本命中关键词 → 领域，
技术栈命中关键词 → 领域，两者取并集。更智能的拆解可传入
LLM 版 decompose_fn 替换本模块的规则实现。
"""

from __future__ import annotations

from agent.planner.stack_map import detect_domains
from agent.planner.task_tree import TaskNode, TaskTree

# 子域关键词 → 任务类型（规则版启发式）
_DOMAIN_KEYWORDS: dict[str, tuple[str, ...]] = {
    "frontend": ("页面", "前端", "界面", "ui", "web", "网站", "商城", "平台"),
    "backend": ("api", "后端", "服务", "登录", "认证", "订单", "支付", "平台", "商城", "网站"),
    "database": ("数据", "存储", "用户", "订单", "商品", "平台", "商城", "网站"),
}

# 生命周期骨架：Implementation 之外的固定阶段
_SKELETON: tuple[tuple[str, str], ...] = (
    ("Requirement", "requirement"),
    ("Architecture", "architecture"),
)
_TAIL: tuple[tuple[str, str], ...] = (
    ("Testing", "testing"),
    ("Security Audit", "security"),
    ("Deploy", "deploy"),
)


def decompose(task: str, tech_stack: str | None = None) -> TaskTree:
    """规则版拆解：生命周期骨架 + 按关键词/技术栈识别实现子域。

    例：「开发一个类似 Steam 游戏平台」→
        ROOT ├─ Requirement ├─ Architecture
             ├─ Implementation ├─ Frontend ├─ Backend ├─ Database
             ├─ Testing ├─ Security Audit └─ Deploy
    """
    root = TaskNode(title=task, task_type="root")
    for title, task_type in _SKELETON:
        root.add(TaskNode(title=title, task_type=task_type))

    implementation = root.add(TaskNode(title="Implementation", task_type="implementation"))
    for domain in _match_domains(task, tech_stack):
        implementation.add(TaskNode(title=domain.capitalize(), task_type=domain))
    if not implementation.children:
        # 识别不出子域时至少有一个通用开发节点
        implementation.add(TaskNode(title="Develop", task_type="backend"))

    for title, task_type in _TAIL:
        root.add(TaskNode(title=title, task_type=task_type))
    return TaskTree(root=root)


def _match_domains(task: str, tech_stack: str | None) -> list[str]:
    """任务关键词 + 技术栈 → 去重后的领域列表（关键词序优先）。"""
    lowered = task.lower()
    domains = [
        domain
        for domain, keywords in _DOMAIN_KEYWORDS.items()
        if any(keyword in lowered for keyword in keywords)
    ]
    for domain in detect_domains(tech_stack or ""):
        if domain not in domains:
            domains.append(domain)
    return domains