# Failure Memory

记录失败与教训。目标：**同类错误不允许出现第二次**。

## 何时记录

- 同一方法连续失败两次以上，被迫换思路时
- 阶段被打回（测试不通过、审计不通过、评审拒绝）的根因
- 环境/工具坑（构建失败、依赖冲突、平台差异）
- 错误假设导致的返工

## 使用规则

- 开始一个新子任务前，先扫一眼本文件，避开已知的坑。
- 只追加，不删除；同一教训重复出现时在原条目上加重次数标记。
- 教训要写成**可执行的规避动作**，不写空泛的「下次注意」。

## 条目模板

```markdown
## F-<编号>: <失败标题>

What Happened:
<发生了什么，在哪个阶段/子任务>

Root Cause:
<根因分析，不是表面现象>

Wrong Assumption:
<当时错在哪个假设或判断>

Lesson (可执行的规避动作):
<下次遇到类似情况，具体怎么做>

Date: <YYYY-MM-DD>
Role: <相关角色>
```

---

<!-- 从这里开始追加失败记录 -->

## F-1: task stuck: 创建 hello.py 文件

What Happened:
failed after 3 runs and 0 rollbacks (type=general)

Lesson (可执行的规避动作):
回退到问题产生的阶段修复；重复回退两次以上应拆小任务或补充需求上下文后重新计划

Date: 2026-08-15
Role: Supervisor

## F-2: task stuck: 编写打印 hello world 的代码

What Happened:
failed after 3 runs and 0 rollbacks (type=backend)

Lesson (可执行的规避动作):
回退到问题产生的阶段修复；重复回退两次以上应拆小任务或补充需求上下文后重新计划

Date: 2026-08-15
Role: Supervisor

## F-3: task stuck: 编写hello.py打印hello world

What Happened:
failed after 3 runs and 0 rollbacks (type=backend)

Lesson (可执行的规避动作):
回退到问题产生的阶段修复；重复回退两次以上应拆小任务或补充需求上下文后重新计划

Date: 2026-08-15
Role: Supervisor
