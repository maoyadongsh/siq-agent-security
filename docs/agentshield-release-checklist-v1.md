# AgentShield GitHub Release 清单 v1

- 日期：2026-09-05
- 状态：**tag `agentshield-v0.1.0` 已切**（2026-09-06，commit `f14bb06`）。矩阵仍无 `supported` 行。
- 仓库：[`maoyadongsh/siq-agent-security`](https://github.com/maoyadongsh/siq-agent-security)
- 分支：`cursor/agentshield-w0-contracts-8eff`（**不要**为发版而合 `main`，除非另行要求）
- 规格：[`agentshield-dev-spec-v1.md`](./agentshield-dev-spec-v1.md) §5.2
- 评委入口：[`AGENTSHIELD.md`](../AGENTSHIELD.md)（源码 `go build` + `serve`；bootstrap **不会**按 URL 下载）

> 一句话：先让已签名的 `skill-manifest.json` 与四目标二进制哈希一致，再 `gh release create`。矩阵**不得**出现 `supported` 行。私钥只走环境变量，禁止打印、禁止写进 notes、禁止提交。

---

## 0. 当前快照（发版前要核对）

| 项 | 口径 |
| --- | --- |
| tag 名 | `agentshield-v0.1.0`（与 `DefaultURLBase` / `binary.version` 一致） |
| 资产文件名 | `agentshield-linux-amd64`、`agentshield-linux-arm64`、`agentshield-darwin-arm64`、`agentshield-windows-amd64.exe` |
| URL 前缀 | `https://github.com/maoyadongsh/siq-agent-security/releases/download/agentshield-v0.1.0/` |
| 公钥（bootstrap 已嵌入） | `LtEknKeTxzUQwErXI0MboUQQXKqrGp+R2x2RUv9/ZHY=` |
| `support_matrix` | 全行 `experimental` 或 Trae `audit_only`；**0 行 `supported`** |
| bootstrap | 找不到本地二进制就失败；不下载 Release 对象 |
| 计划 §1.4 | 合 `main`、打 Release **除非另行明确要求** |

OpenClaw / CodeBuddy linux 备注指向 2026-09-05 隔离 HOME 证据；**状态仍是 experimental**。改备注或改 Skill 目录（`skill-manifest.json` 除外）都会改变签名文档或 `content_hash`，必须重签。

---

## 1. 禁止项

- 把任意一行改成 `supported`（`ValidateMatrix` 会拒绝；评委入口也禁止）
- 打印、粘贴、提交 `AGENTSHIELD_RELEASE_SEED`；不要写进 commit、PR、Release notes、证据、聊天
- 轮换公钥，除非种子丢失或密钥泄露（要同时改 `ReleasePublicKeyB64`、bootstrap、`--write-bootstrap`）
- 上传与清单 `sha256` / `bytes` 不一致的二进制
- 用 `gh release create` 之前跳过 `manifest-verify` 与哈希核对
- 改 `hermes-agent` / `research-engine`；不 `openshell gateway start`

---

## 2. 重签（有种子才做）

种子只允许环境变量 `AGENTSHIELD_RELEASE_SEED`（32 字节 Ed25519 seed 的标准 base64）。gitignore：`*.release.seed`、`secrets/`。本机若有忽略文件，注入后**不要 `echo` / `cat` 该值。

```bash
cd apps/agentshield
export PATH="${HOME}/sdk/go/bin:${PATH}"
# 注入种子后：
./agentshield release-manifest --build --bin-dir /tmp/agentshield-release-bin
./agentshield manifest-verify ../../skills/agentshield/skill-manifest.json
gofmt -l . && go vet ./... && go test ./...
```

`release-manifest` 会用 `DefaultMatrix()` 覆盖 `support_matrix`。改备注先改 `internal/skillmanifest/matrix.go`，再重签。合同样例（测试密钥，不是发布密钥）：

```bash
WRITE_SKILL_MANIFEST_SAMPLE=1 go test ./internal/skillmanifest -run TestSampleManifestMatchesBuilder
```

然后：

```bash
cd ../control-api
uv run --frozen pytest app/tests/test_schema_contracts.py -q -k skill_manifest
```

---

## 3. 无种子时的失败闭合

没有 `AGENTSHIELD_RELEASE_SEED`：

1. **不要**伪造签名，不要改 `signed_by` / bootstrap 公钥。
2. 只跑哈希核对（下一节）。源码若已变，核对会失败——这是预期，说明不能上传旧清单对应的 URL。
3. 评委路径继续 `go build`；bootstrap 不按 URL 下载。

---

## 4. 哈希核对（不需要种子）

```bash
# 现编四目标并与 skills/agentshield/skill-manifest.json 比对
./scripts/agentshield-release-check.sh --build

# 或对已有目录（例如 release-manifest --bin-dir）
./scripts/agentshield-release-check.sh --bin-dir /tmp/agentshield-release-bin
```

退出码 0：四个 `sha256` 与 `bytes` 都与清单一致。非 0：禁止 `gh release create`。

CI 的 `agentshield` job 会交叉编译并 `manifest-verify`，**故意不**把每次 PR 的二进制钉死到清单（否则任何 Go 改动都要种子）。发版前必须本地（或 tag 作业）跑本脚本。

---

## 5. 真正打 tag / Release（本清单不自动执行）

确认：工作区干净、清单已提交、`agentshield-release-check.sh --bin-dir <同一目录>` 为 0、矩阵无 `supported`。

```bash
# 二进制必须是重签时编出来的那四个文件
gh release create agentshield-v0.1.0 \
  --title "agentshield 0.1.0" \
  --notes-file - \
  /tmp/agentshield-release-bin/agentshield-linux-amd64 \
  /tmp/agentshield-release-bin/agentshield-linux-arm64 \
  /tmp/agentshield-release-bin/agentshield-darwin-arm64 \
  /tmp/agentshield-release-bin/agentshield-windows-amd64.exe <<'EOF'
AgentShield 0.1.0 binaries pinned by skills/agentshield/skill-manifest.json.

Judge path: AGENTSHIELD.md (source go build). bootstrap does not download these URLs.

support_matrix has no supported rows.
EOF
```

notes 里不要出现种子、token、本机绝对路径。创建后立刻：

```bash
gh release view agentshield-v0.1.0 --json assets --jq '.assets[].name'
# 抽查一个资产的 sha256，必须等于清单对应字段
```

评委仍以源码构建为准，直到你明确改 `AGENTSHIELD.md` 的「尚未发布」句。

---

## 6. 可选：Skill zip（§5.2 第 4 步）

```bash
git archive --format=zip --prefix=agentshield/ \
  HEAD:skills/agentshield > /tmp/agentshield-skill-v0.1.0.zip
```

可挂到同一 Release，不是评委复现的前置。

---

## 7. 完成后回写

- [`AGENTSHIELD.md`](../AGENTSHIELD.md)：删掉「GitHub Release 未打 tag」或改成已发布 + tag
- 本文件状态行改为「tag 已切」
- 规格 §9 W5/W6：URL 对象已存在
- **仍然不要**把矩阵改成 `supported`，除非另案 + 重签
