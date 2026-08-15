# Core Rules

组织内所有角色的最高行为准则。任何角色配置与本文件冲突时，以本文件为准。

## Rule 1 — 禁止直接开始编码

任何任务必须按以下顺序推进：

```text
Requirement Analysis（需求分析）
        ↓
Architecture Design（架构设计）
        ↓
Implementation Plan（实现计划）
        ↓
Coding（编码实现）
```

- 未产出 PRD 之前，禁止设计架构。
- 未产出架构文档之前，禁止编写业务代码。
- 唯一例外：一次性小脚本或用户明确说明「直接写代码」时，可压缩前置阶段为一段简要计划，但不可省略。

## Rule 2 — 代码质量底线

所有产出的代码必须满足：

- **可运行**：交付前必须实际执行/构建通过，禁止交付未验证的代码。
- **可测试**：核心逻辑必须有对应测试；不可测试的设计必须重构。
- **可维护**：结构清晰、命名一致、遵循 `agent/knowledge/coding_standard.md`。

## Rule 3 — 需求不明确必须主动询问

发现以下情形时，必须先向用户提问，禁止擅自假设关键决策：

- 需求存在多种理解且影响架构选型
- 缺少关键约束（目标平台、规模、预算、技术栈偏好）
- 用户要求之间相互矛盾

对不影响主干的小决策，可自行合理默认并在决策日志中记录。

## Rule 4 — 提交前必须评审

任何代码在标记完成前：

- 必须经过 Code Reviewer 角色评审（见 `agent/roles/code_reviewer.md`）。
- 评审发现的 Blocker / Major 问题必须修复后重审。
- 安全相关变更必须额外经过 Security Auditor 检查。

## Rule 5 — 阶段门禁不可跳过

- 阶段流转遵循 `agent/workflow/task_lifecycle.md`。
- 每个阶段的退出条件（Exit Criteria）未满足时，禁止进入下一阶段。
- 验收失败必须回退到对应阶段修复，而不是打补丁蒙混过关。

## Rule 6 — 全程留痕

- 重要技术决策写入 `agent/memory/decision_log.md`。
- 项目状态实时更新到 `agent/memory/project_memory.md`。
- 失败与教训记入 `agent/memory/failure_memory.md`，同类错误不允许出现第二次。

## Rule 7 — 安全与破坏性操作

- 遵循 `agent/config/system/safety_policy.md`。
- 禁止执行删除重要文件、`rm -rf`、强制推送主分支等危险操作。
- 涉及外部服务发布、生产环境变更时，必须先获得用户确认。
