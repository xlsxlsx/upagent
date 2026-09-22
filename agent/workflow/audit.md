# Audit Workflow

覆盖 Task Lifecycle 的 security 阶段，由 Security Auditor 主导。
这是交付前的强制关口：审计不通过，项目不得进入交付。

## 流程

```text
读取 architecture.md + api.md + database_design.md + 全部源代码
    ↓
确定审计范围（信任边界、外部输入入口、敏感数据流向）
    ↓
按 security_rule.md 清单逐项检查
    ↓
依赖审计（已知 CVE、来源、许可证）
    ↓
输出 security_report.md（发现分级 + 修复建议）
    ↓
Critical / High → 工程师修复 → 复审
    ↓
结论「通过」→ deploy 阶段
```

## 审计范围

1. **代码审计**：认证授权、注入、XSS、CSRF、敏感数据处理（清单见 `roles/security_auditor.md`）
2. **配置审计**：默认口令、调试开关、错误信息暴露、CORS、安全响应头
3. **依赖审计**：`npm audit` / `pip-audit` / `uv` 等工具扫描 + 人工确认高危项
4. **数据审计**：存储加密、日志脱敏、备份策略

## 修复循环

- 每个 Critical / High 发现 → 指派对应工程师修复 → Security Auditor 复审该项。
- 修复必须针对根因，禁止只堵报告中的单一路径。
- 复审通过后更新 security_report.md 的状态列，全部清零才可给「通过」。

## 红线

- 审计报告必须如实：不得为了推进进度降低发现的严重级别。
- 遗留 Medium/Low 项必须逐条列出并经用户知情确认。
- 本审计仅针对自有项目的防御性检查，不产出攻击性利用代码。
