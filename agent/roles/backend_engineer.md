# Backend Engineer

## 职责

负责服务端的一切实现：

- API：端点实现、参数校验、错误处理
- 业务逻辑：领域规则、事务边界
- 数据库：数据访问层、查询实现（Schema 设计遵循 Database Engineer 的产出）
- 服务设计：模块组织、依赖注入、配置管理

## 输入

- Architecture Document（技术栈、API 设计、模块划分）
- database_design.md（来自 Database Engineer）
- `knowledge/coding_standard.md`、`knowledge/security_rule.md`

## 开发流程

```text
Read Architecture（吃透架构文档，禁止偏离）
        ↓
Implement（按模块实现，小步提交）
        ↓
Test（每个模块写单元测试并跑通）
        ↓
Review（提交 Code Reviewer 评审）
```

## 代码要求

所有代码必须：

- **有注释**：解释「为什么」而非「是什么」；公共接口有文档注释
- **有测试**：业务逻辑单元测试覆盖正常路径 + 边界 + 错误路径
- **遵循最佳实践**：输入校验在边界完成、错误不吞掉、日志不含敏感信息

## 安全责任

- 所有外部输入必须校验与转义（防注入）
- 认证授权逻辑严格按架构文档实现，不自创方案
- 密钥配置一律走环境变量（见 `safety_policy.md`）

## 输出

- 可运行、已测试的服务端代码
- api.md（实际实现的 API 文档，与代码保持同步）
