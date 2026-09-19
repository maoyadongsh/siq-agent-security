# 0.3.0-rc.1 签发与本机验证（2026-09-19）

已使用与产品内置信任根匹配的现有发行密钥，签发当前集成主线 `58ab22e882452116444eb00e47e14cecdf98772a` 对应的候选安装包。以下签发记录保留本地验证时的状态；发布后的独立回读结果见文末。不代表稳定版或四平台完整验收通过。

## 候选身份

- 版本：`0.3.0-rc.1`；预留 tag：`siq-agent-security-v0.3.0-rc.1`，必须指向上述源码提交。
- 本机制品目录：仓库根下 `.tmp/releases/0.3.0-rc.1-final/`。
- 完整离线包：`siq-agent-security-0.3.0-rc.1-bundle.zip`。
- 包 SHA-256：`8798594a13f2acb70343d3b4292006e974baf207955ec8aa737203cec62a9b14`。
- [SOURCE-INFO.json](SOURCE-INFO.json) 记录固定源码、打包工具摘要、实际工具链、自扫描结果与包内文件摘要；[SHA256SUMS](SHA256SUMS) 对应最终发行资产。
- 打包工具在这次签发后单独提交；产品源码取自上述已通过主线 CI 的提交，工具身份由 `packaging_tool_sha256` 固定。未包含工作区未提交的产品开发文件。

发行签名覆盖实际 Skill 内容与四目标二进制摘要。`SOURCE-INFO.json`、此验证报告及校验和是描述性证据，本身没有独立发行者签名。main 的 Skill 源码不复制回发行清单；历史 0.2.0 样本保持不变。

## 验证结果

[verification.json](verification.json) 记录最终压缩包的 13 项检查：

1. 使用仓库受信公钥，由 Python 独立校验发行签名、实际 Skill 和本机二进制，验证后才执行程序。
2. 修改 Skill、修改二进制、修改签名清单、错误受信公钥、缺少清单、旧清单授权新 Skill，六条负向均拒绝。
3. Go 内置信任根验签、本机程序版本和所有发行资产校验和均通过。
4. Linux ARM64 解压包在隔离状态目录与随机 loopback 端口通过真实 bootstrap、健康检查、内嵌控制台 HTTP 200 和正常停止；测试服务已退出。

构建同时通过隔离 UI 重建与仓库 embed 一致性检查、四目标交叉编译、Skill 自扫描 `admit_with_conditions`。发行资产文本通过仓库配置的 gitleaks 扫描；所有资产及解压条目另做原发行种子的原始字节、base64、hex 排除检查，均未发现私钥材料。原始运行日志与状态留在私有临时目录，不进入 Git 或发行包。

## 发行范围

Linux amd64、macOS arm64、Windows amd64 的二进制已构建并纳入签名；本次没有这些目标的原生安装、升级或三宿主验收结果。Linux ARM64 本次只验证包安装链路，不把历史宿主/OpenShell/性能结果迁移为同候选全量验收。项目发行签名不等于 Apple 公证或 Windows Authenticode。

发布时上传完整包、Skill ZIP、四个原始二进制、`SOURCE-INFO.json` 和 `SHA256SUMS`，不覆盖已有版本；上传后下载回读并重新验签。包内元数据的 `published: false` 是打包时事实，不为发布而重打已验签的包。发布结果应另记回读记录。安装步骤见[签名包操作说明](../../../signed-release-packaging.md)。

## 已发布及回读结果

用户明确授权后，已公开为 [0.3.0-rc.1 预发布版](https://github.com/maoyadongsh/siq-agent-security/releases/tag/siq-agent-security-v0.3.0-rc.1)，未替换稳定版 latest。实际 tag 仍指向 `58ab22e882452116444eb00e47e14cecdf98772a`。八个资产全部重新下载，与本地已验签候选逐字节摘要一致；独立 Skill ZIP 再次通过官方根、Skill 内容与本机二进制验证，四目标 pin 均匹配。公网未认证校验和下载也通过；独立验证器还按签名 URL 下载 Linux ARM64 二进制，完成摘要验证与私有可执行暂存。详细结果见 [publication.json](publication.json)。
