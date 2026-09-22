# Execution Policy（执行策略）

任何 Agent 执行任务时必须遵守的总策略。Supervisor 按本文件裁决「继续 / 换方法 / 上报」。

## 执行原则

1. 单任务单目标：一次循环只解决任务树上的一个叶子节点。
2. 先看再动：编码前必须读取 Repository Map 与相关文件，禁止盲改。
3. 小步提交：每个可验证的改动点独立完成并验证，再进入下一个。
4. 预算上限：单任务循环 ≤ 10 步（AgentLoop.max_steps）；单任务重试 ≤ 2 次（Supervisor.max_retries，与 token 预算联动收紧）。

## 完成判定

- 任务声明的交付物存在且通过对应 evaluation/ 清单。
- 测试类任务：test_runner 输出 0 failed。
- 文档类任务：文件存在且包含要求的章节。

## 失败处理

| 情形 | 动作 |
| --- | --- |
| 首次失败 | 原地重试（retry） |
| 同类错误第 2 次 | 换方法（change_method），禁止重复同一方案 |
| 同类错误第 3 次 / 超总预算 | 上报 Supervisor（escalate），记入 failure_memory.md |

## 禁止事项

- 禁止跳过 workflow/task_lifecycle.md 的阶段门禁。
- 禁止在测试失败时用放宽断言、跳过用例的方式「转绿」。
- 禁止未经 Patch 审核直接批量重写文件。
