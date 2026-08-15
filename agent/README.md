# Agent Configuration — AI Software Engineering Organization

本目录把 Agent 从「聊天助手」升级为「完整软件研发团队」：
用户输入「最终目标 + 可能的技术栈」，Agent 通过
**计划 → 执行 → 审查** 完成代码开发与交付。

结构翻新自 `new.md` 的设计草案：Markdown 是配置与知识层，
`core/ planner/ router/ communication/ tools/ agents/ reflection/ audit/`
下的 Python 模块是可执行的运行时引擎。

## 加载顺序

任务开始时按以下顺序读取：

1. `config/system/` — 我是谁、行为准则、思考方式、安全底线（**始终生效**）
2. `workflow/task_lifecycle.md` — 确定当前阶段与门禁
3. `roles/<当前角色>.md` — 当前阶段主导角色的职责与产出要求
4. `knowledge/` — 执行时对照的规范与模式
5. `memory/` — 恢复项目状态、检查已知教训

## 目录索引

```text
agent/
├── config/system/                核心系统配置（最高优先级）
│   ├── agent_identity.md         身份：AI 软件工程组织
│   ├── agent_rules.md            七条最高行为准则
│   ├── reasoning_policy.md       四步思考流程（理解→拆解→风险→执行）
│   └── safety_policy.md          安全底线（破坏性操作 / 敏感信息）
│
├── config/                       执行策略层（怎么干活）
│   ├── execution_policy.md       执行总策略：预算 / 完成判定 / 失败处理
│   ├── tool_usage_policy.md      工具选择表与使用顺序
│   ├── coding_strategy.md        编码方法论（编码前/中/后）
│   ├── debug_strategy.md         调试闭环 + 重试纪律
│   ├── memory_strategy.md        三层记忆的读写时机
│   └── review_strategy.md        Patch 审核与阶段评审标准
│
├── roles/                        十个角色配置（职责 / 输入 / 输出 / 准则）
│   ├── ceo_agent.md              总调度
│   ├── product_manager.md        PRD
│   ├── architect.md              架构设计
│   ├── backend_engineer.md       服务端
│   ├── frontend_engineer.md      前端
│   ├── database_engineer.md      数据层
│   ├── devops_engineer.md        构建部署
│   ├── tester.md                 三层测试
│   ├── security_auditor.md       安全审计
│   └── code_reviewer.md          代码评审
│
├── workflow/                     流程与阶段门禁
│   ├── task_lifecycle.md         八阶段生命周期（总纲，禁止跳过）
│   ├── planning.md               Phase 1–3：需求 / 计划 / 架构
│   ├── development.md            Phase 4 & 7：开发 / 优化
│   ├── testing.md                Phase 5：测试
│   ├── audit.md                  Phase 6：安全审计
│   ├── deployment.md             Phase 8：交付部署
│   ├── bug_fix.md                缺陷修复流程（复现→定位→修复→验证）
│   ├── feature_development.md    功能开发流程
│   ├── refactoring.md            重构流程（小步改 + 步步验证）
│   └── large_project.md          大型项目流程（Supervisor 全程调度）
│
├── knowledge/                    规范知识库
│   ├── coding_standard.md        编码规范
│   ├── architecture_pattern.md   架构模式与选型速查
│   ├── security_rule.md          开发期安全规则
│   ├── engineering_principles.md 十条工程价值观
│   ├── software_architecture.md  架构决策准则
│   ├── design_pattern.md         设计模式适用与反模式
│   ├── database_best_practice.md 数据库建模/访问/演进
│   ├── api_design.md             REST 设计与安全底线
│   └── frontend_best_practice.md 组件/状态/性能/安全
│
├── memory/                       项目记忆（执行中持续更新）
│   ├── project_memory.md         当前状态（单一事实来源）
│   ├── decision_log.md           决策日志（只追加）
│   └── failure_memory.md         失败教训（同错不二犯）
│
├── tools/                        工具能力与限制
│   ├── terminal.md               shell / build / test
│   ├── git.md                    提交规范与红线
│   ├── browser.md                页面验证与资料检索
│   ├── database.md               迁移与查询
│   └── code_execution.md         运行验证
│
└── evaluation/                   验收体系
    ├── quality_check.md          代码质量清单（评审用）
    ├── security_check.md         安全验收清单（审计用）
    └── final_acceptance.md       最终验收（五项全过才交付）
```

