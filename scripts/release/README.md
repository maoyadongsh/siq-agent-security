# 客户端发行工具

维护者从仓库根运行，Python 3.12+、OpenSSL；公开回读另需已认证的 GitHub CLI 和联网。工具不发布或覆盖远端资产，不需要发行私钥即可复验正式包。

## 验证现有签名包

先将指定 Release 的八份附件下载到一个新目录。`SOURCE-INFO.json` 中的源码身份只是描述性元数据；核对预期 tag/commit 后显式传入，不能把元数据当作源码构建证明。

```bash
mkdir -p .tmp
release_dir=$(mktemp -d "${TMPDIR:-/tmp}/siq-release-assets.XXXXXX")
env -u GITHUB_TOKEN gh release download siq-agent-security-v0.3.1 \
  --repo maoyadongsh/siq-agent-security --dir "$release_dir"
python3 scripts/release/verify.py --release-dir "$release_dir" \
  --version 0.3.1 --source-sha f3d9c3f0933f3b08d15b2d3dbc522f409c77a355 \
  --report .tmp/release-verification.json
```

验证八资产清单/摘要、ZIP 路径/类型/大小/大小写冲突、包与单文件的一致性、官方 Skill 签名和实际内容、四目标二进制 pin、许可文件及当前可信生成器的安装文本。`SHA256SUMS` 自身不是签名；官方签名约束 Skill 与二进制 pin，不单独证明源码、许可证和安装说明的出处。解包发生在私有临时目录；默认不联网、不执行二进制、不启动服务。

增加 `--native-smoke` 可显式运行当前 Linux/macOS 目标的空状态启动、status、pair、控制台和停止链路；使用临时状态、随机回环端口，私有日志/配对输出随临时目录清理。Windows 原生链路尚不支持此驱动；Linux 通过不能替代另外三个发行目标验收。报告文件必须是新路径，重复运行换文件名，不覆盖旧记录。

验证器的安装说明要求与当前生成器一致。历史 RC 的旧说明会被拒绝；这不撤销旧签名，复验旧说明需另行审查对应版本，不放宽检查后直接执行包内文本。

## 只读公开回读

沿用上一步经验证的本地八资产目录：

```bash
python3 scripts/release/readback.py --reference-dir "$release_dir" \
  --version 0.3.1 --source-sha f3d9c3f0933f3b08d15b2d3dbc522f409c77a355 \
  --report .tmp/release-readback.json
```

核对远端 tag 的 commit、非草稿状态、八资产实际下载与本地逐字节一致性、官方验签、匿名校验清单下载和当前目标的签名 URL 下载/暂存。记录 `prerelease` 与 `is_latest` 的实测值，不把它们强制改成正式版。不会启动服务或修改 Release。私有未发布候选不能通过此公开回读。

## 构建与边界

企业 Edge/Connector 使用独立的 [enterprise_candidate.py](enterprise_candidate.py)，
不是下述个人客户端打包入口。它要求完整提交 ID 和独立审阅的企业源码清单，
离线构建 Linux amd64/arm64；默认包含 Hermes、OpenClaw、directory，可选择子集。
产物包括 `CANDIDATE.json`、二进制、许可/摘要及明确标名的 `unsigned-candidate.zip`，
ZIP 逐文件回读核对并保留可执行位；外层 SHA256SUMS 同时覆盖 ZIP 和散文件。
不生成 `release.json` 或签名，
不能交给生产安装器直接安装。参数、清单范围和限制见
[enterprise-release-candidate/v1](../../packages/contracts/enterprise-release-candidate.v1.md)。
工作树增量必须先完成评审和源码冻结，不能使用旧提交宣称包含最新开发成果。当前 `main` 已包含 2026-09-26/27 的后续企业收口与 CI 修复，但尚未据此生成、签发或发布新候选；`0.4.0-rc.2` 仍固定在较早的 `7b68c14`，不得重标为当前主线包。

