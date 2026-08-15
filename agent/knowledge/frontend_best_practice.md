# Frontend Best Practice（前端最佳实践）

前端（React 为主，通用于组件化框架）准则，frontend 子域任务必读。

## 组件

- 组件单一职责：展示组件不拿数据，容器组件不写样式细节。
- Props 显式类型化；禁止透传整个大对象只用其中一两个字段。
- 列表渲染 key 用稳定 id，不用数组下标。
- 状态最小化：能从 props/已有状态推导的值不放 state。

## 状态与数据

- 服务端数据与 UI 状态分开管理（请求缓存层 vs 本地 state）。
- 全局状态克制：跨页面共享才上全局，其余用组件树内传递。
- 请求三态必须处理：loading / error / empty，禁止只写 happy path。

## 性能

- 先测量再优化：React DevTools Profiler 确认重渲染热点。
- 大列表虚拟化；路由级代码分割（lazy + Suspense）。
- 昂贵计算 useMemo、回调稳定 useCallback——仅在有测量证据时使用。

## 安全与可访问性

- 禁止 `dangerouslySetInnerHTML` / `innerHTML =` 注入未消毒内容（审计 High）。
- token 不放 localStorage 长存敏感凭据，优先 HttpOnly Cookie。
- 交互元素用语义标签（button/a），表单控件有 label，图片有 alt。
