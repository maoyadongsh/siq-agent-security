# R04-D Hermes 清单修复后的最终候选复验

- 日期：2026-09-14
- Git 基线：`b303c6f92392f3a44c306d81ad7323c6291ef4f2`
- 未提交候选 SHA256：`f4b5c23cfff4f89608b1e113b36858c2938d6f8e06630b6e9031c7665c77420c`
- 构建输入：当前存在的 1225 个 `apps/agentshield`/`apps/web` 已跟踪或未忽略文件，逐文件 SHA256 清单组合摘要 `16edba83b0a4bb629cff680f7ff105cf19db05fa209f930fa0983bb1e94d98fa`
- 状态：本机复验通过；未提交、未推送、未合并、未发布

## 变更原因

真实 Hermes 0.21.0 Plugin Doctor 首次运行发现，适配器注册了 `pre_tool_call` 与 `post_tool_call`，但旧 `plugin.yaml` 只含兼容字段 `hooks`，没有当前运行时校验的 `provides_hooks`，因此产生两条警告。本批在源适配器和 Go 内嵌资产中同步声明两个 `provides_hooks`，保留旧 `hooks` 字段兼容较早宿主，并增加镜像一致性与声明回归断言。

修复后真实 `hermes plugins doctor ... --ci` 返回：runtime discovery、manifest parsing、import、registration 全部 OK，0 tools、2 hooks，无警告。

## 最终候选回归

- R01 SEC 本地服务级活体：[最终证据](../r01-skill-context-final-20260914-2110/report.md) 57/57 通过。
- 更新事务 runner：7/7 通过。
- 会话、发现与适配器 runner：30/30 通过，使用真实 Hermes CLI 对隔离 `work` profile 启用、诊断和卸载，保留默认 profile、未知文件及用户后续配置。
- 证据均绑定 SHA256 `f4b5c23c…7420c` 的同一候选。

## 边界

本批没有启动模型或执行宿主工具调用；Hermes 证据到达真实清单解析、插件导入/注册和隔离 profile 配置生命周期，R01/R02 的工具调用与重试门槛仍为 partial。公网来源、WorkBuddy、Windows/macOS 也没有因此关闭。

