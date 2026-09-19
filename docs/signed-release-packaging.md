# 签名安装包的构建与验证

开发入口为 `main`；用户安装入口为经过签发的具体版本包。GitHub 自动生成的 Source code ZIP 和直接复制的 `skills/siq-agent-security/` 不含该版本签名清单，不能作为签名安装包使用。历史 `testdata/releases/` 只用于回归测试。

当前可下载版本：[0.3.0-rc.1 预发布版](https://github.com/maoyadongsh/siq-agent-security/releases/tag/siq-agent-security-v0.3.0-rc.1)。普通用户选择 `siq-agent-security-0.3.0-rc.1-bundle.zip`，解压后按下文安装；维护者构建、签发步骤另列于下。该版 Linux ARM64 安装链路已验证，其他目标尚待原生验收，见[发行证据](evidence/releases/0.3.0-rc.1/README.md)。

## 构建固定版本

在仓库根运行，`--source-sha` 必须是已审阅的完整提交 ID，版本示例不是自动发布承诺：

```bash
python3 scripts/release/package.py \
  --source-sha <40位已审阅提交ID> \
  --version 0.3.0-rc.1 \
  --out-dir .tmp/releases/0.3.0-rc.1-unsigned
```

工具从 Git 提交导出构建输入，不复制工作区未提交文件、私有状态或论文；只在临时目录安装锁定 Web 依赖、重建 UI 和构建二进制。重建 UI 与提交的 embed 有差异时失败，应先修正并审阅源码/生成物，不能在发行过程中默默替换候选身份。需要 Python 3.12+、Git、Node/npm 和支持本仓 Go 模块的工具链；输出记录实际工具版本。

输出包括明确标为 `unsigned-candidate` 的压缩包、四目标原始二进制、`SOURCE-INFO.json` 与 `SHA256SUMS`；没有可安装 Skill ZIP。四目标是 Linux amd64/arm64、macOS arm64、Windows amd64；不意味着四平台的安装和实际宿主能力已经完成验收。

## 使用现有发行密钥签发

通过已批准的本机秘密存储或 CI secret 将 `SIQ_AGENT_SECURITY_RELEASE_SEED` 提供给打包进程。不要将密钥写在命令参数、终端输出、报告或 Git 文件中。该变量只会传给签名子进程，不传给 npm、Go 构建或验证子进程。

对同一固定源码使用新的空输出目录：

```bash
python3 scripts/release/package.py \
  --source-sha <40位已审阅提交ID> \
  --version 0.3.0-rc.1 \
  --out-dir .tmp/releases/0.3.0-rc.1-signed \
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

把完整包解压到新目录，在该目录执行。Linux/macOS 选择对应二进制；以下以 Linux arm64 为例：

```bash
chmod +x bin/siq-agent-security-linux-arm64
export SIQ_AGENT_SECURITY_BIN="$PWD/bin/siq-agent-security-linux-arm64"
sh skills/siq-agent-security/scripts/bootstrap.sh
```

Windows PowerShell：

```powershell
$env:SIQ_AGENT_SECURITY_BIN = (Resolve-Path '.\bin\siq-agent-security-windows-amd64.exe').Path
& '.\skills\siq-agent-security\scripts\bootstrap.ps1'
```

沿用系统正常脚本执行策略，不要求关闭系统安全控制。bootstrap 在启动前验证清单、Skill 内容和二进制，并将程序暂存到受控位置。之后按本机操作指南配对管理界面、确认权限和接入宿主；启动服务本身不等于给所有宿主启用保护。

若仅使用 Skill ZIP，先确认同版本 Release 二进制已上传；只有显式设置 `SIQ_AGENT_SECURITY_ALLOW_DOWNLOAD=1` 才允许 bootstrap 下载清单中固定的资产。完整离线包可以使用其自带二进制，无需下载。

## 发布与回读

打包命令不创建 tag、推送 Git、上传或发布 Release。签发后先检查候选来源、范围、秘密扫描及最终解压包验证；取得发布授权后，版本 tag 指向固定源码提交，上传完整包、Skill ZIP、四目标二进制和元数据，不覆盖同版本资产。

发布后重新下载包和二进制，核对本地已验签候选摘要，并再次验证清单与内容。README 的安装链接只能指向实际存在且已回读验证的版本，不能用 `latest` 把研究源码预发布或历史包误作新版安装包。
