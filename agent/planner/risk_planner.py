"""风险规划（dev-notes/new.md「五、重构 Planner」risk_planner.py）。

    risk: payment security

规则版风险识别：任务描述关键词 → 风险条目（级别 + 缓解要求）。
LLM 版可注入 assess_fn 替换，接口不变。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

# 风险评估函数：任务描述 -> 风险列表
AssessFn = Callable[[str], list["Risk"]]


@dataclass(frozen=True)
class Risk:
    """一条已识别风险。"""

    name: str
    level: str  # high / medium / low
    mitigation: str  # 必须落实的缓解动作


# 关键词 → 风险（对应 knowledge/security_rule.md 的高危场景）
_RISK_RULES: tuple[tuple[tuple[str, ...], Risk], ...] = (
    (
        ("支付", "payment", "订单", "结算", "checkout"),
        Risk("payment security", "high", "支付回调验签、金额服务端复核、幂等处理"),
    ),
    (
        ("登录", "认证", "auth", "密码", "password", "token", "会话", "session"),
        Risk("authentication security", "high", "密码哈希存储、token 过期与刷新、防暴力破解"),
    ),
    (
        ("用户", "个人信息", "隐私", "user data", "profile"),
        Risk("personal data protection", "medium", "最小化收集、脱敏展示、访问权限校验"),
    ),
    (
        ("上传", "upload", "文件", "attachment"),
        Risk("file upload abuse", "medium", "类型白名单、大小限制、存储与执行隔离"),
    ),
    (
        ("搜索", "查询", "sql", "报表"),
        Risk("injection", "high", "参数化查询、输入校验、最小权限数据库账号"),
    ),
)


def assess_risks(task: str, assess_fn: AssessFn | None = None) -> list[Risk]:
    """识别任务风险；未命中任何规则时返回一条通用低风险提示。"""
    if assess_fn is not None:
        return assess_fn(task)
    lowered = task.lower()
    risks = [risk for keywords, risk in _RISK_RULES if any(k in lowered for k in keywords)]
    if not risks:
        risks.append(Risk("general quality", "low", "按 evaluation/ 清单执行常规验收"))
    return risks
