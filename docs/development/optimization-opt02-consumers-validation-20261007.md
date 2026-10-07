# OPT-02 身份边界消费者回归

日期：2026-10-07。分支：`codex/security-optimization-20261007`。本记录补充[首批验证](optimization-opt01-opt02-validation-20261007.md)，不替换历史结果。

## 变化与原因

生产构建关闭开发身份后，进一步发现会话恢复和 AuthGate 仍分别解释开发开关，历史浏览器脚本也依赖构建产物注入身份。现统一使用 `DEV && !PROD && VITE_DEV_MODE === 'true'`；环境示例默认 false。所有 build 路径仍拒绝 true，没有为测试放宽生产保护。

30 组现有浏览器夹具改为：构建时 false、隔离环境目录、同源 API；测试层只在 loopback 精确刷新端点提供合成会话。真实开发 API 脚本显式注入本夹具身份，故障注入的 `route.fetch` 同样携带指定身份。只读测试保持真实后端拒绝，恢复身份时只移除自己的拦截器。移动页独立安装测试会话。合成会话不进入产品包、不连接生产 IAM。

## 验证

| 范围 | 结果 | 本地原始记录（忽略目录） |
| --- | --- | --- |
| 前端全量 | 1,031 项通过；会话恢复新增生产/开发对照 | `var/optimization-20261007/opt02-web-all-followup.log` |
| 构建与开发身份防误配置 | 两类构建通过；显式 true 拒绝见首批记录 | 同目录构建日志、首批记录 |
| 浏览器主套件 | 首轮 28/30，通过后定位两项夹具残留 | `browser-fixture-migration-full-001/result.json` |
| 两项修复复跑 | candidate-review、four-entry-navigation 均通过；2/2 | `browser-fixture-migration-repair-001/result.json` |
| 浏览器聚焦先行验证 | overview、audit、workspace、business 四组通过 | `browser-fixture-migration-002/result.json` |
| 套件编排与会话边界 | 编排 21 项、会话边界 3 项通过 | `opt02-browser-runner-unit.log`；unittest 终端记录 |

以上相对记录路径均位于 `var/optimization-20261007/`。30 个脚本均有通过记录：28 个来自全套首轮，2 个来自修复复跑；不把两轮拼成一次全量通过。首轮失败、定位和修复日志保留。

消费者回归覆盖真实页面、375px 移动布局、候选权限与审批失败恢复；其中使用真实隔离 API/原生 Edge 的脚本仍是开发身份、合成数据。生产身份验证证据仍以首批 OIDC/JWKS 正负向测试为准，不把浏览器合成会话当作生产登录证明。
