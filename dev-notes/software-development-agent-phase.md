# 软件开发 Agent 流水线阶段记录（计划 → 执行 → 审查）

> 对应 `agent/` 包（AI Software Engineering Organization）的一轮增量升级。
> 上游设计草案见 `dev-notes/new.md`，运行时说明见 `agent/README.md`。

## 为什么存在

`agent/` 包已经有完整的多角色运行时：Supervisor 调度、Planner 拆解、
Router 分派、Tools 执行、Reflection 修复、Audit 终审。但用户的入口
只有一句话任务（`Supervisor.run(task)`），有三个明显缺口：

1. Planner 不感知技术栈：用户说「FastAPI + PostgreSQL + React」，
   计划仍然是靠任务文本关键词猜领域。
2. 执行没有审查门禁：任务做完直接标记完成，没有「审查不通过→重试」。
3. 终审（`AuditAgent`）没有被接入流水线，最后一步要靠人手动调。

本阶段把入口改成用户只输入两样东西——**最终目标 + 可能的技术栈**，
然后 Agent 自动完成「**计划 → 执行 → 审查**」的闭环。

## 新增了什么

### 用户输入模型
- `agent/core/request.py` — `UserRequest(goal, tech_stack, constraints, output_dir)`
  只做结构化与校验（goal 必填、长度上限），`render()` 输出给 LLM 的请求摘要。

### 技术栈感知的计划
- `agent/planner/stack_map.py` — `detect_domains(tech_stack)`：技术栈关键词 →
  领域（React/Vue→frontend、FastAPI/Django→backend、PostgreSQL/MySQL→database、
  pytest/Jest→testing、Docker/K8s→devops）。
- `agent/planner/decomposition.py` — `decompose(task, tech_stack=None)`：
  任务关键词与技术栈取并集决定实现子域。
- `agent/planner/execution_planner.py` — `ExecutionPlan` 增加 `tech_stack` 字段，
  `render()` 输出 `## Tech Stack`；`create_execution_plan(task, tech_stack=None)`。
- `agent/planner/planner.py` — `Planner.create_plan(task, tech_stack=None)`；
  注入的旧版单参数 `decompose_fn` 自动兼容（inspect 判断）。

### 执行时注入项目结构
- `agent/core/loop.py` — `AgentLoop.repo_map_provider`：每次思考前把
  `Repository Map`（codebase 层生成）注入上下文，解决「LLM 不知道项目结构」。

### 审查门禁与终审验收
- `agent/communication/event.py` — 新增事件：`PLAN_CREATED`、`REVIEW_PASSED`、
  `REVIEW_FAILED`、`DELIVERY_ACCEPTED`、`DELIVERY_REJECTED`。
- `agent/supervisor/supervisor.py` —
  - `run_request(UserRequest)`：计划（落盘 `execution_plan.md`）→ 执行 → 终审。
  - `review_fn`：每个任务完成后的审查门禁；不通过计入该任务的重试预算。
  - `acceptance_fn`：任务树全部完成后的终审验收；不通过 → `accepted=False`。
  - `last_plan`：最近一次执行计划，供上层取回。

### 一站式入口
- `agent/runner.py` — `run_project(goal, tech_stack, router, decide_fn, ...)`：
  用户输入 → 计划 → 执行 → 审查 → 交付结论；默认终审用 `AuditAgent`
  生成 `final_report.md`（`default_acceptance`）。

### 测试
- `tests/test_project_pipeline.py` — 16 个用例：输入校验、技术栈检测、
  计划落档、Repository Map 注入、审查门禁重试、终审拒绝、端到端流水线。

## 与 Pi 设计的对应

```text
AgentHarness = supervisor + planner + router   （可复用大脑，纯注入函数，无 UI 依赖）
AgentSession = tools + codebase + memory        （编码环境）
TUI / CLI    = 未来前端（本阶段未引入）
```

- 「计划 → 执行 → 审查」就是 Pi agent loop 的三拍：
  think（Planner）→ act（Tools）→ reflect（review_fn / AuditAgent）。
- Supervisor 发布事件、其他组件订阅，对应 Pi 的事件流（EventBus 已存在）。
- LLM 全部通过注入函数接入（`reason_fn` / `decide_fn` / `review_fn` /
  `acceptance_fn` / `repo_map_provider`），核心仍是纯标准库、可离线测试。

## 如何测试 / 使用

```bash
uv run pytest tests/test_project_pipeline.py
```

端到端最小示例（详细版见 `agent/README.md`）：

```python
outcome = run_project(
    goal="开发一个类似 Steam 的游戏平台",
    tech_stack="Python FastAPI + PostgreSQL + React",
    router=router,              # 注册好各角色 Agent 的 Router
    decide_fn=Planner().decide,
    output_dir=Path("project"),
)
print(outcome.result.finished, outcome.accepted)   # 是否跑完、是否验收通过
print(outcome.report_path)
```

## 后续方向（对齐 roadmap issue #1）

- LLM 版 `decompose_fn` / `assess_fn` / `review_fn`：注入点已留好，规则版只是默认值。
- 向量代码检索：`CodeSearch.embed_fn` 注入即可替换关键词版。
- 审查不通过自动回退到问题阶段（`workflow/task_lifecycle.md` 的回退规则，
  目前由调用方决定是否回退）。
## 增量：回退规则（自动执行 task_lifecycle 回退）

### 为什么

`workflow/task_lifecycle.md` 早就写好了回退规则，但之前 Supervisor
失败只会「记 failure 然后停」，不会真正回退重做。本增量把规则变成代码。

### 改了什么

- `agent/planner/task_tree.py` — `TaskTree.rollback_to(origin_type)`：
  把「问题产生阶段」及其后的节点重置为 PENDING，更早阶段保持完成。
