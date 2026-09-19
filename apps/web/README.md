# Web 控制台开发与构建

同一 React/TypeScript 源码树提供个人与企业两种应用。个人控制台嵌入 Go 客户端，管理本机 Agent、Skill、授权、任务与隐私；企业控制台连接 Control API，管理租户环境、资产、风险、策略和审计。两者具有独立入口与身份上下文。

## 选择构建模式

| 模式 | 开发 / 构建 | 后端与输出 |
| --- | --- | --- |
| 企业 | `npm run dev` / `npm run build` | Control API；输出 `apps/web/dist/` |
| 本地个人 | `npm run dev:local` / `npm run build:local` | loopback Go daemon；输出 `apps/agentshield/internal/ui/embedded/` |

从仓库根进入 `apps/web`，使用锁文件安装依赖：

```bash
cd apps/web
npm ci
npm test
npm run build
npm run build:local
```

Windows PowerShell 可将 `npm` 写为 `npm.cmd`，无需修改 ExecutionPolicy。本地入口通过 Node 设置当前进程的 `VITE_APP=agentshield` 并调用锁定的 Vite，不依赖全局 Vite 或 POSIX 环境变量语法。两种构建均先运行 TypeScript 检查。

`dev:local` 默认监听 `127.0.0.1`、打开 `/overview`，并以本地应用处理 `/`、`/demo` 等 SPA 路由；附加参数示例为 `npm run dev:local -- --port 5174 --strictPort`。开发代理把 `/v1`、`/healthz`、`/ui-config.json` 发往 `127.0.0.1:47611`，需另行启动、配对该 daemon。端口与 Origin 处理见 [localProxy](dev/localProxy.ts)，不要通过删除服务端来源检查解决连接问题。

企业开发代理目标见 [Vite 配置](vite.config.ts)：Control API 默认 `127.0.0.1:8600`，开发 IAM 路由默认 `127.0.0.1:10088`；真实部署按[企业说明](../../docs/control-plane.md)配置，不能将开发身份带入生产。

## 交互与事实边界

| 本地功能 | 展示/操作 | 必须遵守的含义 |
| --- | --- | --- |
| 资产与宿主 | 发现、实例管理、接入预览、诊断 | 已发现、已配置、已加载、运行验证分别显示 |
| Skill 生命周期 | 导入检查、权限准备、安装、更新、移除与恢复 | 准入不授予权限；安装成功不证明运行受保护；未知用户文件保留 |
| 授权与确认 | 权限草稿、人工批准、会话与逐次审批 | 批准不等于执行；reserved/completed/uncertain 来自服务端签名记录 |
| 任务与结果 | 活动、来源、执行、回执、效果与完成状态 | 工具返回成功、签名观察和实际完成不能合并成一个“成功”标签 |
| 隐私与导出 | 按需原文授权、检查与任务导出 | 原文默认关闭；敏感来源路径与 token 不写 URL 或 Web Storage |

个人端入口在 [src/local](src/local/)，路由见 [App.tsx](src/local/App.tsx)，请求封装见 [api.ts](src/local/api.ts)。界面消费服务端事实，不生成签名、推断有效权限或把预览自动变成批准。通知只提示待办并打开详情，不能代替操作者确认。原文辅助采集失败不伪造内容，也不改变工具裁决。

## 开发验证与交付

Vitest 覆盖请求、状态投影和权限/效果相关逻辑；真实浏览器与宿主旅程另见[测评索引](../../evaluations/README.md)。开发页面可访问不等于配对、授权或宿主已验收。

`build:local` 会更新受版本控制的嵌入资产。应复核源码与资产差异，然后固定候选并构建 Go；仅重新编译 Go 不会自动重建 React。嵌入层的使用与边界见 [internal/ui](../agentshield/internal/ui/README.md)。测试和构建命令在此供开发者使用，本轮文档更新本身不产生新的平台验收结果。
