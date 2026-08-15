# Task Lifecycle

整个 Agent 组织的生命周期。任何任务必须按以下八个阶段推进，**禁止跳过阶段**。
每个阶段有明确的主导角色、交付物与退出条件（Exit Criteria）；退出条件不满足不得进入下一阶段。

## 阶段总览

| 阶段 | 名称 | 主导角色 | 交付物 | 详细流程 |
| --- | --- | --- | --- | --- |
| Phase 1 | Requirement | Product Manager | PRD | `planning.md` |
| Phase 2 | Planning | CEO Agent | Project Roadmap | `planning.md` |
| Phase 3 | Architecture | Architect | architecture.md | `planning.md` |
| Phase 4 | Development | 各工程师 | 源代码 + api.md + database_design.md | `development.md` |
| Phase 5 | Testing | Tester | test_plan.md + test_report.md | `testing.md` |
| Phase 6 | Security Audit | Security Auditor | security_report.md | `audit.md` |
| Phase 7 | Optimization | 各工程师 | 优化后的代码与记录 | `development.md` |
| Phase 8 | Delivery | CEO Agent + DevOps | deployment.md + 验收结论 | `deployment.md` |

## 各阶段退出条件

- **Phase 1 Requirement**：PRD 完成，P0 功能全部有验收标准；关键歧义已向用户澄清。
- **Phase 2 Planning**：Roadmap 覆盖全部 P0 需求；子任务有负责角色与依赖顺序；风险分析完成。
- **Phase 3 Architecture**：架构文档六要素齐全（技术栈/结构/数据库/API/部署/扩展）；重要决策已入决策日志。
- **Phase 4 Development**：全部 P0 功能实现；单元测试通过；Code Reviewer 评审通过（无 Blocker/Major）。
- **Phase 5 Testing**：test_report 结论为「通过」；无 Blocker/Major 级失败用例。
- **Phase 6 Security Audit**：security_report 结论为「通过」；无未修复的 Critical/High 漏洞。
- **Phase 7 Optimization**：已识别的性能问题处理完毕或经用户确认遗留；回归测试通过。
- **Phase 8 Delivery**：`evaluation/final_acceptance.md` 全部清单通过；交付物齐全。

## 回退规则

- 任一阶段失败 → 回退到问题产生的阶段修复，再顺序重新通过后续门禁。
- **Supervisor 已自动执行**：任务重试耗尽按 `ROLLBACK_TARGETS` 映射回退
  （testing→implementation、security→architecture、deploy/各开发子域→implementation）；
  终审不通过默认回退到 implementation；回退预算 `max_rollbacks`（默认 2）耗尽即停。
- 例：安全审计发现架构级漏洞 → 回到 Phase 3 修订架构 → 重走 4/5/6。
- 每次回退在 `memory/project_memory.md` 记录原因，重复回退两次以上的问题记入 `failure_memory.md`。

## 轻量模式

对于小型任务（单文件脚本、简单修复），CEO Agent 可宣布启用轻量模式：
Phase 1–3 压缩为一段「需求 + 方案」说明，Phase 5–6 压缩为自测 + 安全自查。
但**阶段顺序与验收结论不可省略**，且必须在开场明确告知使用轻量模式。
