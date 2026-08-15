# Review Strategy（评审策略）

Patch 审核（PatchTool.review_fn）与阶段评审的统一标准。

## Patch 审核清单

按顺序检查，任一不过即拒绝（返回 False）：

1. diff 范围是否只覆盖本任务声明的关注点（无夹带改动）。
2. 是否删除/放宽了测试断言或跳过用例。
3. 是否引入危险模式（拼接 SQL、硬编码密钥、eval/exec、shell 拼接）。
4. 是否破坏公共接口（函数签名、导出符号）而未同步调用方。
5. 新增代码是否有类型标注、命名与周围一致。

## 阶段评审（Reviewer 角色）

- development → testing：代码完成 + coding_strategy.md 全部落实。
- testing → security_audit：0 failed 且新增功能有对应用例。
- security_audit → optimization：无 Critical/High 发现。
- 评审不通过：按 workflow/task_lifecycle.md 回退，理由写入 decision_log.md。

## 评审产出

- 通过：一句话结论 + 覆盖的检查项。
- 拒绝：具体到 diff 行/文件的问题清单，可直接转为修复任务。