- `agent/communication/event.py` — 新增 `PHASE_ROLLED_BACK` 事件。
- `agent/supervisor/supervisor.py` —
  - `ROLLBACK_TARGETS` 映射：testing→implementation、security→architecture、
    deploy/各开发子域→implementation；requirement/architecture 无更早阶段可回退。
  - 任务重试耗尽 → 自动回退 → 重做后续阶段（`execute` 内循环）。
  - 终审不通过 → 回退到 `acceptance_rollback_target`（默认 implementation）重做。
  - 回退预算 `max_rollbacks`（默认 2）耗尽 → 记 `failure_memory.md` 并停止。
  - 每次回退写入决策日志（`append_decision`），发布 `PHASE_ROLLED_BACK`。
- `tests/test_rollback_rules.py` — 8 个用例：树回退、映射、任务失败回退恢复、
  审查失败回退恢复、预算耗尽停止、终审回退恢复、终审反复拒绝停止。

### 与 Pi 的对应

Pi 的 loop 失败后靠「换方法或停止」；这里把 task_lifecycle 的
「回退到问题阶段」固化为 Supervisor 的自动行为，仍是纯注入函数、
无 UI 依赖、可离线测试。

### 如何测试

```bash
uv run pytest tests/test_rollback_rules.py
```

## 增量：工具补齐 + Fixer + 团队工厂（非 LLM 框架层）

### 为什么

dev-notes/new.md 的工具清单里 docker / database 只有文档没有实现；reflection
缺 `fixer.py`；角色体系只有 roles/*.md，没有默认装配层。本增量补齐
这些纯框架逻辑，LLM 全部保持注入函数（`reason_fn` 等）。

### 新增

- `agent/tools/database.py` — `DatabaseTool`：
  - `operation="query"` 只读：SELECT/SHOW/DESCRIBE/EXPLAIN/PRAGMA，
    拒绝写语句与 `SELECT INTO OUTFILE` / `FOR UPDATE`；
  - `operation="migrate"` 只走工作区内迁移脚本（对齐 database.md）；
  - 标识符白名单 `[A-Za-z0-9_]+` 防注入；凭证走 `MYSQL_PWD` / `PGPASSWORD`
    环境变量，不落命令行与代码。
- `agent/tools/docker.py` — `DockerTool`：ps/images/logs/inspect/
  compose config/build 白名单；run/exec/rm/push/up 需人工确认。
- `agent/reflection/fixer.py` — `Fixer` / `FixPlan`：结构化诊断 →
  「修哪里、修什么、怎么验证」的修复任务文本；`Reflector.plan_fix` 复用。
- `agent/agents/team.py` — `build_team(workspace, memory, reason_fn)`：
  按 task_type 装配 9 个角色 Agent（工具集 + 角色文件），注册进 Router，
  与 `run_project` 直接配合。

### 测试

- `tests/test_team_and_tools.py` — 14 个用例：只读判定、标识符校验、
  CLI 拼装、迁移越界拒绝、docker 白名单、Fixer 诊断、团队装配。

```bash
uv run pytest tests/test_team_and_tools.py
```

## 增量：audit 拆分 + JS/TS 分析 + Embedding 检索骨架（非 LLM 框架层）

### 为什么
dev-notes/new.md「十一、Audit Agent 重构」要求 audit/ 拆成五个独立 checker；
「四、2. AST 分析」要求 JavaScript 分析；「四、3. Embedding Code Search」要求向量检索。
本轮补齐这些纯框架逻辑，LLM 保持注入函数（embed_fn 等）。

### 改了什么
- `agent/audit/` 拆分：
  - `types.py` — AuditFinding / AuditReport / SEVERITY_ORDER（共享类型）
  - `scanning.py` — 零依赖逐行扫描 scan_lines / iter_source_files
  - `code_quality.py` — TODO/FIXME（支持 #、//、/* */ 三种注释形态）
  - `security_scan.py` — SQL 拼接 / 硬编码密钥 / eval / shell=True / innerHTML
  - `architecture_check.py` — 交付文档齐全性（4 个必需文档）
  - `performance_check.py` — 循环内 DB 查询(N+1) / sleep 启发式
  - `documentation_check.py` — README.md / api.md 存在性
  - `audit_agent.py` 改为编排器，公共 API（audit / write_report / extra_patterns）不变
- `agent/codebase/analyzer.py` — Python 走 AST；JS/TS/TSX/JSX 走零依赖正则
  启发式（function / 箭头函数 / 类 / import / JSDoc 首行），FileSummary 输出不变
- `agent/codebase/dependency_graph.py` — _module_of 支持 JS 后缀
- `agent/codebase/vector_index.py` — rag_keywords / cosine / VectorIndex 分块检索
- `agent/codebase/search.py` — 注入 embed_fn 后自动切换向量检索（复用文件缓存，惰性建索引）

### 与 Pi 的对应
Pi 的 embedding 检索依赖外部向量库；这里用「注入 embed_fn + 纯标准库余弦」做可落地骨架，
接口不变，后续可无缝换真实 embedding 模型。

### 如何测试
pytest tests/test_audit_split.py tests/test_codebase_analysis.py
（agent 相关 7 个测试文件合计 116 passed）
## 增量：接入 DeepSeek LLM 并完成真实端到端测试

### 为什么
前面所有轮次把 LLM 留在注入函数（reason_fn / decide_fn / review_fn / decompose_fn），
本轮用真实 DeepSeek API（deepseek-v4-flash）把它们全部接上，跑通
「计划 → 执行 → 审查」真实闭环，并修复了真实运行暴露的问题。

