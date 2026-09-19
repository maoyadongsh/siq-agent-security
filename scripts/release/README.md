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

[package.py](package.py) 从固定完整 Git SHA 导出产品允许清单，隔离构建四目标；`--help` 给出候选参数。没有签发参数时产生明确的未签名候选，不宣称为可安装发行版。签发是独立维护者流程，遵守[源码与发行边界](../../docs/skill-source-release-boundary-20260919.md)。工具不更改已发布资产。

```bash
python3 -m unittest discover -s scripts/release -p 'test_*.py' -v
python3 -m ruff check scripts/release
```

[仓库整理阶段复验](../../docs/evidence/repository-reorganization-20260919/README.md)与[0.3.1 发行记录](../../docs/evidence/releases/0.3.1/README.md)分别记账；重复验证不增加独立环境数量。

## Skill 源码说明的原生检查

`skill_source_smoke.py --binary <self-built-program> --target <os/arch> --report <new-file>` 用自建程序自扫描源码 Skill，确认缺 manifest 的 bootstrap 在创建状态/暂存前拒绝，并在两个独立临时状态目录验证 `start` 和 `init`→`serve` 的 status/pair/控制台/停止链路。日志、状态和配对输出不进入公开报告；不注册宿主钩子、后台系统服务或发布签名包。

[skills-compat 工作流](../../.github/workflows/skills-compat.yml)使用四个原生目标，执行前比较真实 OS/架构以防误用交叉编译冒充原生运行。runner 标签按 [GitHub 官方说明](https://docs.github.com/en/actions/reference/runners/github-hosted-runners)选择；托管主机上的源码检查仍不证明用户桌面、完整宿主验收、发行安装升级或 OS 厂商签名。源码正文变化不改 0.3.1 的签名载荷，后续安装包需要新的候选与签发。
