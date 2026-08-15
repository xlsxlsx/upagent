# Large Project Workflow（大型项目流程）

适用：从零构建多子系统项目（如「开发电商系统」）。主导角色：Supervisor 全程调度。

## 总流程

1. **规划**：Planner 产出 ExecutionPlan（任务树 + 依赖 + 风险），示例：
   - phases: requirement → architecture → database → backend → frontend → testing → security
   - dependencies: backend depends database；frontend depends backend
   - risk: payment security（high）
2. **调度**：Supervisor 按依赖序取叶子任务，经 Router 分派给对应 Agent。
3. **协作**：阶段完成发布事件（如 ARCHITECTURE_COMPLETED），下游 Agent 监听后自动开始。
4. **闭环**：每个子域完成即走 testing；失败进 bug_fix.md 流程。
5. **终审**：AuditAgent 产出 final_report.md（评分 + Issues + Recommendation）。

## 分解原则

- 叶子任务粒度：一个 Agent 一次循环（≤25 步）内可完成。
- 高风险子域（支付、认证）优先实现并优先审计。
- 每个子域完成后立即写 Project Memory（选型、接口约定），供后续子域对齐。

## 中断恢复

- ProjectState 持久化为 JSON；恢复时从任务树第一个未完成叶子继续。
- 恢复后必须先重跑全量测试确认基线，再继续新任务。

## 门禁

- 依赖未完成的子域不得开工（拓扑序强制）。
- final_report.md 结论 FAIL：按 Recommendation 回退对应阶段，不得交付。
