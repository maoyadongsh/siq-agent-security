# Windows 修复候选签名交接

当前签发交接候选已更新为 `d9ad885f2f894dce3f7c9dd036130df7bb436e2a`（Windows Hermes 请求预算修复）。四目标仍为干净构建、嵌入版本 `0.0.0-dev`，正式发行须由维护者选择批准版本重建并签发。当前归档 `windows-unsigned-candidate-d9ad885-reviewed.zip`，SHA256 `7da0db60c367b5c1125331ccdd25e88f90ca867140d08ebe7d81f3c28afd6ada`；见 [新摘要](evidence/personal-experience/windows-sunbo/hermes-skill-budget-20260919/unsigned-candidate.json)。下方旧候选摘要保留为历史，不用于本次签发。

2026-09-19 03 时当前交接源码为 `eac2a99089e8d17a752bd6159ce15dcdf9b9c2b8`，包含安装后会话绑定界面、在线 SEC 安装读取接线及长路径诊断修复。四目标干净开发构建位于 `.tmp/windows-goal-20260916/windows-unsigned-candidate-eac2a99/`；归档为 `windows-unsigned-candidate-eac2a99-reviewed.zip`，SHA256 `973a669ad110ee4540f766b1ba0572b82b7d573b97b7659ba0780db73abcd4bd`，66,029,577 字节。见 [当前候选记录](evidence/personal-experience/windows-sunbo/skill-session-management-20260919/unsigned-candidate.json)。

嵌入版本仍为 `0.0.0-dev`，维护者必须从此固定源码按批准正式版本重建四目标并记录新摘要后签发，不能直接将开发包标为正式发行。Skill 载荷经源码差异与逐文件摘要确认和 2d5ee6c 相同，旧正式清单、签名及信任根未改。2d5ee6c 的归档和宿主证据保留为历史，不作为当前二进制实测。下方 ff16606/candidate.1 步骤仍是历史准备记录，当前源码与摘要以本段为准。

本材料关联 PR #83、Issue #87。仅准备未签名候选，不授权签发、发布、合并或更换信任根。

## 固定输入

实现提交：`ff16606`（WorkBuddy 修复入口恢复同步、完整匹配的产品钩子，保留用户钩子，去除已确认产品重复项）。后续仅测试与说明提交不改变二进制源码。

本机候选目录：`.tmp/windows-goal-20260916/windows-unsigned-candidate-ff16606/`，包含 `bin/` 四目标二进制、`skills/siq-agent-security/` 当前 Skill、`SOURCE-INFO.json` 源码与逐文件 SHA256。交接压缩包单独生成，不提交二进制到 Git。

候选版本：`0.2.1-windows-candidate.1`，只是本轮构建身份，尚非批准发行版本。维护者若选择其他版本，必须以相同源码重新构建全部二进制并重新计算摘要，不只改清单版本文字。仓库旧 v0.2.0 清单保持原样；暂存 Skill 不包含旧清单，避免把不匹配的旧签名随候选交付。

## 可复现准备

使用干净的固定提交、Go 工具链及新输出目录。四个目标为 windows/amd64、linux/amd64、linux/arm64、darwin/arm64。各目标的构建命令为：

```powershell
$env:CGO_ENABLED = '0'
# 为每个目标设置 GOOS 与 GOARCH，并将文件名换为对应目标。
go build -C apps/agentshield -trimpath -ldflags '-s -w -X main.Version=0.2.1-windows-candidate.1' -o '<交接目录>/bin/siq-agent-security-windows-amd64.exe' ./cmd/agentshield
```

Linux/macOS 文件不加 `.exe`。Skill 应取固定提交的已跟踪文件，排除旧 `skill-manifest.json`；不要复制工作树的临时或未跟踪文件。构建结果必须与 `SOURCE-INFO.json` 核对，源码和字节有变化就创建新候选记录。

## 受授权维护者签发

维护者通过既有秘密管理流程向**签发子进程**提供 `SIQ_AGENT_SECURITY_RELEASE_SEED`，不得把种子写入此文档、命令历史或产物。本轮没有读取或使用该秘密。

在已审阅的交接目录中执行下列命令；`$approvedURLBase` 必须是维护者批准的新版本下载前缀，不能沿用 v0.2.0 地址。以下命令会创建新候选清单，不修改仓库旧清单：

```powershell
$bin = Join-Path $candidate 'bin/siq-agent-security-windows-amd64.exe'
$skill = Join-Path $candidate 'skills/siq-agent-security'
$manifest = Join-Path $skill 'skill-manifest.json'
if (Test-Path -LiteralPath $manifest) { throw '目标清单已存在，停止以免覆盖' }
& $bin release-manifest --skill-dir $skill --bin-dir (Join-Path $candidate 'bin') --version '0.2.1-windows-candidate.1' --url-base $approvedURLBase --client-compatible --out $manifest
if ($LASTEXITCODE -ne 0) { throw '签发失败，保留现场' }
& $bin manifest-verify $manifest
if ($LASTEXITCODE -ne 0) { throw '既有发行信任根或内容验证失败，禁止发布' }
```

不使用 `--write-bootstrap`。签发命令可能只警告密钥与内置信任根不一致，因此后续 `manifest-verify` 是必须通过的门槛，不能把命令创建了文件当作验签通过。

随后逐一核对清单内每个二进制的文件名、SHA256、size 与交接记录，并以仓库既有 Go/Python 验证器检查 Skill/清单/引导下载链路。维护者将**新版本的完整包与相符清单**纳入最终整合候选后，复跑 Issue #87 的三个失败测试及两个 CI job。不能只把旧清单中的哈希替换成新值。

## 仍未完成

本轮没有正式签名、正式下载地址或发行。旧清单与当前 Skill 的不一致仍是实际 CI 阻塞；交接材料不等于解除阻塞。三宿主真实保护闭环的验收也不由发行验签替代。
