# 0.3.0 正式版本签发与验证（2026-09-19）

用户明确要求正式发布。版本为 `0.3.0`，源码固定为 `83fde2df0bcfc817d85568978e3881e22474815e`，标签 `siq-agent-security-v0.3.0`。[GitHub Release](https://github.com/maoyadongsh/siq-agent-security/releases/tag/siq-agent-security-v0.3.0) 已使用普通发布类型并设为 Latest；发布结果单独记录，不变更 0.3.0-rc.1 的历史身份或验收事实。

## 内容与身份

产品功能源码与 `58ab22e` 相同（`apps/agentshield`、`apps/web`、`skills/siq-agent-security` 逐路径 Git diff 无差异），发行时更新 Skill 暂存版本和二进制版本。新打包工具已在本源码提交内，`INSTALL.md` 补齐先验签、再由已验证程序初始化启动的步骤。

完整包：`siq-agent-security-0.3.0-bundle.zip`，SHA-256 `6132d68fa97b6b01fba36355a0636650cb1180cb0d703e0b48a4fcafd8d4211e`。发布目录同时包含 Skill ZIP、四个原始程序及元数据。见 [SOURCE-INFO.json](SOURCE-INFO.json) 和 [SHA256SUMS](SHA256SUMS)。原发行种子仅注入签名子进程，不更换信任根，未写入任何制品。

## 验证

[verification.json](verification.json) 记录最终包的 **14/14** 检查：原发行根验签、实际内容与程序 pin、六条负向、Go 验签、版本和资产摘要、Linux ARM64 bootstrap/控制台/退出，以及执行包内 INSTALL.md 的空状态初始化、身份状态、配对、控制台和停止。测试状态与原始日志保留在私有临时目录，不进入 Git 或发行资产。

构建同时检查隔离重建的 UI 与提交 embed 一致，Skill 自扫描为 `admit_with_conditions`，四目标程序齐全。gitleaks 文本扫描通过；全部发行资产与解压条目排除了原发行种子的原始字节、base64 和 hex 表示。打包边界 8 项单测、Ruff 和 whitespace 检查通过。

[publication.json](publication.json) 记录已发布状态（`prerelease: false`、`is_latest: true`）、标签源码及 **8/8** 远端资产摘要回读一致。回读后再次通过官方根、Skill 内容与四目标 pin 验证，并验证匿名校验和下载及 Linux ARM64 签名 URL 下载与暂存。

[source-ci.json](source-ci.json) 记录发行源码 `83fde2d` 的五条工作流均成功：ci、research、runtime-security、personal-experience、sonarcloud。源码 CI 与发行资产安装验证分别记录。

## 平台与发行范围

正式 Release 类型不替代平台验收。Linux ARM64 本次验证的是上述安装链路；Linux amd64、macOS arm64、Windows amd64 仅完成构建和签名摘要核对，平台实验性状态保持不变。全部目标的新版本升级/回滚、完整宿主验收、Apple 公证/Windows Authenticode 和性能门仍按各自证据记录，不把旧候选结果迁移为本版全量通过。

安装见[操作指南](../../../signed-release-packaging.md)。`SOURCE-INFO.json` / 初始验签报告中的 `published: false` 是打包与本地验证时事实；发布结果见独立的 [publication.json](publication.json)，不修改已验签压缩包。
