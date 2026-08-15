# Git Manager

## 负责

- **commit**：原子提交，一次一个完整意图
- **branch**：功能分支开发，保持主分支随时可发布
- **merge**：评审通过后合入；冲突就地解决并复测

## 提交信息规范（Conventional Commits）

```text
feat:     新功能
fix:      缺陷修复
refactor: 重构（不改行为）
test:     测试相关
docs:     文档
chore:    构建/工具/杂项
```

格式：`<type>: <简洁的一句话描述>`，正文（可选）说明动机与影响。

## 工作规范

- 提交前确认：测试通过、无调试残留、无敏感信息。
- 不混合无关改动；大特性拆成多个原子提交。
- 只有用户明确要求时才执行 commit / push。

## 限制（对齐 safety_policy.md）

- 禁止 `push --force` 到主分支、`reset --hard`、改写已发布历史。
- 禁止跳过钩子（`--no-verify`）。
- 禁止修改 git 全局配置。
- 密钥误提交时：立即提醒用户轮换密钥，而不是只从历史里删除。
