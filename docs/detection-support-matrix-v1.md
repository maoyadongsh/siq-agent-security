# 检测支持矩阵 v1（DEV06）

> 与 [detection-baseline.md](detection-baseline.md)、[threat_match_oracle/v1](../apps/control-api/app/tests/fixtures/threat/match_oracle_v1.json) 配套。
> 本矩阵只陈述**能力归属**，不把 AST 独有能力记成 Go↔Python 完全对等。

## 共享层（Go + Python 合同承诺）

| 能力 | 载体 | 字段级对等 |
| --- | --- | --- |
| 签名规则包文本正则 | `threat_rules.v1.json` / `rulepack.Builtin` | 是：`match_oracle_v1` 冻结 `rule_id` / `line` / `excerpt` / `excerpt_sha256` / `content_sha256` / `detected_type` |
| 类型嗅探 | `detect_type` / `DetectType` | 是（同上） |
| 脱敏 + excerpt 截断 40 | redaction patterns | 是（同上） |
| 每规则首次命中 | 按行扫描 | 是 |

再生 Oracle（Python 为独立生产者）：

```bash
cd apps/control-api && uv run python scripts/gen_threat_match_oracle_v1.py
```

验证：

```bash
cd apps/control-api && uv run pytest app/tests/test_threat_match_oracle.py -q
cd apps/agentshield && go test -count=1 ./internal/threat/ -run TestMatchOracleFieldParity
```

## Python 独有（AST；Go 不实现、不对等宣称）

| rule_id | 说明 |
| --- | --- |
| `threat-py-os-system` | AST：`os.system` / `os.popen` |
| `threat-py-subprocess-shell` | AST：`subprocess.*(shell=True)` |
| `threat-py-ctypes-load` | AST：`ctypes` 动态加载 |
| `threat-py-syntax-parse-failed` | AST 解析失败告警 |

规则包中的 `threat-py-*-regex` / `threat-py-dangerous-import` 属于**共享层**；与 AST 规则可对同一行为双命中（纵深，非 bug）。

## 尚未纳入本切片 Oracle 的缺口（诚实保留）

| 缺口 | 计划归属 | 本切片状态 |
| --- | --- | --- |
| 多行 shell 续行 / 管道跨行（H5a） | DEV06-B / DEV06-D / DEV06-E | **部分：** shell 接合 POSIX `\`；PowerShell 接合 `` ` ``；DEV06-E：shell/powershell 对下一行以 `|` 开头的伪管道续行亦接合（不嵌入换行）。语料含 `mal-download-exec-pipe-continued` / `-pseudo` 与 PS 对应样本。剩余：引用/fence 深层语义 |
| 引用 / fence 启发式与 zone 降级（H5b–c、准入） | DEV06-C | **部分：** docs 区代码文件（`isCodeFile`）不再一律 info 降级；示例判定改为 blockquote + 显式 example/do-not-follow 措辞，不再因引号个数降级。fence 仍由调用方处理 |
| 能力事实 → 准入 disposition 端到端 | DEV06-F | **聚焦：** [`capability-admission-matrix-v1.md`](capability-admission-matrix-v1.md) + `dispositions_matrix_test.go` 锁 25 条共享规则与正交判据。跨产品 profile / 整任务未宣称 |
| Unicode 行分隔、词边界变异语料 | DEV06-G | **聚焦：** Go `splitLines` 对齐 Python `splitlines`（含 U+2028/U+2029/NEL 等）；语料 `mal-download-exec-pipe-unicode-ls` + `benign-download-exec-notcurl-boundary`。RE2 vs Python 完整 Unicode `\b` 语义未宣称 |

真实设备信任、独立扫描复核、生产策略差分不在此矩阵记为通过。