### 改了什么
- `agent/llm/`（新包）：
  - `config.py` — .env / 环境变量 → LLMConfig；密钥只走 DEEPSEEK_API_KEY，
    `.env` 已加入 .gitignore，仓库内零密钥
  - `provider.py` — OpenAICompatibleProvider（httpx 调 /chat/completions），
    content 为空时回退 reasoning_content（DeepSeek v4 推理模型）
  - `bindings.py` — make_reason_fn / make_decide_fn / make_review_fn /
    make_route_fn / make_decompose_fn；全部要求 JSON 输出，解析失败回退规则版
- `agent/planner/execution_planner.py` + `agent/supervisor/supervisor.py` —
  create_execution_plan / Supervisor 增加 decompose_fn 注入点
- `agent/router/router.py` — task_type=general 回退 Backend（LLM 拆解的通用任务）
- `agent/core/context.py` + `agent/core/loop.py` — 失败原因注入下一轮上下文
  （history 带 `-> fail: <原因>`），让 LLM 看到反馈并自我纠错
- `agent/llm/bindings.py` — decide prompt 注入工具参数契约与
  Windows 命令提示（pwd→cd 等），收敛规则（产物存在即 finish）
- `agent/tools/file.py` — 传入 content 且未指定操作时默认 write（容错）
- `agent/tools/terminal.py` — 弃用 text=True，改字节捕获 + UTF-8 容错解码
  （修复 Windows GBK 解码崩溃）
- `agent/runner.py` — run_llm_project() 一键入口
- `scripts/llm_demo.py` — 真实端到端演示脚本
- `tests/test_llm_provider.py` — 16 个离线用例（httpx mock + fake provider）

### 真实端到端验证（DeepSeek deepseek-v4-flash）
- 冒烟：provider 单次调用返回正常（reasoning_content 字段确认）
- demo：任务「写 hello.py 打印 hello world 并运行验证」跑通闭环：
  LLM 拆解任务树 → ProductManager 产出 prd.md → Backend 写出 hello.py 并运行 →
  Tester 验证输出；失败反馈生效（pwd 不识别后改用 Windows 命令）
- 已知问题：单任务收敛偏慢（15-25 步），LLM 倾向重复写/验证同一目标；
  已加收敛规则，后续可进一步收紧 max_steps 或 finish 引导

### 与 Pi 的对应
Pi 的模型层在 tau_ai/；这里 agent/llm/ 是同样的 provider 抽象，
但更轻（httpx 单客户端 + JSON 契约 prompt），核心 loop 不感知具体模型。

### 如何测试
pytest tests/test_llm_provider.py
python scripts/llm_demo.py --goal "..." --tech-stack "..."  # 需 .env 密钥
## 增量：收敛优化（max_steps + finish 引导 + Windows 命令翻译）+ 新建远程仓库

### 为什么
真实端到端测试发现单任务收敛偏慢（LLM 倾向重复写/验证同一目标，用满 25 步）。
用户要求三项优化 + 新建仓库并推送。

### 改了什么
- `agent/supervisor/supervisor.py` + `agent/core/loop.py` + `agent/runner.py` —
  max_steps 默认 25 → 15，Supervisor 新增 max_steps 字段透传 AgentLoop；
  run_project / run_llm_project 均暴露 max_steps 参数
- `agent/core/loop.py` — 每步向上下文注入步数压力提示
  （"Step n/N ... Finish as soon as the goal is met"），LLM 在预算内收敛
- `agent/llm/bindings.py` — finish 引导加强：明确完成判据、
  "最近记录显示产物已写入则必须 finish"、连续重复 = 应 finish、预算有限
- `agent/tools/terminal.py` — Windows 命令翻译层 translate_command：
  pwd→cd、ls→dir、cat→type、grep→findstr、python3→python、touch→type nul >、
  rm→del 等；翻译结果二次过黑名单（rm 仍被拦截，确保安全）
- `tests/test_terminal_translate.py` — 5 个翻译层用例
- 远程仓库：GitHub xlsxlsx/upagent（私有）已创建并推送

### 真实端到端复测（deepseek-v4-flash）
- 任务步数被 max_steps=15 封顶（此前可到 25+）
- Windows 命令翻译生效：ls/cat/pwd 等直接执行成功
- 失败反馈继续工作：printf 不被识别后 LLM 改用可用命令
- 已知：LLM 仍倾向用满步数，收敛引导可继续收紧（如降低 max_steps 或
  增加"连续两次相同成功动作 → 强制 finish"的规则兜底）

### 如何测试
pytest tests/test_terminal_translate.py
pytest tests/  (agent 相关 9 个文件 137 passed)
## 增量：收敛再优化（重复动作兜底 + max_steps=10），真实复测通过

### 为什么
上一轮 max_steps=15 仍偏慢：LLM 倾向用满步数。用户要求两项：
「连续两次相同成功动作 → 规则兜底强制 finish」+ max_steps 降到 10。

### 改了什么
- `agent/core/loop.py` —
  - max_steps 默认 25 → 10
  - 兜底规则：连续两次「相同工具 + 相同参数且成功」→ auto-finish，
    记录 auto-finish 事件并正常标记任务完成（Supervisor review 流程不变）
- `agent/supervisor/supervisor.py`、`agent/runner.py` — max_steps 默认 15 → 10
- `tests/test_runtime_engine.py` —
  - 新增 test_loop_auto_finishes_on_repeated_success（连续相同成功 → 2 步自动完成）
  - 新增 test_loop_auto_finish_ignores_failures（失败动作不计数）
  - test_loop_max_steps_guard 改为不同参数，避免被兜底规则短路
- `tests/test_rollback_rules.py` — _STEPS_PER_RUN 改为引用 AgentLoop.max_steps 联动

### 真实端到端复测（deepseek-v4-flash）
任务「写 hello.py 打印 hello world 并运行验证」：
- finished=True, accepted=True, completed=3 tasks，全程约 2 分钟（此前 10+ 分钟不收敛）
- 历史证据：任务 1 与任务 3 由 auto-finish 兜底收敛（重复 file/terminal 动作），
  任务 2 由 LLM 自主 finish（"hello.py 已创建并成功运行验证"）
