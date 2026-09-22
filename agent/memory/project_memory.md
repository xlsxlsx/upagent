# Project Memory

记录当前项目状态。由 Supervisor 与各角色 Agent 维护：每完成一个子任务、
每次阶段流转、每次回退都必须更新本文件。这是长任务的「单一事实来源」——
上下文丢失后从这里恢复。

## 使用规则

- 只保留**当前**状态，历史决策进 `decision_log.md`，失败教训进 `failure_memory.md`。
- 每次更新填写「Last Updated」。
- Next Action 必须具体到「哪个角色做什么」，禁止写模糊的「继续开发」。

---

## Current State

```text
Project:            <项目名称与一句话描述>

Current Phase:      <任务类型，见 workflow/task_lifecycle.md：requirement / architecture / implementation / testing / security / deploy>

Active Role:        <当前主导角色>

Last Updated:       <日期时间>
```

## Completed

<!-- 已完成的阶段与子任务，附交付物路径 -->

- [ ] Requirement — PRD：
- [ ] Architecture — architecture.md：
- [ ] Implementation — 源代码 + api.md + database_design.md：
- [ ] Testing — test_report.md：
- [ ] Security Audit — security_report.md：
- [ ] Deploy — deployment.md：

## Current Issues

<!-- 当前阻塞与未解决问题：描述 / 级别 / 负责角色 -->

| 问题 | 级别 | 负责角色 | 状态 |
| --- | --- | --- | --- |
|  |  |  |  |

## Architecture Decision

<!-- 生效中的关键架构决策摘要，详情见 decision_log.md -->

-

## Next Action

<!-- 下一步：哪个角色、做什么、完成标准 -->

-