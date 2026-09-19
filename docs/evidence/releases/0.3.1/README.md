# SIQ Agent Security 0.3.1 正式发布记录

用户明确要求发布 **SIQ Agent Security 0.3.1 正式版**。固定源码为 `f3d9c3f0933f3b08d15b2d3dbc522f409c77a355`，标签为 `siq-agent-security-v0.3.1`。[GitHub Release](https://github.com/maoyadongsh/siq-agent-security/releases/tag/siq-agent-security-v0.3.1)已公开，`prerelease: false`，发布回读确认 Latest。

## 内容与身份

相对 0.3.0，包内 Skill 指引更新首次启动、配对、人工审批、Writer 锁和平台范围；源码仓库更新研究组织、模块 README、流程图与发行验证工具。产品运行时、Web 功能、适配器实现及合同没有变化。新包重新构建并由原发行信任根签名；未覆盖 0.3.0 或历史 RC 的资产、签名和证据。

包提供完整离线 ZIP、签名 Skill ZIP、四目标二进制、SOURCE-INFO 与 SHA256SUMS，共八份附件。GitHub 自动生成的源码归档仍不等于签名安装包。发行后的文档回执和图表样式调整不改变此固定源码身份。

## 实际验证

| 检查 | 本次结果与边界 |
| --- | --- |
| [固定源码 CI](source-ci.json) | 6/6 工作流成功：ci、runtime-security、research、personal-experience、sonarcloud、pages；工作流数量不是测试项数 |
| [最终包验证](verification.json) | 八资产清单/校验和、官方根签名、Skill 实际内容、四目标 pin、包内外一致性、许可与可信安装说明均通过 |
| Linux ARM64 原生链路 | 执行最终包 INSTALL 的验签与 start，在全新私密状态验证 status、pair、控制台 HTTP 与正常 stop；不注册系统服务或宿主 |
| [篡改拒绝](tamper-rejection.json) | 3/3：修改 Skill、错误发行公钥、修改二进制均拒绝，未暂存不可信程序；不执行修改后的内容 |
| [公开回读](publication.json) | 8/8 附件下载与已验本地包逐字节一致；复验官方签名、四目标 pin、匿名校验和下载与 Linux ARM64 签名 URL 下载/暂存 |

本次未验证另外三个目标的原生安装、所有 OS 升级回滚、系统服务、通知和完整宿主旅程；项目签名不等于 Apple 公证或 Authenticode。历史四目标源码检查与宿主记录继续绑定各自候选，不迁移为本版验收。

## 使用与追溯

安装见[签名包指南](../../../signed-release-packaging.md)，支持见[平台矩阵](../../../../platforms/support-matrix.md)。[SOURCE-INFO.json](SOURCE-INFO.json)记录隔离构建身份、工具链与资产摘要；其中 `published: false` 是构建时事实，发布状态由独立回读记录证明。校验和与源码描述不是额外发行者签名，官方清单签名覆盖实际 Skill 内容和四目标二进制 pin。

打包前重建本地 UI 并确认与提交的 embed 完全一致；15 项发行工具单测通过。密钥仅在本机签名进程使用，未复制到公开资产或报告；临时状态、配对输出和程序日志不公开。
