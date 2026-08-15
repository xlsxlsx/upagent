# Memory Strategy（记忆策略）

三层记忆（memory/tiers.py）各存什么、何时写、何时读。

## 分层规则

| 层 | 存什么 | 生命周期 | 载体 |
| --- | --- | --- | --- |
| Short Term | 当前任务进展：「今天正在修改登录」 | 任务结束即弃 | 进程内 |
| Project Memory | 项目长期事实：「数据库用 PostgreSQL」「认证用 JWT」 | 跟项目走 | memory/project_facts.md |
| Knowledge Memory | 跨项目经验：「JWT 最佳实践」「React 性能优化」 | 跟 Agent 走 | memory/knowledge_memory.md |

## 写入时机

- Short Term：每个循环步骤的关键中间结论（当前假设、下一步）。
- Project Memory：技术选型确定时、约定形成时（一次一条，可复述的事实）。
- Knowledge Memory：任务复盘时提炼的可跨项目复用经验。
- 决策与失败仍分别走 decision_log.md / failure_memory.md（带编号模板）。

## 读取时机

- 每次推理前由 ContextBuilder 自动注入三层非空内容（各层 ≤ 2000 字符）。
- 新任务启动：优先读 Project Memory 对齐既有约定，禁止推翻已有选型而不记决策。

## 质量要求

- 一条记忆一件事，可独立复述；不存敏感信息（密钥、密码）。
- Project/Knowledge 层自动去重（同句不重复写入）。
