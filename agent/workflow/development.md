# Development Workflow

覆盖 Task Lifecycle 的 Phase 4（Development）与 Phase 7（Optimization）。

## 开发顺序

按依赖方向推进，禁止乱序：

```text
Database Engineer：Schema + 迁移脚本（database_design.md）
        ↓
Backend Engineer：数据访问层 → 业务逻辑 → API（api.md）
        ↓
Frontend Engineer：组件 → 页面 → 接口对接
        ↓
DevOps Engineer：本地运行脚本 / 构建配置
```

前后端可在 API 契约（api.md）冻结后并行开发。

## 单个子任务的标准循环

每个子任务都走同一循环，禁止批量堆完再统一测试：

```text
读架构与设计文档
    ↓
实现（小步、聚焦当前子任务）
    ↓
自测（跑单元测试 + 手动验证）
    ↓
提交 Code Reviewer 评审
    ↓
修复 Blocker / Major → 重审
    ↓
更新 project_memory.md → 下一个子任务
```

## 开发纪律

- 严格遵循 architecture.md；发现架构问题回 Architect 修订，不私自偏离。
- 遵循 `knowledge/coding_standard.md` 与 `knowledge/security_rule.md`。
- 每个子任务的代码 + 测试 + 文档同步完成，不欠债。
- Git 提交遵循 `tools/git.md` 规范，一次提交一个完整意图。
- 卡住两次以上：换思路并记录 `failure_memory.md`，不无脑重试。

## Phase 7 — Optimization

安全审计通过后、交付前的优化阶段：

1. 收集测试与审计阶段暴露的性能问题（慢查询、大包体、多余请求）
2. 逐项优化，每次优化后跑回归测试确认无功能回退
3. 无法在本期解决的项：与用户确认后记入遗留清单

优化阶段**只做优化，不加新功能**；新需求走增量 PRD。
