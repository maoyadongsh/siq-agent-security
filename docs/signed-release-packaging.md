# 签名安装包的构建与验证

开发入口为 `main`；用户安装入口为经过签发的具体版本包。GitHub 自动生成的 Source code ZIP 和直接复制的 `skills/siq-agent-security/` 不含该版本签名清单，不能作为签名安装包使用。历史 `testdata/releases/` 只用于回归测试。

当前可下载版本：[0.3.1 正式版（Latest）](https://github.com/maoyadongsh/siq-agent-security/releases/tag/siq-agent-security-v0.3.1)。普通用户选择 `siq-agent-security-0.3.1-bundle.zip`，解压后按下文安装；维护者构建、签发步骤另列于下。该版 Linux ARM64 安装链路已验证，其他目标尚待原生验收，见[发行证据](evidence/releases/0.3.1/README.md)。

## 构建固定版本

在仓库根运行，`--source-sha` 必须是已审阅的完整提交 ID，版本示例不是自动发布承诺：

```bash
python3 scripts/release/package.py \
  --source-sha <40位已审阅提交ID> \
  --version 0.3.1 \
  --out-dir .tmp/releases/0.3.1-unsigned
```

工具从 Git 提交导出构建输入，不复制工作区未提交文件、私有状态或论文；只在临时目录安装锁定 Web 依赖、重建 UI 和构建二进制。重建 UI 与提交的 embed 有差异时失败，应先修正并审阅源码/生成物，不能在发行过程中默默替换候选身份。需要 Python 3.12+、Git、Node/npm 和支持本仓 Go 模块的工具链；输出记录实际工具版本。

输出包括明确标为 `unsigned-candidate` 的压缩包、四目标原始二进制、`SOURCE-INFO.json` 与 `SHA256SUMS`；没有可安装 Skill ZIP。四目标是 Linux amd64/arm64、macOS arm64、Windows amd64；不意味着四平台的安装和实际宿主能力已经完成验收。

## 使用现有发行密钥签发

通过已批准的本机秘密存储或 CI secret 将 `SIQ_AGENT_SECURITY_RELEASE_SEED` 提供给打包进程。不要将密钥写在命令参数、终端输出、报告或 Git 文件中。该变量只会传给签名子进程，不传给 npm、Go 构建或验证子进程。

对同一固定源码使用新的空输出目录：

```bash
python3 scripts/release/package.py \
  --source-sha <40位已审阅提交ID> \
  --version 0.3.1 \
  --out-dir .tmp/releases/0.3.1-signed \
  --sign
```

成功前必须通过现有 Go 内置信任根的验签、实际 Skill 内容校验和恰好四目标的摘要/大小/版本下载 URL 核对。错误密钥不会产出发行目录，工具不修改公钥或 bootstrap 信任根。它在暂存副本更新 SKILL frontmatter 的版本，并生成实际内容对应的 v3 client-compatible 清单，不修改 main 中的 Skill 或旧签名样本。

成功输出：

| 文件 | 用途 |
| --- | --- |
| `siq-agent-security-<版本>-bundle.zip` | 完整离线包：四目标二进制、Skill、签名清单、许可和 `INSTALL.md` |
| `siq-agent-security-skill-<版本>.zip` | 完整签名 Skill，可手动放入宿主 Skill 目录；下载二进制前仍须明确允许联网 |
| `siq-agent-security-<OS>-<架构>[.exe]` | 按原文件名作为 Release 资产上传，与清单下载 URL 对应；离线 ZIP 内位于 `bin/` |
| `SOURCE-INFO.json`、`SHA256SUMS` | 源提交、构建与文件摘要；元数据和校验和本身不是额外发行者签名 |

发行签名认证 Skill 内容和清单绑定的二进制；不把项目清单签名称为 Apple Developer ID、公证或 Windows Authenticode。首次平台安全提示、原生安装/升级及宿主能力的剩余门槛应在发行说明中保留。

## 用户从完整包安装

准备 Python 3（建议 3.12+）；Windows 示例使用已加入 PATH 的 `python`。把完整包解压到本人拥有的新目录，在该目录执行。首次体验使用独立状态目录，验签成功后再运行程序。

**0.3.1 包内 `INSTALL.md` 包含以下首次启动步骤，并通过 Linux ARM64 空状态实际验证。**

**历史 0.3.0-rc.1 首次启动说明更正：** 包内 `INSTALL.md` 省略了状态初始化步骤。当前 bootstrap 调用的是 `serve`；空状态目录会报 `configuration missing`，因此首次启动按下面的“验签 → `start` 初始化并启动 → 浏览器配对”操作。已发布压缩包的字节和签名保持不变。本次更正不增加其他平台的实机验收结论。

Linux/macOS 选择对应二进制；以下以 Linux arm64 为例：

```bash
chmod +x bin/siq-agent-security-linux-arm64
export SIQ_AGENT_SECURITY_BIN="$PWD/bin/siq-agent-security-linux-arm64"
export SIQ_AGENT_SECURITY_STATE_DIR="$PWD/state"
export SIQ_AGENT_SECURITY_STAGE_DIR="$PWD/.verified-bin"
export SIQ_AGENT_SECURITY_REQUIRE_PINNED=1
VERIFIED_BIN="$(sh skills/siq-agent-security/scripts/resolve_verified_bin.sh)" &&
  "$VERIFIED_BIN" start --port 47611
```

resolver 先验证官方签名、实际 Skill 内容及选中程序的摘要，再返回私有暂存路径。只有验签成功才执行 `start`；它初始化状态并在前台提供服务。Linux amd64/macOS arm64 请替换第一、二行中的二进制文件名。

Windows PowerShell（签名公钥是已固定的发行信任根，不从待验清单读取）：

```powershell
$ErrorActionPreference = 'Stop'
$env:SIQ_AGENT_SECURITY_BIN = (Resolve-Path '.\bin\siq-agent-security-windows-amd64.exe').Path
$env:SIQ_AGENT_SECURITY_STATE_DIR = Join-Path (Get-Location).Path 'state'
$env:SIQ_AGENT_SECURITY_STAGE_DIR = Join-Path (Get-Location).Path '.verified-bin'
$VerifiedBin = & python '.\skills\siq-agent-security\scripts\verify_manifest.py' `
  --manifest '.\skills\siq-agent-security\skill-manifest.json' `
  --pubkey 'LtEknKeTxzUQwErXI0MboUQQXKqrGp+R2x2RUv9/ZHY=' `
  --skill-dir '.\skills\siq-agent-security' `
  --bin $env:SIQ_AGENT_SECURITY_BIN --stage-to $env:SIQ_AGENT_SECURITY_STAGE_DIR
if ($LASTEXITCODE -ne 0 -or -not $VerifiedBin) { throw 'Package verification failed' }
& "$VerifiedBin" start --port 47611
```

保持终端运行，打开 `http://127.0.0.1:47611/overview`，输入终端显示的一次性配对码；按 `Ctrl+C` 停止前台服务。状态目录保存身份与历史，之后沿用同一路径。若程序返回已有匹配实例的状态，可对同一实例使用 `pair --port 47611` 获取新码。端口被其他实例占用时先核对归属，不结束不明进程。

若要使用包内 bootstrap，须先通过上述校验取得暂存程序，再用它执行 `init --port 47611`，确认成功后，使用相同状态目录和端口调用 `bootstrap.sh` / `bootstrap.ps1`。沿用系统正常脚本执行策略。bootstrap 的“starting serve”输出本身不是健康检查；启动后用已验证程序的 `status --port 47611` 核对服务身份与就绪状态。

若仅使用 Skill ZIP，同版本二进制已随本次 Release 上传。Linux/macOS 可先设置独立的状态与暂存目录，显式设置 `SIQ_AGENT_SECURITY_ALLOW_DOWNLOAD=1`，从实际 Skill 目录运行 `scripts/resolve_verified_bin.sh` 取得验签后的程序，再执行 `start`。Windows 可使用上面的验证器，将 `--bin ...` 替换为显式 `--fetch-artifact`，保持 `--stage-to` 和固定公钥校验。完整离线包可直接使用自带二进制，无需下载。

确认服务就绪后，按[个人客户端手册](personal-client-operation-guide-20260916.md)确认权限和接入宿主。启动服务本身不等于给所有宿主启用保护。

## 发布与回读

打包命令不创建 tag、推送 Git、上传或发布 Release。签发后先检查候选来源、范围、秘密扫描及最终解压包验证；取得发布授权后，版本 tag 指向固定源码提交，上传完整包、Skill ZIP、四目标二进制和元数据，不覆盖同版本资产。

发布后重新下载包和二进制，核对本地已验签候选摘要，并再次验证清单与内容。README 的安装链接只能指向实际存在且已回读验证的版本，不能用 `latest` 把研究源码预发布或历史包误作新版安装包。
