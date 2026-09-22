# Decision Log

记录「为什么这么设计」。所有重要技术决策（选型、架构取舍、安全方案）都必须留档。
只追加，不删除；决策被推翻时新增一条并标注取代关系，保留原始记录。

## 记录规则

- 什么算「重要」：影响架构、难以回退、多个方案争议大、涉及安全的决策。
- 每条必须包含：决策、理由、备选方案与放弃原因、日期。
- 由做出决策的角色负责记录（多数来自 Architect 与 Supervisor）。

## 条目模板

```markdown
## D-<编号>: <决策标题>

Decision:
<做了什么决定，例如：Use PostgreSQL>

Reason:
<为什么，例如：Need relational consistency，事务与外键约束是订单系统的硬需求>

Alternatives Considered:
- <备选方案 A>：<放弃原因>
- <备选方案 B>：<放弃原因>

Consequences:
<这个决策带来的影响与约束>

Status: Active | Superseded by D-<编号>

Date: <YYYY-MM-DD>
Role: <决策角色>
```

---

<!-- 从这里开始追加决策记录 -->
