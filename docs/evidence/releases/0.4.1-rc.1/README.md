# SIQ Agent Security 0.4.1-rc.1 签名候选

2026-09-28，按用户要求合并并签发 Windows WorkBuddy 修复。源码固定为 `a620a31b1dccdc7d2061e97ed4378c574321860d`；[PR #111](https://github.com/maoyadongsh/siq-agent-security/pull/111) 的合并提交为 `3f0f9b585628cae07347ab9e9c50af8e9ecde0dc`，代码树相同。main 保护规则保持不变。当前为 GitHub 草稿候选，公开 Latest 仍为 0.4.0；签名不代表真实 WorkBuddy 新批次验收完成。

## 签发与校验

沿用本机现有 publisher Ed25519 身份。种子文件以不跟随链接的方式读取，核对当前 owner、0600、单链接和祖先写入主体，再在内存中派生公钥与产品固定信任根比对。种子只注入签名流程，不进入命令参数、日志、构建子进程或附件。未修改密钥、信任根或 0.4.0 制品。

实际入口是仓库 `scripts/release/package.py --sign`；`.github/workflows/release-signing.yml` 仅签署研究源码校验清单，不是客户端 publisher 签发入口。维护者只需从既有受控存储向打包进程注入 `SIQ_AGENT_SECURITY_RELEASE_SEED`，无需向 Windows 端传递私钥。

独立复核的 2,062 文件清单摘要为 `cbc252859abf797314fe2ed39d7bbac38189026378bb82f19a62d9b5c0285403`。固定源码导出核对通过；锁定依赖的本地 UI 重建与提交 embed 一致。构建工具链为 Go 1.26.6，四目标从同一源码构建；版本、工具身份与逐文件摘要见 [SOURCE-INFO](SOURCE-INFO.json)。源码身份元数据不是额外的签名构建证明，publisher 签名绑定 Skill 与四目标二进制 pin。

| 检查 | 实际结果 |
| --- | --- |
| [Windows 原生组件 CI](https://github.com/maoyadongsh/siq-agent-security/actions/runs/36379619929) | 候选全量退出 0，55 包，67 条条件/平台 skip 不计通过；未运行 POSIX 专属测试另列 |
| Linux 源码复核 | `go test -count=1 -timeout 10m ./...`、`go vet ./...`、gofmt 均退出 0；adapterinstall/inventory/decisionrelay race 退出 0 |
| [最终签名包](verification.json) | 官方根、实际 Skill、四目标 pin、八资产与包/单文件一致性、安装说明均通过 |
| Linux ARM64 原生最终包 | 全新状态 start/status/pair/控制台/stop 通过；不注册系统服务或宿主 |
| [篡改拒绝](tamper-rejection.json) | 正常对照退出 0；Skill、二进制、错误公钥三项退出 3，拒绝暂存；工具探针错误保留 |
| [草稿下载回读](draft-readback.json) | 八附件与本机候选逐字节一致，再次独立验签通过；不等于匿名公开下载 |

## Windows 接续

有仓库权限的维护者可下载草稿的完整离线包。源码与候选版本分别为 `a620a31b` / `0.4.1-rc.1`。按包内 INSTALL.md 使用固定官方公钥验证实际 Skill 和 Windows 程序后，在专用实例继续新批次。草稿未公开时不要使用 Skill-only 的下载 URL。

```powershell
gh release download siq-agent-security-v0.4.1-rc.1 --repo maoyadongsh/siq-agent-security --dir .\siq-0.4.1-rc.1-assets
```

完整 ZIP SHA-256：`ed3983591a3b68d49aa41b6013f41fe5b56b4db09e7a5878743998a2e83c177d`。校验和用于传输核对，不能代替官方签名校验。

本轮未运行 Windows 正式包安装/升级/回滚及真实 WorkBuddy N、R/W/T、J、F 新批次，未完成 Authenticode 或 Apple 公证。没有扩大 Grant、自动续期、重放 uncertain 或改写历史批次。代码和签名候选已交付，产品修复完成仍取决于原生验收。
