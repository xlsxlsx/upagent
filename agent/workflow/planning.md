# Planning Workflow

覆盖 Task Lifecycle 的 Phase 1（Requirement）、Phase 2（Planning）、Phase 3（Architecture）。

## Phase 1 — Requirement（Product Manager 主导）

```text
用户任务输入
    ↓
理解目标（用户目的 / 明确需求 / 隐含需求）
    ↓
歧义澄清（必要时向用户提问，见 Rule 3）
    ↓
编写 PRD（目标 / 画像 / 功能列表 / User Story / 优先级 / 验收标准）
    ↓
CEO Agent 确认 PRD
```

产出：PRD。退出条件：P0 功能全部有可验证的验收标准。

## Phase 2 — Planning（CEO Agent 主导）

```text
读取 PRD
    ↓
任务拆解（按 reasoning_policy.md Step 2，标注负责角色与依赖）
    ↓
风险分析（技术 / 安全 / 性能，见 Step 3）
    ↓
生成 Project Roadmap
    ↓
初始化 memory/project_memory.md
```

产出：Project Roadmap。退出条件：全部 P0 需求被子任务覆盖，依赖顺序明确。

## Phase 3 — Architecture（Architect 主导）

```text
读取 PRD + Roadmap
    ↓
技术选型（记录理由与备选方案到 decision_log.md）
    ↓
系统结构 / 数据库概览 / API 设计 / 部署方案 / 扩展方案
    ↓
输出 architecture.md
    ↓
CEO Agent + 工程师角色评审通过
```

产出：architecture.md。退出条件：六要素齐全且评审通过。

## 规划阶段红线

- 规划期间**禁止写业务代码**（验证性 spike 除外，且 spike 代码不直接进交付物）。
- 计划必须是决策完备的：进入开发阶段后，工程师不应再面临未决的重大选型。
- 任何用户新增需求都回到 Phase 1 走增量 PRD，不允许口头插队。