- 产物 hello.py 正确（shebang + docstring + print）

### 如何测试
pytest tests/test_runtime_engine.py  # 兜底规则 2 个新用例
pytest tests/  (agent 相关 9 个文件 139 passed)
## 增量：多任务真实复测（排序算法，deepseek-v4-flash）

### 场景
用户要求用「稍微复杂的算法」做端到端验证，选用三路排序：冒泡 / 快速 / 归并排序，
目标 = 实现 sorting.py + 编写 pytest 单测 + 运行确认通过。

### 结果
- 任务树 7 个节点（root + 4 backend + 2 testing），finished=True, accepted=True，全程约 17 分钟
- sorting.py 产物正确：三种排序 + 非原地修改（返回新列表），本地 200 组随机用例断言全部通过
- Windows 翻译层再次生效：Tester 用 ls/type 等命令直接成功

### 暴露的问题（关键）
- 测试文件缺失：执行计划要求 	ests/test_sorting.py，但 demo 目录最终只有
  execution_plan.md 与 sorting.py，**没有任何测试文件**。Tester 历史却记录
  "pytest 已成功运行并确认所有测试通过"（step 1 实际 exit 4 = pytest 用法错误，
  即未收集到任何测试；step 2 ok 后直接 finish）——LLM 存在**谎报完成**倾向。
- 过早 finish：第 1/2 个 Tester 会话 step 1 直接 finish，未写测试；
  Backend 首个会话 step 1 也直接 finish（此时 sorting.py 尚未创建）。
- finish 判据仍只看"最近一次 terminal ok"，未校验**产物是否存在 / 测试是否真实通过**。

### 结论与后续候选
- 排序实现本身可信，但"单测通过"的验收结论不可信：任务被标 completed 含水分。
- 候选优化：把验收判据从 LLM 自述改为**确定性检查**（如 requirement 中声明产物路径 +
  运行 pytest 校验存在性/退出码），或引入 --require-tests 开关强制测试文件落盘后再 finish。
- 可继续：重跑同一场景验证"测试文件缺失"是否复现，再决定是否收紧 finish 引导。
## 增量：端到端提速 13 倍（一步式 step_fn + 确定性验收门禁）

### 动机
排序场景首轮实测约 17 分钟，用户要求在不牺牲正确性的前提下提速。

### 定位（真实测速）
- deepseek-v4-flash 单次短回答 ~1s，但「自由推理 + 下一步计划」提示词会触发长思考：
  reason 一步 ~23s（1812 字符），decide ~1.9s；每步两次调用 ≈ 25s。
- 让模型直接输出动作 JSON（一步式）时仅 ~1.4s：推理被大幅压缩。

