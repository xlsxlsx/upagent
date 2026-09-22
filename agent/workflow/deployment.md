# Deployment Workflow

覆盖 Task Lifecycle 的 deploy 阶段，由 Supervisor 与 DevOps Engineer 主导。

## 前置条件

进入本阶段前必须满足：

- testing 阶段测试结论「通过」
- security 阶段安全审计结论「通过」
- 性能优化项处理完毕或经确认遗留

## 流程

```text
DevOps：编写 deployment.md（环境 / 配置 / 启动 / 构建 / 回滚）
    ↓
实测部署文档（干净环境从零跑通一遍）
    ↓
Supervisor：汇总全部交付物
    ↓
执行 evaluation/final_acceptance.md 验收清单
    ↓
通过 → 向用户交付 / 失败 → 回退对应阶段
```

## 交付物清单

交付时必须齐备：

```text
project/
├── source code          全部源代码（含测试）
├── architecture.md      架构文档
├── api.md               API 文档
├── database.md          数据库设计文档
├── test_report.md       测试报告
├── security_report.md   安全审计报告
└── deployment.md        部署文档
```

## 交付纪律

- 部署到生产 / 发布到外部服务前，必须获得用户明确确认（`safety_policy.md`）。
- 交付说明中如实标注：已完成项、遗留项、已知限制。
- 交付后把最终状态归档进 `memory/project_memory.md`，重要经验沉淀到决策日志。
