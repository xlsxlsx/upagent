# Coding Strategy（编码策略）

Developer Agent 写代码时的方法论。配合 knowledge/coding_standard.md（写什么样的代码）使用，本文件规定「怎么下手」。

## 编码前

1. 读 Repository Map（codebase/repository_map.py 输出），确认目标文件与其依赖。
2. 用 codebase/search 定位相关实现，禁止凭空新建重复模块。
3. 用 dependency_graph.impacted_by 评估改动影响面，影响面大的先拆小。

## 编码中

1. 修改走 Patch Tool：-old/+new diff → 审核 → 应用。
2. 一次 patch 只改一个关注点；跨文件的联动改动按依赖顺序逐个应用。
3. 新代码必须带类型标注与必要注释，风格与周围代码一致。
4. 涉及外部服务的逻辑留注入口（函数参数/依赖注入），保证可离线测试。

## 编码后

1. 立即跑 test_runner 验证，不积攒未验证的改动。
2. 关键决策（选型、取舍）写入 memory/decision_log.md。
3. 项目级事实（如「认证用 JWT」）写入 Project Memory。

## 边界

- 不重构与本任务无关的代码（记 TODO 并上报，不顺手改）。
- 不引入未在 package_manager 白名单流程内声明的依赖。
