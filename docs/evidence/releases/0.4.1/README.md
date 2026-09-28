# SIQ Agent Security 0.4.1 正式发行

2026-09-28，按用户明确授权公开为[正式版并设为 Latest](https://github.com/maoyadongsh/siq-agent-security/releases/tag/siq-agent-security-v0.4.1)。固定源码 `a620a31b1dccdc7d2061e97ed4378c574321860d` 已通过 [PR #111](https://github.com/maoyadongsh/siq-agent-security/pull/111) 合入 main；重新构建并签发新版本，不重标或覆盖 0.4.1-rc.1 与 0.4.0。正式发行不表示真实 WorkBuddy 新批次验收已完成。

## 来源与签发

沿用既有 publisher Ed25519 身份与产品内置公钥，入口为 `scripts/release/package.py --sign`。在内存中核对私钥派生公钥等于固定信任根，密钥只进入签名子进程，不进入附件、日志或构建进程；没有建立新的信任根。签名准备见 [preparation.json](preparation.json)，版本、Go 1.26.6 工具身份和内容摘要见 [SOURCE-INFO.json](SOURCE-INFO.json)。

独立评审的 2,062 文件清单 SHA-256 为 `cbc252859abf797314fe2ed39d7bbac38189026378bb82f19a62d9b5c0285403`；导出源码与清单一致，锁定依赖重建的 Web 资源与提交 embed 一致。当前 main `67dc69c8eff87d6baac3076f333d95fc3ee89663` 与该源码的产品路径一致，后续文档同步不进入已冻结制品。源码元数据是描述性记录；publisher 签名绑定 Skill 内容和四目标二进制 pin，不额外构成源码构建证明。

## 实际检查

| 检查 | 结果与记录 |
| --- | --- |
| Windows 源码原生 CI | [36379619929](https://github.com/maoyadongsh/siq-agent-security/actions/runs/36379619929)：候选全量退出 0、55 包；67 条条件/平台 skip 不计通过，POSIX 专属未运行项另列 |
| Linux 源码复核 | 同一 a620a31b 的 Go 全量、vet、gofmt 和 adapterinstall/inventory/decisionrelay race 退出 0；沿用 [RC 评审记录](../0.4.1-rc.1/README.md)，不计为新独立环境 |
| 新版本构建签发 | `sign-reviewed-candidate.py` 调用 `package.py --sign`，退出 0；Linux amd64/arm64、macOS arm64、Windows amd64 |
| 独立包验证 | `verify.py --version 0.4.1 --source-sha a620a31b1dccdc7d2061e97ed4378c574321860d --native-smoke` 退出 0；[官方签名、实际 Skill、四 pin、八资产、安装文本和包内一致性](verification.json)通过 |
| Linux ARM64 最终包 | 同一验证命令执行临时全新状态 start/status/pair/控制台/stop，全部通过；不注册系统服务或宿主 |
| 篡改拒绝 | [正常对照退出 0；Skill、二进制、错误公钥各退出 3](tamper-rejection.json)，均在暂存前拒绝；只修改临时副本 |
| 公开下载 | `readback.py --version 0.4.1 --source-sha a620a31b1dccdc7d2061e97ed4378c574321860d` 退出 0；[publication.json](publication.json)：八附件逐字节一致、官方验签、匿名校验清单及签名 URL 下载/暂存通过，prerelease=false、is_latest=true |
| 历史资产 | [preserved-releases.json](preserved-releases.json)：0.4.0 / 0.4.1-rc.1 的发布记录与八附件 ID、大小、摘要、更新时间均未改变 |

## 安装与接续

下载[0.4.1 完整离线包](https://github.com/maoyadongsh/siq-agent-security/releases/download/siq-agent-security-v0.4.1/siq-agent-security-0.4.1-bundle.zip)，按包内 INSTALL.md 用固定官方公钥核验实际 Skill 和对应平台程序。完整包 SHA-256：`190dd5d3f07020014f98eabe6637e43ecb7e7980437b8deb793b4230e89822c4`；Windows EXE：`a334b2993727c98a9d14c14d472d49217448945112acf38425884f9b6c1a20a6`。其余传输摘要见 [SHA256SUMS](SHA256SUMS)，不能用校验和替代签名。

```powershell
gh release download siq-agent-security-v0.4.1 --repo maoyadongsh/siq-agent-security --dir .\siq-0.4.1-assets
```

在专用实例继续 Windows 正式包新装、升级、回滚及真实 WorkBuddy N、R/W/T、J、F 新批次。保留原 Grant、身份、失败记录与旧批次，迁移前检查 reader/writer 和 Windows profile 兼容性。不得用旧程序覆盖不兼容的新状态，回滚不能复活撤销身份或恢复旧授权。

本轮没有执行上述 Windows 正式包与 WorkBuddy 业务矩阵，也没有完成 Authenticode 或 Apple 公证；没有扩大 Grant、自动续期或重放 uncertain。既有成功仅证明各记录范围，产品链路全部修复仍须原生验收。
