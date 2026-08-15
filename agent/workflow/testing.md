# Testing Workflow

覆盖 Task Lifecycle 的 Phase 5（Testing），由 Tester（QA Engineer）主导。

## 流程

```text
读取 PRD 验收标准 + api.md + database_design.md
    ↓
编写 test_plan.md（用例先行）
    ↓
准备测试环境与测试数据
    ↓
执行三层测试
    ↓
输出 test_report.md
    ↓
结论：通过 → Phase 6 / 不通过 → Bug 回给工程师
```

## 三层测试策略

| 层级 | 覆盖对象 | 依据 |
| --- | --- | --- |
| Unit | 函数/类：正常、边界、错误路径 | 各模块实现 |
| Integration | API + 数据库、模块协作 | api.md 契约 |
| E2E | 用户完整流程 | PRD User Story |

- 优先保证 P0 功能的三层覆盖，P1/P2 至少覆盖单元层。
- 全量测试必须能通过一条命令重复执行。

## Bug 处理循环

```text
发现 Bug → 记录（复现步骤 / 实际 vs 预期 / 级别）
    ↓
回给对应工程师修复（Tester 不改业务代码）
    ↓
修复后回归：重跑失败用例 + 相关用例
    ↓
更新 test_report.md
```

- Blocker / Major 未清零，测试结论不得写「通过」。
- 修复引发的新问题按新 Bug 重新走循环。

## 红线

- 禁止为通过而放宽断言、跳过用例、篡改预期。
- 测试数据不使用真实用户数据。
- 报告必须如实反映结果，失败就是失败。
