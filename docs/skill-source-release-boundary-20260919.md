# Windows 开发成果合入与 Skill 发行边界（2026-09-19）

## 决策

源码开发、合并和正式发行分别验收。Windows junction 修复属于源码安全修复，可以完成测试后合入 main；发行私钥不再是普通开发 PR 的前提。正式安装包仍必须通过原有签名、Skill 内容摘要、平台二进制摘要与安全暂存检查。

此前 #83 为保持旧 `skill-manifest.json` 与目录摘要一致，将 Python junction 修复及三个 Go 回归文件暂放 #90。该处理保护了发行验证，但耦合了源码和旧发行包。本次用完整历史签名样本保留验证能力，并合入这四个文件；不伪造签名，不跳过失败测试。

## 目录与职责

| 路径 | 职责 |
| --- | --- |
| `skills/siq-agent-security/` | 最新开发源码；不附带不匹配的旧清单。复制/发现 Skill 成功不等于签名安装成功。 |
| `apps/agentshield/testdata/releases/siq-agent-security-v0.2.0/` | 从 main `0c1817c1150fd8051998c3292a6659925684ad5d` 逐字节归档的 28 个文件；仅供历史兼容验签，禁止作为当前修复版发行。 |
| `internal/skillmanifest/*_test.go`（Go 模块内） | 官方根验证历史完整包；当前源码复制到临时目录，以测试密钥签名并验证正反路径。 |
| 外部发行暂存目录 | 承载当次实际源码、实际工件与新的正式签名清单；不使用历史摘要授权新代码。 |

历史快照的生产公钥、签名和内容均保持不变。临时测试密钥只用于 `t.TempDir()`，产品公钥、bootstrap 信任根、生产验证逻辑不改。Windows junction 不跟随外部目录，未知 reparse 类型仍拒绝。测试样本保留旧版行为，不代表应安装旧版。

## 如何使用和发布

开发者可在仓库根执行 `go build -C apps/agentshield -o ../../bin/siq-agent-security ./cmd/agentshield`（Windows 文件名加 `.exe`），再使用该本地构建的 CLI 开发调试。它是开发构建，不能冒充正式已签名发行。

从 main 复制的 Skill 源码不提供正式签名安装承诺。无 `skill-manifest.json` 时，shell 与 PowerShell bootstrap 明确拒绝启动；`allow-local` 也不跳过 Skill 签名和内容摘要检查。不能把历史清单复制回当前源码来“修复”安装，摘要不匹配应继续失败。

正式发行流程保持独立：

1. 冻结源码提交，复制当次 Skill 到隔离发行暂存目录，构建并保存四目标二进制。
2. 维护者在受控环境通过现有 env 机制提供正式签名种子，调用 `release-manifest --skill-dir <暂存目录> --bin-dir <工件目录> --version <新版本> --client-compatible`。不得把种子写进脚本、仓库或报告。
3. `manifest-verify <暂存目录>/skill-manifest.json` 验证官方签名与实际目录；`scripts/agentshield-release-check.sh --manifest <暂存目录>/skill-manifest.json --bin-dir <工件目录>` 对比实际二进制。该脚本只核对工件摘要与大小，不替代前一步验签。
4. 对签名包执行平台安装验证，再按发布授权分发整个包。本次合并不签发、不上传 Release，不把开发测试通过当成正式发行通过。

## 合并范围与未完成项

#80/#81/#82 的 Writer、迁移、DACL 修复和 #83 的 Windows 资源事实、宿主接入、客户端生命周期已经进入 main；#90 补齐 junction 验证器与 Go/Python 内容哈希回归。Windows OpenClaw 的 WSL Agent、Hermes 原生 CLI、WorkBuddy 原生最小读写证据按原报告保留，不扩大为所有运行模式均已验收。未推送的协作者工作不包含在本次合并中。#68 云开发环境继续排除。

旧报告的“待签名才能合并”是此前处理状态，本决策取代该源码合并限制；正式新发行签名仍待维护者单独完成。历史证据与已冻结比赛包不重写。

## 后续签发进展（2026-09-19）

上述“本次合并不签发”和“待维护者完成”描述的是源码合并时状态。随后依据用户要求，已从集成主线 `58ab22e` 用原发行密钥签发 `0.3.0-rc.1`，完整离线包及 Skill ZIP 通过官方根验证，Linux ARM64 最终解压包通过真实 bootstrap 和负向校验。现已按用户授权发布为 [GitHub 预发布版](https://github.com/maoyadongsh/siq-agent-security/releases/tag/siq-agent-security-v0.3.0-rc.1)，八个资产下载回读与本地候选一致并通过验签；其他目标原生安装与稳定版验收仍未完成。详见[签发证据](evidence/releases/0.3.0-rc.1/README.md)与[固定源码打包工具](signed-release-packaging.md)。此进展不改变 main 的开发源码身份，也不改写历史发行样本。
