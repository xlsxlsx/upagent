# Feature Development Workflow（功能开发流程）

适用：在既有项目上新增一个功能。主导角色：Developer，Architect 参与设计。

## 阶段

| 步骤 | 动作 | 交付物 | 退出条件 |
| --- | --- | --- | --- |
| 1 澄清 | 明确输入/输出/边界，不明确处提问而非假设 | 需求要点 | 验收标准可测 |
| 2 设计 | 读 Repository Map，确定改动文件与接口 | 设计要点（写入 decision_log） | 影响面已评估 |
| 3 实现 | 按 coding_strategy.md 编码（Patch 优先） | 代码 | 自测通过 |
| 4 测试 | 新功能用例 + 全量回归 | 测试报告 | 0 failed |
| 5 评审 | 按 review_strategy.md 走 Patch/阶段评审 | 评审结论 | 通过 |

## 门禁

- 步骤 2 未评估 dependency_graph 影响面，不得进入实现。
- 新功能没有对应测试用例，不得进入评审。

## 回退规则

- 评审发现设计问题：回步骤 2，重新设计并记录决策变更。
- 回归被破坏：按 bug_fix.md 处理后再继续本流程。