## 运行时引擎（Python 模块）

```text
agent/
├── core/                         Agent 核心
│   ├── agent.py                  Agent 类：角色 md 即 Prompt，reason_fn 注入 LLM
│   ├── loop.py                   Agent Loop：思考→决策→执行→记录（max_steps 防失控）
│   ├── state.py                  ProjectState：八阶段生命周期 + JSON 持久化
│   └── context.py                ContextBuilder：需求+状态+记忆+知识 五要素拼装
│
├── planner/                      规划层
│   ├── planner.py                create_plan(task)→TaskTree；decide(thought)→Action
│   ├── task_tree.py              任务树：深度优先取下一个未完成叶子
│   ├── decomposition.py          规则版任务拆解（可注入 LLM 版替换）
│   ├── dependency_planner.py     子域依赖表 + 拓扑排序执行顺序
│   ├── risk_planner.py           规则版风险识别（assess_fn 可注入 LLM 版）
│   ├── execution_planner.py      ExecutionPlan：拆解+依赖+风险+技术栈 一步生成
│   └── stack_map.py              技术栈 → 领域检测（React→frontend 等）
│
├── codebase/                     Code Intelligence Layer（编码前先看项目）
│   ├── analyzer.py               AST 分析：类/函数/导入摘要
│   ├── symbol_index.py           符号 → 定义位置
│   ├── dependency_graph.py       import 关系 + 修改影响面
│   ├── repository_map.py         project_map.md 生成（注入 Context）
│   └── search.py                 关键词代码检索（embed_fn 可注入向量版）
│
├── supervisor/supervisor.py      总调度：分派→执行→审查门禁→终审验收→回退重做→记失败
├── runner.py                     run_project：用户输入 → 计划 → 执行 → 审查 一站式入口
├── router/router.py              task_type → Agent 调度（llm_route_fn 兜底）
├── communication/                message.py 点对点消息；event.py EventBus 发布订阅
├── memory/                       store.py 决策/失败日志；tiers.py 三层记忆
│                                 （短期 / 项目长期 / 跨项目知识）
│
├── tools/                        工具层（md 是能力描述，py 是实现）
│   ├── base.py                   Tool 基类 + ToolResult
│   ├── terminal.py               危险命令黑名单
│   ├── git.py                    子命令白名单 + Conventional Commits 强制
│   ├── file.py                   工作区路径穿越防护
│   ├── browser.py                只读 GET 页面验证
│   ├── patch.py                  Patch Tool：diff → 审核（review_fn）→ 应用
│   ├── database.py               只读查询 + 迁移脚本（凭证走环境变量）
│   ├── docker.py                 docker 白名单（只读/构建；run/exec 需人工）
│   └── test_runner.py            test_runner（结果摘要）+ package_manager（白名单）
│
├── agents/developer.py           Developer：实现→测试→反思修复循环（≤3 轮）
├── agents/team.py                build_team：角色→工具集装配，注册进 Router
├── reflection/                   error_analyzer.py 结构化诊断；fixer.py 诊断→修复指引；
│                                 reflector.py 修复任务生成；retry_policy.py 同错两次换方法、三次上报
└── audit/                        audit_agent.py 终审扫描；scoring.py 三维评分
                                  → final_report.md（Score / Findings / Recommendation）
```

核心解耦：LLM 全部通过注入函数接入（`reason_fn` / `decide_fn` /
`analyze_fn` / `llm_route_fn` / `assess_fn` / `review_fn` / `embed_fn`），
运行时引擎纯标准库实现，可用桩函数离线测试（见
`tests/test_runtime_engine.py`、`tests/test_runtime_upgrades.py` 与
`tests/test_project_pipeline.py`，运行 `uv run pytest tests/test_project_pipeline.py`）。

