# 修复后候选正式签名指引（维护者专用）

2026-09-16 修订。rc.1 保留为历史，不再作为修复后候选。当前修复候选为 rc.2，
构建绑定与未完成验收见 `release-openshell-review-fixes-20260916.md`。
签名只验证制品来源，不表示 O05、B3 或跨平台验收完成。

## 前提

- 正式种子必须是 **32 字节种子的标准 base64 编码**；不接受原始字符串。
- `skillmanifest.KeyFromEnv` 读取 `SIQ_AGENT_SECURITY_RELEASE_SEED`。
  不生成替代正式种子，不修改内嵌信任根，不使用 `--write-bootstrap`。
- 内嵌信任根为 `LtEknKeTxzUQwErXI0MboUQQXKqrGp+R2x2RUv9/ZHY=`。
  签名命令自身仅警告公钥不符，必须执行下列独立 `manifest-verify`；不通过则不得发布。
- 禁用 shell 跟踪。种子仅交互读取到环境变量，不写入命令历史、argv、日志或仓库。

## 操作（Bash；Linux arm64 本机）

以下命令使用构建后的原生二进制，避免在仓库根错误执行 `go run ./cmd/agentshield`。
签名输出与 Skill 内容一起放入私有暂存目录，避免覆盖受版本管理的清单。
`manifest-verify` 会对**清单所在目录**重算 Skill 哈希，不能单独把清单放在无内容目录验签。

```bash
set +x
set -euo pipefail
cd /home/maoyd/siq/worktrees/siq-release-openshell-20260916-142706
candidate_dir="$PWD/dist/siq-agent-security-0.3.0-rc.2"
(cd "$candidate_dir" && sha256sum -c SHA256SUMS)

umask 077
signing_stage=$(mktemp -d)
cp -a skills/siq-agent-security "$signing_stage/skill"
trap 'unset SIQ_AGENT_SECURITY_RELEASE_SEED' EXIT
read -r -s -p '正式 base64 种子（不回显）: ' SIQ_AGENT_SECURITY_RELEASE_SEED
printf '\n'
export SIQ_AGENT_SECURITY_RELEASE_SEED

"$candidate_dir/siq-agent-security-linux-arm64" release-manifest \
  --client-compatible --version 0.3.0-rc.2 \
  --skill-dir "$signing_stage/skill" \
  --bin-dir "$candidate_dir" \
  --out "$signing_stage/skill/skill-manifest.json" \
  --url-base 'https://github.com/maoyadongsh/siq-agent-security/releases/download/v0.3.0-rc.2'
unset SIQ_AGENT_SECURITY_RELEASE_SEED

"$candidate_dir/siq-agent-security-linux-arm64" manifest-verify \
  "$signing_stage/skill/skill-manifest.json"
```

其余架构须使用对应原生二进制；不能以交叉编译代替实机验收。
暂存目录保留供人工核对，确认用途后精确清理。不要上传任何种子或私有环境文件。

发布前复核 manifest 的版本、四个平台 artifact 的 sha256/bytes/URL、signed_by、
Skill content_hash 与本次构建证据一致。content_hash 只绑定 Skill 内容，不能代替
Go 源码/二进制绑定。确认正式签名及剩余发行门禁后再另行发布；本轮未签名、未上传。
