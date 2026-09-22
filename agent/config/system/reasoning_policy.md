# Reasoning Process

控制组织内所有角色的思考方式。对于任何任务，必须依次执行以下四个步骤。

## Step 1 — 理解目标

在动手之前，先输出对任务的理解：

- **用户目的**：用户最终想达成什么（业务目标，而不只是字面要求）
- **用户需求**：明确说出来的功能与约束
- **隐含需求**：没有说但显然需要的内容（如：登录系统隐含密码加密、会话管理）

若理解存在歧义且影响重大 → 触发 `agent_rules.md` Rule 3，先向用户提问。

## Step 2 — 任务拆解

把大任务拆成可独立推进、可独立验证的子任务，并标注负责角色。

示例——「开发商城」拆解为：

| 子任务 | 负责角色 |
| --- | --- |
| Frontend（页面、购物车交互） | Frontend Engineer |
| Backend（订单、商品 API） | Backend Engineer |
| Database（商品/订单/用户表） | Database Engineer |
| Payment（支付集成） | Backend Engineer + Security Auditor |
| Authentication（注册登录、会话） | Backend Engineer + Security Auditor |

拆解要求：

- 每个子任务有明确的**完成标准**（Definition of Done）
- 明确子任务之间的**依赖顺序**（如：数据库 Schema 先于后端实现）
- 拆解结果写入执行计划（execution_plan.md），由 Supervisor 统一调度

## Step 3 — 风险分析

对每个子任务检查三类风险，并给出应对策略：

- **技术风险**：技术选型不成熟、依赖库限制、集成复杂度
- **安全风险**：注入、越权、敏感数据泄露（对照 `agent/knowledge/security_rule.md`）
- **性能风险**：数据量增长、并发瓶颈、慢查询

高风险项必须：

1. 在决策日志中记录风险与预案
2. 优先做小规模验证（spike），再全面实现

## Step 4 — 执行

- 按拆解顺序执行，一次专注一个子任务。
- 每完成一个子任务：自测 → 更新 `project_memory.md` → 进入下一个。
- 执行中发现计划有误：停下来修正计划，而不是硬着头皮继续。
- 连续两次同一方法失败：换思路，并记录到 `failure_memory.md`。
