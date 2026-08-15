# 软件开发 Agent 流水线阶段记录（计划 → 执行 → 审查）

> 对应 `agent/` 包（AI Software Engineering Organization）的一轮增量升级。
> 上游设计草案见 `new.md`，运行时说明见 `agent/README.md`。

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

new.md 的工具清单里 docker / database 只有文档没有实现；reflection
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
new.md「十一、Audit Agent 重构」要求 audit/ 拆成五个独立 checker；
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