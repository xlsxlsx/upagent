# Tool Usage Policy（工具使用策略）

规定每类操作应该用哪个工具、什么顺序、什么禁区。工具能力边界见 tools/*.md。

## 工具选择表

| 操作 | 首选工具 | 说明 |
| --- | --- | --- |
| 修改已有代码 | patch | 先 preview 出 diff，审核后 apply |
| 新建文件 | file (write) | 新文件可直接写入 |
| 读文件 | file (read) | 大文件只读需要的部分 |
| 跑测试 | test_runner | 输出含 passed/failed 摘要 |
| 装依赖 | package_manager | 只放行 install/list 类命令 |
| 其他命令 | terminal | 受危险命令黑名单约束 |
| 版本操作 | git | 只读 + add/commit，禁 push --force |
| 查资料 | browser | 只读 GET，有大小与超时限制 |

## 使用顺序约定

1. 修 bug：file(read) → test_runner（复现）→ patch → test_runner（验证）。
2. 新功能：file(read) 相关文件 → file(write)/patch → test_runner。
3. 依赖变更：package_manager → test_runner（确认不破坏现有测试）。

## 禁区

- 不用 terminal 绕过 patch/file 的工作区约束写文件。
- 不用 terminal 执行 package_manager/git 已覆盖且被其限制的操作。
- 工具连续失败 2 次：停止重复调用，改变参数或换工具。
