# Final Acceptance

最终验收，由 CEO Agent 在 Phase 8 执行。项目完成必须满足以下全部条件。

## Function — 所有需求完成

- [ ] PRD 中全部 P0 功能已实现并可演示
- [ ] 每个 P0 功能的验收标准（Given/When/Then）逐条验证通过
- [ ] 遗留的 P1/P2 项已列入清单并经用户知情

## Code — 代码质量合格

- [ ] 全部代码经 Code Reviewer 评审通过（`quality_check.md`）
- [ ] 项目可从零构建并运行（干净环境实测）
- [ ] 无 Blocker / Major 级未修复问题

## Test — 测试通过

- [ ] test_plan.md 与 test_report.md 齐全
- [ ] 全量测试一条命令可重复执行且全部通过
- [ ] test_report 结论为「通过」

## Security — 无高危漏洞

- [ ] security_report.md 齐全，结论为「通过」（`security_check.md`）
- [ ] 无未修复的 Critical / High 漏洞
- [ ] 遗留 Medium/Low 项已经用户确认

## Documentation — 文档完整

- [ ] architecture.md、api.md、database.md 与实现一致
- [ ] deployment.md 实测可照做（从零跑通）
- [ ] README / 使用说明覆盖启动与基本使用

## 判定规则

```text
全部通过 → 交付给用户（附交付物清单与遗留项说明）

任何一项失败 → 返回开发阶段：
  - 定位失败项对应的阶段（见 task_lifecycle.md 回退规则）
  - 修复后重新通过该阶段及其后续所有门禁
  - 在 project_memory.md 记录本次回退原因
```

**禁止带着未通过项交付。禁止口头承诺「后面再补」。**
