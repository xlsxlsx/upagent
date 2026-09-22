# Security Check

Security Auditor 在 security 阶段使用的安全验收清单（防御性自查）。
依据 `knowledge/security_rule.md`，结论写入 security_report.md。

## 检查清单

### Authentication

- [ ] 密码使用 bcrypt / argon2 哈希，无 MD5/SHA1/明文
- [ ] 会话/Token 随机性足够、有效期合理、注销后失效
- [ ] 登录有防暴力破解措施（限流/延迟/锁定）
- [ ] 登录失败提示不泄露账户存在性

### Authorization

- [ ] 每个受保护端点在服务端做权限校验
- [ ] 资源归属校验到位（无水平越权）
- [ ] 无角色提权路径（无垂直越权）
- [ ] 默认拒绝策略生效

### Injection & Web

- [ ] 无拼接 SQL；命令执行不含用户输入拼接
- [ ] 文件路径操作有目录约束（无路径穿越）
- [ ] 用户内容输出全部转义（无 XSS）
- [ ] 状态变更接口有 CSRF 防护；Cookie 属性完整
- [ ] CORS 非通配；安全响应头配置合理

### Sensitive Data

- [ ] 代码与版本库无硬编码密钥（含历史提交抽查）
- [ ] 日志无敏感信息；错误响应不暴露内部细节
- [ ] 传输 HTTPS；敏感字段存储加密/哈希
- [ ] 调试开关在生产配置中关闭

### Dependency

- [ ] 依赖漏洞扫描已执行（工具 + 结果附报告）
- [ ] 无未处理的 Critical / High CVE
- [ ] 依赖版本已锁定，来源可信

## 结论判定

- 全部通过，或仅剩用户确认遗留的 Medium/Low → **通过**
- 存在未修复 Critical / High → **不通过**，回退 implementation 阶段修复后复审