### 用户输入：最终目标 + 技术栈（推荐入口）

用户只提供两样东西，其余交给 `run_project`：

```python
from pathlib import Path
from agent.core.agent import Agent
from agent.planner.planner import Planner
from agent.router.router import AgentRouter
from agent.runner import run_project

router = AgentRouter()
router.register(Agent(name="Backend", role="backend_engineer.md",
                      tools=[FileTool(), PatchTool(), TerminalTool()],
                      reason_fn=llm_reason))

outcome = run_project(
    goal="开发一个类似 Steam 的游戏平台",
    tech_stack="Python FastAPI + PostgreSQL + React",
    router=router,
    decide_fn=Planner().decide,
    output_dir=Path("project"),   # 计划 + 终审报告落在这里
)
print(outcome.result.finished, outcome.accepted)   # 是否跑完、是否验收通过
print(outcome.report_path)
```

闭环说明：

1. **计划**：`UserRequest(goal, tech_stack)` 校验后生成 `ExecutionPlan`
   （技术栈 → 领域：React→frontend、FastAPI→backend、PostgreSQL→database；
   依赖拓扑排序；风险清单），落盘 `execution_plan.md`。
2. **执行**：Supervisor 逐任务调度；编码前通过 `repo_map_provider`
   注入 `Repository Map`（项目结构/依赖/影响面）。
3. **审查**：每个任务完成过 `review_fn` 门禁（不通过计入重试）；
   全部完成后走 `acceptance_fn` 终审（默认 `AuditAgent` 生成
   `final_report.md`，Critical/High 或需求未 100% 完成 → 不交付）。
4. **回退**：任务重试耗尽或终审不通过 → 按 `workflow/task_lifecycle.md`
   回退规则自动回退到问题产生的阶段重做（测试失败→开发、审计失败→架构）；
   回退预算 `max_rollbacks`（默认 2）耗尽 → 记入 `failure_memory.md` 并停止。

### 最小串联示例

```python
from agent.core.agent import Agent
from agent.core.state import ProjectState
from agent.memory.store import MemoryStore
from agent.planner.planner import Planner
from agent.router.router import AgentRouter
from agent.supervisor.supervisor import Supervisor
from agent.tools.file import FileTool
from agent.tools.patch import PatchTool
from agent.tools.terminal import TerminalTool

backend = Agent(name="Backend", role="backend_engineer.md",
                tools=[FileTool(), PatchTool(), TerminalTool()], reason_fn=llm_reason)
router = AgentRouter()
router.register(backend)

# Supervisor 一步到位：ExecutionPlan（拆解+依赖+风险）→ 调度 → 重试 → 记失败
supervisor = Supervisor(router=router, decide_fn=Planner().decide,
                        state=ProjectState(), memory=MemoryStore())
result = supervisor.run("开发一个类似 Steam 的游戏平台")
print(result.finished, result.completed)
```

## 端到端执行效果

用户输入：目标 = `做一个在线游戏网站`，技术栈 = `Node.js + Vue + MySQL`

```text
CEO Agent 读取任务、澄清歧义、建立计划
    ↓
Product Manager 生成 PRD
    ↓
Architect 设计架构（architecture.md）
    ↓
Database Engineer 设计数据（database_design.md）
    ↓
Backend Engineer 写服务（api.md）
    ↓
Frontend Engineer 写页面
    ↓
Tester 测试（test_plan.md / test_report.md）
    ↓
Security Auditor 审计（security_report.md）
    ↓
Code Reviewer 全量代码检查
    ↓
DevOps + CEO 验收交付（deployment.md）
```

最终输出：

```text
project/
├── source code
├── architecture.md
├── api.md
├── database.md
├── test_report.md
├── security_report.md
└── deployment.md
```
