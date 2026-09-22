# Task Lifecycle

整个 Agent 组织的生命周期。任何任务必须按以下阶段顺序推进，**禁止跳过阶段**。
每个阶段有明确的产出与退出条件（Exit Criteria）；退出条件不满足不得进入下一阶段。

阶段与运行时任务类型一一对应（`agent/planner/task_tree.py` 的 `task_type`）：
`requirement → architecture → frontend/backend/database（implementation 子域）→
testing → security → deploy`。旧设计中的 Planning / Optimization / Delivery 已合并：
Planning 并入 requirement + architecture，Optimization 并入 implementation，
Delivery 即 deploy。

## 阶段总览

| 阶段 | task_type | 主导角色 | 交付物 | 详细流程 |
| --- | --- | --- | --- | --- |
| 1 Requirement | requirement | Product Manager | PRD | `planning.md` |
| 2 Architecture | architecture | Architect | architecture.md | `planning.md` |
| 3 Implementation | frontend / backend / database | 各工程师 | 源代码 + api.md + database_design.md | `development.md` |
| 4 Testing | testing | Tester | test_plan.md + test_report.md | `testing.md` |
| 5 Security Audit | security | Security Auditor | security_report.md | `audit.md` |
| 6 Deploy | deploy | DevOps | deployment.md + 验收结论 | `deployment.md` |

## 各阶段退出条件

- **Requirement**：PRD 完成，P0 功能全部有验收标准；关键歧义已向用户澄清。
- **Architecture**：架构文档六要素齐全（技术栈/结构/数据库/API/部署/扩展）；重要决策已入决策日志。
- **Implementation**：全部 P0 功能实现；单元测试通过；Code Reviewer 评审通过（无 Blocker/Major）。
- **Testing**：test_report 结论为「通过」；无 Blocker/Major 级失败用例。
- **Security Audit**：security_report 结论为「通过」；无未修复的 Critical/High 漏洞。
- **Deploy**：`evaluation/final_acceptance.md` 全部清单通过；交付物齐全。

## 回退规则

- 任一阶段失败 → 回退到问题产生的阶段修复，再顺序重新通过后续门禁。
- **Supervisor 已自动执行**：任务重试耗尽按 `ROLLBACK_TARGETS` 映射回退
  （testing→implementation、security→architecture、deploy/各开发子域→implementation）；
  终审不通过默认回退到 implementation；回退预算 `max_rollbacks`（默认 2）耗尽即停。
- 例：安全审计发现架构级漏洞 → 回到 architecture 修订架构 → 重走实现/测试/审计。
- 每次回退写入 `memory/decision_log.md`；重复回退两次以上的问题记入 `failure_memory.md`。

## 轻量模式

对于小型任务（单文件脚本、简单修复），LLM 拆解会把任务压到 2–4 个粗粒度任务
（见 `agent/llm/bindings.py` 的 `_DECOMPOSE_SYSTEM`）：requirement/architecture
压缩为一段「需求 + 方案」说明，testing/security 压缩为自测 + 安全自查。
但**任务顺序与验收结论不可省略**。