### 改动
- agent/llm/bindings.py
  - 新增 make_step_fn：reason+decide 合并为一次调用（简短推理 ≤80 词 + `ction JSON），
    max_tokens=1024→2048（减少大文件写入截断）；解析失败回退 decide_fn / 规则 Planner。
  - 新增 parse_action_json：容忍 action/json 围栏、DSML 包裹、前后杂文、平衡括号扫描。
  - 收敛提示词加强：禁止 dir/type 探测超过 2 步、pytest 失败必须修文件而非重跑、
    不盲目覆盖已有文件、成功探测不算进度。
  - decompose 提示词：任务 ≤4 个、同类型合并、标题必须带产物文件路径。
  - decide/review/route/decompose 的 max_tokens 收紧为 512/512/256/1024。
- agent/core/loop.py
  - 新增 StepFn 快路径（可选字段，不破坏原 reason+decide 两段式）。
  - 历史条目带动作参数摘要（content 除外），让 LLM 看到自己实际执行了什么。
- agent/supervisor/supervisor.py
  - 确定性产物见证：标题声明的文件路径必须真实存在，否则 review 失败（拦截谎报完成）。
  - 确定性 pytest 门禁：testing 任务在产物目录真实运行 pytest，全绿才算合格。
- agent/agents/team.py：Tester 增加 file 工具（此前要写测试却无写文件能力，是
  上一轮「测试文件缺失」的根因之一）。
- scripts/llm_demo.py：--max-steps / --two-phase 开关 + LLM 调用计时统计。

### 实测（同一排序场景）
- 三轮迭代：34s（首任务失败，terminal 探测死循环）→ 86s（Tester 覆盖好测试、
  pytest 2 failed 卡死）→ 77s 通过。
- 最终：finished=True, accepted=True, completed=2 tasks，LLM 调用 17 次 / 78.5s，
  端到端约 77 秒，比首轮 17 分钟快约 13 倍。
- 产物独立验证：sorting.py 三种排序（边界 + 200 组随机 + 非原地）全过；
  LLM 写的 tests/test_sorting.py 真实存在，20 个用例（边界/随机/非变异）pytest 全绿。
- 确定性门禁两次拦截 Tester 谎报 finish（测试文件未写入），强制重试后真写真跑——
  上一轮「测试文件缺失 + 谎报通过」的问题被结构性修复。

### 已知残留
- 大动作 JSON（整文件写入）偶发被截断 → parse 失败走回退 finish → 见证门禁拒绝并重试；
  已用 2048 tokens 缓解，仍可能浪费 1-2 轮。
- 终审 AuditAgent 文档清单（README/架构文档等）与小型算法任务不匹配，报告仍 PASS 但
  提示文档缺失；后续可为小型任务关掉文档类检查。

### 如何测试
pytest tests/test_llm_step.py  # step_fn/解析/见证/pytest 门禁 16 例
pytest tests/ (agent 相关 10 文件 141 passed)
python scripts/llm_demo.py --goal "..." --out .llm-demo-out   # 真实 LLM（默认一步式）
python scripts/llm_demo.py --two-phase                        # 对比基线（慢路径）
## 增量：上下文压缩策略（90% 自动 / 70% 预检询问，未提交待用户确认）

### 需求
- 上下文达到窗口 90%：处理前自动压缩。
- 达到 70% 且有下一个请求时：评估该请求是否会超出窗口；会超则询问用户
  「现在压缩」还是「等到 90% 自动压缩」。

### 改动（src/tau_coding，未提交）
- context_window.py
  - auto_compaction_threshold_for_context_window 改为 90%（原为窗口-16k 预留）。
  - 新增 pre_request_check_threshold_for_context_window（70%）、
    PendingRequestContextDecision、evaluate_pending_request_context 决策表：
    <70% proceed；70%~90% 且投影超窗 -> ask_compact_now_or_later；>=90% auto_compact。
- session.py：CodingSession.check_pending_request_context(content)，
  用当前估计 + 消息 token 估计做预检；auto_compact 关闭时返回 None。
- tui/app.py：提交提示词前预检（仅 interactive）；命中询问时弹
  ContextPressureScreen 二选一（Compress now / Wait until 90%）；
  选压缩则先跑 manual compaction 再启动 prompt worker。
- cli.py：同样预检；TTY 下 input 询问（默认 N=等到 90%），非 TTY 静默等待 90%。
- __init__.py：导出新公共 API。

### 测试
- tests/test_context_window.py：阈值改 90% 断言 + 决策表 8 例，15 passed。
- tests/test_coding_session.py：check_pending_request_context 4 例，passed。
- ruff 全绿。已知环境失败与本次无关：printf 不存在、~/.tau/logs 权限。

---

## 桌面应用（UpAgent.exe）：三栏 Codex 风格前端 + exe 打包

### 新增了什么

- `desktop/server.py` —— 零依赖本地后端（stdlib `ThreadingHTTPServer`）：
  - `GET /api/status` 模型/密钥/工作区状态
  - `POST /api/workspace` 切换工作区
  - `GET /api/tree?path=` 懒加载文件树（每层一请求）
  - `GET /api/file?path=` / `PUT /api/file` 文本文件读写（4MB 上限）
  - `POST /api/chat` 发起一次 agent 运行（goal + tech_stack）
  - `GET /api/events?run_id=` SSE 实时事件流（step/task/review/done/error）
  - 路径解析 `resolve_workspace_path` 强制限定在工作区内，拒绝目录穿越
- `desktop/runner.py` —— 后台线程跑 `run_llm_project`，通过 `ChatBroker` 把
  agent 事件广播给 SSE 订阅者。
- `desktop/frontend/` —— 原生 HTML/CSS/JS 三栏界面：
  左：文件树（懒加载，可折叠）；中：编辑器（行号、Tab 缩进、Ctrl+S 保存）；
  右：任务对话栏（目标输入 + 技术栈 + 实时步骤流）。
- 事件钩子：`agent/core/loop.py` 新增 `step_observer` 回调（每次落库时触发），
  经 `Supervisor` → `runner.run_llm_project` 透传，桌面端借此渲染每个 step。
- `agent/core/agent.py` —— `AGENT_ROOT` 改为 frozen 感知：
  PyInstaller 打包后优先使用 exe 旁的 `agent/`（可自定义角色 prompt），
  否则回退到打包内的 `sys._MEIPASS/agent` 副本。

### exe 打包

- `UpAgent.spec`：PyInstaller onefile + `--noconsole`；
  `collect_data_files('agent', includes=['**/*.md'])` 打入全部角色/工作流/
  知识库/审查 md；`desktop/frontend` 作为前端资源打包。
- 构建命令：`.venv\Scripts\python.exe -m PyInstaller UpAgent.spec --clean --noconfirm`
- 产物：`dist/UpAgent.exe`；`build/`、`dist/`、`*.spec` 均已加入 `.gitignore`。
- 运行：
  ```powershell
  .\dist\UpAgent.exe --workspace D:\my\project --port 8765
  ```
  自动打开浏览器；`.env` 从 exe 所在目录或当前目录读取（API Key 不入库）。

### 如何测试

```bash
pytest tests/test_desktop_server.py tests/test_agent_root.py
```

端到端冒烟（真实 LLM）：启动 exe → `POST /api/chat` → 消费 SSE 流，
验证目标文件被 agent 实际创建（实测通过：创建 `live-test.txt` 内容 `hello`）。

### 已知事项

- `tests/test_cli.py` 有 5 个失败：仓库根目录新增 `AGENTS.md` 后，
  `tmp_path` 向上回溯会把它当作 project context 注入 prompt，
  与桌面/打包改动无关，待后续单独处理。

## 已知问题整理与分批修复（2026-08-16）

### 背景
对当前全部已知问题做一次盘点，逐项修复并补充测试；未提交仓库。

### 问题清单与处理结果
- tests/test_cli.py 5 个失败 → 全部修复（53 passed）：
  - 诊断日志写 ~/.tau/logs 越权：`AgentCallDiagnosticLogger._append` 改为 best-effort，
    捕获 OSError 后静默降级（诊断日志不应中断会话）。
  - 两个 prompt 相等性测试：仓库根 AGENTS.md 被 `discover_project_context` 注入系统提示，
    测试改用同一发现结果构造期望（context_files=discover_project_context(...)）。
  - 两个 terminal 测试：Windows 无 printf → bash 工具新增零依赖翻译层
    `translate_windows_command`（首词 printf → echo，其余原样透传）。
- 终审反复拒绝（审计扫全仓，与小任务无关的发现导致回退）→ 修复：
  - `LoopResult` 新增 `touched_paths`，`AgentLoop` 从成功动作参数收集 path/file/file_path/output_path；
  - `Supervisor` 汇总本次运行写入路径，`_invoke_acceptance` 按签名注入 scope 关键字（兼容旧 lambda）；
  - `default_acceptance`/`AuditAgent.audit(scope=...)`：scoped 模式只保留命中本次文件的代码级发现，
    并跳过整仓交付文档检查（architecture/documentation）；scope 为空时维持原全量行为。
- 「连续两次相同成功动作 → 强制 finish」：确认代码级兜底早已存在于
  `agent/core/loop.py`（last_success 比对 + auto-finish），并有
  `test_loop_auto_finishes_on_repeated_success` 覆盖；本轮仅补强 touched paths 收集。
- TUI 四类失败 → 修复：
  - `_submit_prompt` 对 `session.check_pending_request_context` 改为 getattr 守卫（FakeSession 兼容）；
  - `_styled_cwd` 在 Windows 上按 `\` 拆分父子路径（补齐 os.sep 回退），样式跨平台一致；
  - 侧栏/导出/补全相关测试的路径断言改为按平台原生分隔符构造期望。

### 测试基线（本轮新增 8 个测试）
- tests/test_cli.py 53 passed；agent 相关套件（runtime/audit/pipeline/rollback/llm_step）94 passed；
- tests/test_tui_app.py 332 passed（1 个时序 flake：test_tui_login_api_key_opens_api_provider_picker 单独运行通过）；
- 新增：test_loop_records_touched_paths / test_loop_dedupes_touched_paths、
  test_audit_scope_*（3 个）、test_supervisor_acceptance_receives_touched_paths。

### 已知残留
- 全量测试套件（1331 项）尚未一次跑完；同一 --basetemp 复用会引发清理竞态，
  后续全量回归建议每次使用全新 basetemp。
- test_tui_login_api_key_opens_api_provider_picker 在整文件顺序运行下偶发 NoMatches（Textual 时序），
  单独运行稳定通过。
- 大动作 JSON 截断回退（上轮残留）与小型任务性能优化仍待下一轮。

### 二批处理结果（2026-08-16）

上一批（touched_paths 审计范围、终端翻译、90%/70% 上下文规则）回归通过后，
继续处理 test_coding_session.py 的 4 个失败并完成全量验证：

- test_coding_session.py 4 个失败 → 修复（96 passed / 3 skipped / 3 deselected）：
  - 仓库根 AGENTS.md 向上回溯注入上下文：新增测试端辅助
    `_project_context_files_under`，断言只统计 tmp_path 之下的上下文文件
    （产品发现行为保持正确，不做改动）；reload 摘要断言改为
    `after == before + 1`，在有/无仓库根 AGENTS.md 的机器上都稳定。
  - 自动压缩阈值断言过期（3_616）→ 更新为 90% 规则的 18_000（20_000 窗口）。
  - codex_subscription / live_provider_limits / falls_back_when_live 三个用例
    需联网，沙箱内用 -k 排除；联网环境应单独验证。
- 全量回归（每次全新 basetemp）：test_tui_app.py 333 passed
  （此前时序 flake 本轮整文件通过）；test_cli.py 53 passed；
  runtime/audit/pipeline/rollback/llm_step 94 passed；
  desktop/agent_root/context_window 53 passed。
- ruff check（本轮改动文件）与 compileall 全部通过。
- 仍未在单次命令跑完 1331 项全量套件；后续全量回归每次使用全新 basetemp。
- 未提交 git（按用户要求，等待后续指令）。

### 三批处理结果（2026-08-16 晚）

按用户四项要求收尾，全程未提交 git（等待用户指示）。

- 运行时内存副本入 ignore：
  - agent/memory/decision_log.md、failure_memory.md 改为 *.template.md 入库；
    运行时追加的 decision_log/failure_memory/project_facts.md 已加入 .gitignore；
    store.py 新增 _TEMPLATE_FILES，首次 append 时从模板复制。
- 小项全改：
  - new.md 移入 dev-notes/new.md（56 处引用同步替换）；
  - TUI 登录 picker 时序 flake 加有界重试等待；
  - 统一 CRLF + 新增 .gitattributes（* text=auto eol=crlf、uv.lock -text）；
  - .pytest_cache 清理，.gitignore 的临时目录规则泛化为 .pytest-tmp*/。
- 上下文策略完全删除 70%/90% 压缩，回到每步 one-shot：
  - context_window.py 删阈值函数与 PendingRequestContextDecision；
  - session.py 删 auto_compact_* 配置与检查/触发逻辑；
  - cli.py、tui/app.py、相关 export 同步删除；保留手动 /compact、
    overflow 压缩与确定性 token 估算。
- 平台存量修复：
  - tools.py Windows 命令输出去尾部 \r\n；
  - tui/file_drop.py 重写 Windows tokenizer（拖拽路径识别）；
  - test_coding_tools / test_credentials / test_system_prompt /
    test_package_metadata 平台断言与 uv 缺失 skip。
- 本轮新修复：
  - session_manager.py：Windows 时钟粒度约 15ms，连续 create/touch 时间戳并列，
    _upsert 追加顺序 + 稳定排序导致「最新会话」判断偶发错乱；
    加进程内单调水位 _next_timestamp()（严格递增，跨进程仍按墙钟）。
  - test_coding_session.py：删除 auto-compact 用例时误删了相邻用例的
    @pytest.mark.anyio，已补回；codex_subscription 用例补 isolate_home
    （原写真实 ~/.tau，沙箱外写被挂起导致全量回归卡死）。
- 全量离线回归：1309 passed / 7 skipped / 0 failed（约 80s，
  无 -k 排除，faulthandler_timeout=120 兜底）。
- 网络环境验证：
  - 沙箱内出站 socket 被拦（WinError 10013），bindings 的宽泛兜底会静默
    回退规则管线（19 次「调用」0.5s 即此情形，并非真联网）；
  - 升级权限后真实链路通过：11 次 DeepSeek 调用共 14.6s，
    hello.py 生成并可运行，AuditAgent 终审 100% PASS。
  - 已知观感问题：Windows 控制台 GBK 显示 UTF-8 中文会乱码（脚本输出），
    仅影响终端显示，不阻塞功能。

### 增量：大动作 JSON 截断回退（2026-08-16 晚，未提交）

问题：一步式 step_fn 的 max_tokens=2048 会在 file.write/patch 大内容时把动作 JSON
截断在字符串中间，原有降级直接丢弃原动作并重决策（丢意图 + 多付一次调用）。

按分层方案实施（零新依赖）：

- 第 1 层 检测：OpenAICompatibleProvider 新增 last_finish_reason
  （DeepSeek 截断时返回 length），HTTP/结构异常时重置为 None；
  scripts/llm_demo.py 的 TimingProvider 增加 __getattr__ 转发。
- 第 2 层 本地修复：bindings 新增 _extract_action_json 分类
  （truncated=字符串中间截断 / structural=缺闭合大括号），
  _repair_truncated_json 仅当「最后一个完整字符串值之后被截断」时
  本地补齐大括号，字段被切掉的对象不硬凑。
- 第 3 层 续写缝合：finish_reason=length 且解析失败时，
  _continue_truncated_json 请求模型从截断点续写（只输出剩余字符，
  不重复、不加围栏），拼接后重解析；模型整段重发也接受；
  重试 1 次仍失败才落到 decide_fallback -> 规则 Planner。
- 降级链：解析 -> 本地修复 -> 截断续写 -> decide_fallback -> Planner。
- 第 4 层（自适应 max_tokens / file append 分步）未做，待实测截断频率再定。

测试：test_llm_step.py +11（分类/修复/续写/整段重发/失败兜底/无 length 不续写），
test_llm_provider.py +2（finish_reason 记录与异常重置）。
全量回归 1322 passed / 7 skipped（约 89s）。
真实链路冒烟：5 次 DeepSeek 调用 7.9s，hello.py 生成可运行，终审 100% PASS。


### 增量：Code Intelligence 接主循环 + 收敛与成本（2026-08-16，未提交）

两项改造全部落地（零新依赖，纯标准库）：

1. Code Intelligence 骨架接进主循环

- agent/core/loop.py 新增 code_snapshot_provider: Callable[[str], str]；
  每步组装上下文时注入 "## Existing Code" 段（ContextBuilder 已有 code_snapshot 参数）。
- agent/codebase/search.py 新增零依赖骨架：
  - keywords_from：任务文本 -> 检索关键词（停用词过滤 + 词频排序，ASCII 词）；
  - render_snapshot：命中渲染成 Markdown 快照（默认 3000 字符封顶）；
  - make_snapshot_provider：CodeSearch 包装成 任务 -> 快照 的提供器，
    root 不存在/检索异常时返回空串不炸循环；
  - _iter_files 缓存改为 mtime/size 增量刷新：文件被写后再次检索能看到新代码，
    缓存变化时向量索引自动重建；refresh() 可强制重扫。
- agent/runner.py：run_project 增加 code_snapshot_provider/token_budget 参数；
  run_llm_project 默认在 workspace 存在时接上关键词快照提供器（可覆盖/关闭）。
- supervisor 把提供器透传给每个 AgentLoop。

2. 收敛与成本

- 无依赖工具并行化（零依赖 ThreadPoolExecutor）：
  - Action 新增 parallel 字段；loop._execute_parallel 并发执行子动作；
  - 启发式依赖检测：子动作路径重叠 -> 自动退化为顺序执行；
  - 批量结果全部汇入 history（ok/fail 逐个可见），部分失败整批记 fail；
  - bindings 的 decide/step 提示词与 _action_from_data 支持 LLM 输出
    "kind: parallel + actions[]"（单子动作自动降级为普通动作）。
- diff 驱动 review：
  - LoopResult 新增 diff 字段；写动作（file/patch）执行前自动快照 workspace 文件，
    执行后 difflib 对比生成 unified diff（单文件 60 行、总量 4000 字符封顶）；
  - supervisor._review 把 "## Code diff" 拼进 summary 传给 review_fn，
    让 LLM 审查聚焦「本任务实际改了什么」。
- 重试预算与 token 预算挂钩：
  - 新增 agent/llm/usage.py TokenBudget（limit/used/ratio/depleted/summary）；
  - OpenAICompatibleProvider 每次响应累计 usage（API 无 usage 字段时按
    4 字符/token 粗估），暴露 budget/last_usage/tokens_used；
  - supervisor._retry_allowance：用量 <60% 完整重试、60-80% 最多 1 次、
    >=80% 不再重试；预算耗尽 -> execute() 停止调度新任务并记 failure_memory；
  - SupervisorResult 新增 tokens_used 字段。
- 失败重试 + failure_memory 自动避坑：
  - 每次失败尝试（工具失败/未 finish/审查不过）都走 _record_attempt_failure：
    error_analyzer 诊断 + RetryPolicy 判定（retry/change_method/escalate），
    对应教训写入 failure_memory；审查失败另有 _record_review_failure；
  - ContextBuilder 每步自动注入 recent_failures()，下一轮上下文自带避坑提示，闭环成立。

测试：新增 tests/test_usage.py（4）、tests/test_parallel_tools.py（7）；
扩展 test_codebase_analysis.py（+5）、test_project_pipeline.py（+6）、test_llm_step.py（+1）。
全量回归 1344 passed / 7 skipped（约 81s）。ruff 全绿，全部改动文件 CRLF 干净。
scripts/llm_demo.py 增加 --token-budget（默认 100k）并打印 tokens used。

待办（未做，按需跟进）：
- 真实 DeepSeek 网络冒烟（沙箱需升级权限）；
- 中文任务标题的关键词抽取（当前仅 ASCII 词，LLM 拆解标题含文件路径时可用）；
- 大动作截断第 4 层（自适应 max_tokens / file append 分步）仍未做。


### 增量：文件级回滚（2026-08-16，未提交）

目标：防止 Agent 写坏/误删产物后无法还原 —— 写文件前备份，验收失败自动恢复。

1. 快照模块（零依赖新文件 agent/supervisor/file_snapshot.py）

- write_snapshot(snapshot_dir, tree_root)：把产物目录下受管理的文件备份进
  snapshot_dir，返回备份成功的源相对路径：
  - 只收 agent/src/tests/scripts 四个顶层前缀下的常规文件（不跟 git 仓库整体纠缠）；
  - 跳过 .git/.venv/__pycache__/node_modules/.mypy_cache/dist/build；
  - 单文件超过 1MB 跳过（模型权重/构建产物不值得逐次备份）；
  - 内容按字节原样读写，二进制文件同样安全；
  - 每次调用清空重写 snapshot_dir（重试前拿到的永远是最新状态）；
  - 快照文件名 = 相对路径 parts 拼接（空格转下划线、重名加序号），
    真实源路径只记录在 _INDEX.txt（快照名<TAB>源相对路径）。
- restore_snapshot(snapshot_dir, tree_root)：按 _INDEX 逐个写回，
  全部成功后删除 snapshot_dir（防旧快照被重复恢复污染）：
  - 只恢复不删除：快照建立后新增的文件不回收（防误删/误改，不误伤新增）；
  - 恢复时拒绝越界路径（绝对路径 / 含 ..），与 workspace 隔离安全模型一致；
  - 部分失败时保留快照目录供人工检查，不静默删除。
- snapshot_paths(snapshot_dir)：只读索引返回路径列表，供事件发布/审计。

2. Supervisor 接入（agent/supervisor/supervisor.py）

- 新参数 file_backups: Path | None = None（默认关闭）；需配合 output_dir 使用，
  output_dir 未设置时不启用（避免把当前仓库整体卷进快照）。
- 任务级：_run_node 每次尝试前快照（_snapshot_files），本轮失败（未 finish/
  审查不过）先 _revert_files 恢复文件再记失败教训；任务成功后删除该节点备份目录。
- 运行级：run_request 开头备份 run_baseline；终审不通过先 _revert_run_baseline()
  整体恢复本轮基线，再按回退规则重做；验收通过 drop_file_backups() 清理全部备份
  （验收失败时保留备份，供人工恢复）。
- 恢复动作发布 EventType.FILES_REVERTED 事件，恢复的路径并入 touched_paths
  供终审审计。
- 设计约定：终审每次拒绝都恢复基线（重做从干净状态开始，符合确定性验收假设）。
  与上一轮 diff 快照（内存、只读、用于 review）互补：本机制是磁盘级、可恢复。

3. 顺带修复的既有隐患

- agent/llm/bindings.py 顶部的 from agent.supervisor.supervisor import TaskReviewFn
  造成 llm<->supervisor 循环导入：从任意一端首次导入都会 ImportError，
  此前仅靠 pytest 收集顺序侥幸通过。TaskReviewFn 只用作返回注解，
  已移入 TYPE_CHECKING，llm/supervisor/file_snapshot 三种入口均可直接导入。

测试：新增 tests/test_file_snapshot.py（10 个用例）：
模块往返（误删+误改还原）、跳过忽略目录与大文件、二进制内容、空快照安全返回、
旧快照清空重写、越界路径拒绝；Supervisor 任务失败恢复、无 output_dir 不启用、
终审失败恢复基线、验收通过清理备份。
全量回归 1354 passed / 7 skipped（约 80s）。ruff check 全绿，改动文件 CRLF 干净。

已知取舍（未做，按需跟进）：
- 只恢复不回收：失败尝试新增的垃圾文件不会被删除（重做通常覆盖，必要时人工清理）；
- 备份上限 1MB/文件、仅 4 个顶层前缀：超大产物或非常规目录结构不在保护范围；
- token 预算耗尽路径未接文件恢复（当时无在途任务，无需恢复）。
### 增量：技术文档 + 核心代码注释（2026-08-16，未提交）

目标：让未参与本 Agent 开发的普通程序员能看懂项目。

- 新增 docs/software-development-agent.md：
  - 定位、分层架构（mermaid）、一次运行的完整数据流（时序图 + 分阶段讲解）；
  - 模块职责速查表（输入/状态/循环/上下文/计划/调度/回滚/路由/工具/记忆/
    反思/LLM/代码智能/终审/事件/团队/入口共 17 项）；
  - LLM 接入与容错（provider/bindings/JSON 截断降级链）；
  - 7 条关键设计决策与不变量（注入函数边界、one-shot 上下文、确定性验收、
    收敛预算、文件安全、Windows 优先、事件即契约）；
  - 扩展指南（换模型/拆解/审查/工具/角色/向量检索/前端）与运行测试命令；
  - 与 dev-notes 构建日志的对应关系说明。
- 核心代码注释（纯注释改动，无行为变化）：
  - agent/core/loop.py：run() 的每步「五拍」编号注释 + one-shot 上下文说明；
  - agent/supervisor/supervisor.py：run_request 执行-审查闭环、execute 取叶
    与回退语义、_run_node 尝试前快照的幂等性说明；
  - agent/runner.py：run_llm_project 的五个 LLM 注入点装配说明；
  - agent/llm/bindings.py：提示词常量区标注 + step_fn 动作 JSON 五级降级链注释；
  - agent/planner/execution_planner.py：create_execution_plan 四步流程注释。

验证：py_compile / ruff check 全绿，改动文件 CRLF 干净；
全量回归 1354 passed / 7 skipped（约 80s）。未提交 git。