# 支持范围与证据等级

核查对象：0.3.1 / `f3d9c3f`，日期 2026-09-19。本表是[实际证据](../docs/evidence/releases/0.3.1/README.md)与[产品范围](../docs/personal-platform-scope-decision-20260917.md)的导航摘要，不是新的运行时合同。签名包中的 `support_matrix` 和源码默认矩阵仍没有 `supported` 行。

| OS / 架构 | 当前宿主范围 | 本版构建/验签 | 本版原生安装链路 | 同候选完整宿主/升级验收 |
| --- | --- | --- | --- | --- |
| Linux arm64 | OpenClaw、Hermes | 已验证 | 已验证首次空状态启动、配对、控制台、停止；不等于全部后台安装场景 | 未完成 |
| Linux amd64 | OpenClaw、Hermes | 已验证 | 未运行 | 未完成 |
| macOS arm64 | OpenClaw、Hermes、WorkBuddy | 已验证 | 未运行 | 未完成；Apple 签名/公证另记 |
| Windows amd64 | OpenClaw、Hermes、WorkBuddy | 已验证 | 未运行 | 未完成；WSL Agent 与原生 CLI 证据不同 |

Linux/WorkBuddy 不新增接入，已有 WorkBuddy 配置可查看或卸载。未知目标不得从邻近行推断支持。项目 Ed25519 清单签名不代表 Apple 公证或 Windows Authenticode。

配置、读回、加载与行为拦截分别验收；L0/L1/L2/L3 能力也不与源码已合并或 GitHub Release 类型互换。[历史平台库存](../docs/personal-platform-validation-spec-v1.md)保留原 18 项范围，当前产品验收使用既有 N09 v2 机制而非删掉历史失败行。