企业候选还包含 `publisher-signing-input.json`：原发行公钥、源码提交与二进制 pin
组成的精确规范化 Ed25519 待签名字节，不是签名包。受控环境经授权签发后，可用独立
可信构建的 `edge-agent verify-enterprise-release --release FILE` 核验正式信封；
该命令不允许替换公钥、不注册设备；不加其他参数只证明信封签名。增加
`--bundle /absolute/bundle` 可只读核对签名中的全部架构及采集器文件，不能替代安装时的
计划绑定和私有暂存校验，也不证明未签入的说明/许可文件或运行行为。
当前候选工具不执行签发、签后组包或发布。

签发后的组包由独立 [enterprise_finalize.py](enterprise_finalize.py) 完成：输入候选目录、
已由受控流程签发的信封、预期完整源码提交/版本，以及独立审阅的本机 Edge 验签程序
和其 SHA-256。不能从待验候选取得验签程序或直接信任候选提供的摘要。
工具先核对待签输入一致性，再验证候选全部制品，复制到私有暂存后二次核验，最后
生成 ZIP、release.json、SOURCE-INFO.json 和 SHA256SUMS 到全新外部目录。
它不持有签名密钥、不注册设备、不发布；组包成功也不代表安装验收完成。
参数见 `python3 scripts/release/enterprise_finalize.py --help`，信任前提及失败边界见
[enterprise-release-finalization/v1](../../packages/contracts/enterprise-release-finalization.v1.md)。

[package.py](package.py) 从固定完整 Git SHA 导出产品允许清单，隔离构建四目标；`--help` 给出候选参数。没有签发参数时产生明确的未签名候选，不宣称为可安装发行版。签发是独立维护者流程，遵守[源码与发行边界](../../docs/skill-source-release-boundary-20260919.md)。工具不更改已发布资产。

当经过验证的增量尚未包含在旧冻结提交中，使用 `--expected-source-inventory <reviewed.json>` 将新提交导出的完整发行源码与已审阅快照比对。清单格式为 `{"schema_version":"siq-release-source-inventory/v1","files":{...}}`，`files` 使用本工具 `inventory()` 的相对路径、SHA-256、字节数、可执行标记，范围恰为 `SOURCE_PATHS`。清单应在评审时固定并另行核对其摘要，不能从待签提交临时生成来代替评审。缺文件、多文件、内容或可执行标记不一致，均在 npm/Go 构建及签发前失败；该清单不是签名或源码证明，不替代正式发行验签。未指定此参数的历史打包行为保持不变。

```bash
python3 -m unittest discover -s scripts/release -p 'test_*.py' -v
python3 -m ruff check scripts/release
```

[仓库整理阶段复验](../../docs/evidence/repository-reorganization-20260919/README.md)与[0.3.1 发行记录](../../docs/evidence/releases/0.3.1/README.md)分别记账；重复验证不增加独立环境数量。

## Skill 源码说明的原生检查

`skill_source_smoke.py --binary <self-built-program> --target <os/arch> --report <new-file>` 用自建程序自扫描源码 Skill，确认缺 manifest 的 bootstrap 在创建状态/暂存前拒绝，并在两个独立临时状态目录验证 `start` 和 `init`→`serve` 的 status/pair/控制台/停止链路。日志、状态和配对输出不进入公开报告；不注册宿主钩子、后台系统服务或发布签名包。

[skills-compat 工作流](../../.github/workflows/skills-compat.yml)使用四个原生目标，执行前比较真实 OS/架构以防误用交叉编译冒充原生运行。runner 标签按 [GitHub 官方说明](https://docs.github.com/en/actions/reference/runners/github-hosted-runners)选择；托管主机上的源码检查仍不证明用户桌面、完整宿主验收、发行安装升级或 OS 厂商签名。源码正文变化不改 0.3.1 的签名载荷，后续安装包需要新的候选与签发。
