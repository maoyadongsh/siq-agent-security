# 签名文档生产者—消费者清单（DEV09-B/C/D）

本清单冻结「谁签、用哪套规范化、谁验」；不是实现细节百科。改签名字段集合或规范化规则时：先升版本合同、双读消费者、再切换写者。

| 文档 | 规范化合同 | 生产者 | 消费者 | 固定向量 | 备注 |
| --- | --- | --- | --- | --- | --- |
| 任务信封 | CPython `json.dumps(sort_keys=True, separators=(",",":"))` 默认 **ensure_ascii=True** | control-api `signing.py` | Edge `VerifyTaskSignature` + `edge/agent/canon.Marshal` | `fixtures/task_signature_vectors_v1.json` | DEV09-A；路由 id `task_envelope/v1` |
| Evidence / Batch | CPython `ensure_ascii=False` + 同 float.__repr__ | Edge `SealEvidence` **默认嵌入** `signing_schema=evidence_utf8/v1`（DEV09-H）→ `canon.MarshalUTF8` | control-api `evidence_signing` 双读（缺省=同合同；错 schema 拒绝） | `fixtures/evidence_signature_vectors_v1.json` + `evidence_embedded_schema_vectors_v1.json` | DEV09-B/H；**不得**与任务/本地 ASCII 混用 |
| skill-manifest | `ensure_ascii=True` 紧凑排序（Python bootstrap / Go skillmanifest） | `release-manifest` | bootstrap/`verify_manifest.py`、`manifest-verify` | 仓库内已签 manifest + Go/Python 对等测 | DEV04；发行根另见信任清单 |
| admission / grant（本地） | Go `apps/agentshield/internal/canon`（ASCII，对齐任务） | agentshield `SignCanonical` + **默认嵌入** `signing_schema=local_canonical/v1`（DEV09-G） | `VerifyDocument` / `VerifyWithSchema(local_canonical/v1)` | `fixtures/local_doc_signature_vectors_v1.json` + embedded 夹具 | DEV09-C/E/G；遗留无字段体仍可双读 |
| receipt（本地链） | 正文用 local ASCII canon → `content_hash=sha256`；**签名覆盖 hash 的 ASCII hex 字节**（`SignBytes`），不是正文 | agentshield `receipt.Append` | `ContentHash` + `VerifyHashSignature` / `VerifyBytes` | `fixtures/receipt_signature_vectors_v1.json` | DEV09-D；路由 id `receipt_hash_chain/v1`；**禁止**用 `VerifyWithSchema`/`SignCanonical` 当回执验签 |
| rulepack `.sig` | 与本地 canon ASCII 一致（`local_canonical/v1`） | 发布流水线 / 独立夹具生产者 | agentshield `rulepack.VerifySignature`；control-api `rulepack._verify_signature` | `fixtures/rulepack_signature_vectors_v1.json` | DEV09-I；sidecar base64 `.sig`，正文不嵌 `signing_schema`；防回滚策略另议 |
| Desired Policy → OpenShell 制品 | 编译产物 `artifact` + sha256；未知键拒绝 | control-api `compile_policy` | Go `grant.CompilePolicy` | `fixtures/policy_compile_vectors_v1.json` | DEV09-F；known_keys 与 unsupported 文案须对等 |
| 分享导出 `agentshield.export.v1` | 本地 ASCII canon（`local_canonical/v1`）覆盖**脱敏投影** | agentshield `export.Seal` | `export.Verify` | Go 往返/篡改/跨合同负向（`seal_test.go`） | DEV15-D；`derived_from.kind=agentshield.export.derived/v1`；**禁止**套用回执 hash-chain 签名 |
| 受管 tip checkpoint | 本地 ASCII canon（`local_canonical/v1`） | `CheckpointStore.Publish`（Append 后） | `CheckpointStore.Load` → `VerifyDetailed` | `checkpoint_test.go` | DEV15-E；路径在 `checkpoints/`，**禁止** `receipts/.../HEAD` |

## 双读原则

- **任务 vs Evidence**：Unicode/HTML/`100.0` 向量下二者字节必不同；混用验签必须失败。
- **本地 ASCII vs Evidence**：`local_doc_signature_vectors_v1.json` 的 `cross_contract_note` 锁定同一文档两套 canon 不等。
- **Receipt hash-chain vs SignCanonical**：同一回执正文上，对 body 的 `SignCanonical` 签名必须与对 `content_hash` hex 的 `SignBytes` 不同；夹具 `cross_contract_note` 锁定。
- **版本路由**：`signing.NormalizeSigningSchema` / `VerifyWithSchema` — 已注册 `local_canonical/v1`、`task_envelope/v1`；`evidence_utf8/v1` 与 `receipt_hash_chain/v1` 在本地 ASCII 验签器上 **受控拒绝**；未知（如 `local_canonical/v2`）在注册双读前拒绝。升版时先挂新 id 再切写者。
- **正文内嵌 `signing_schema`（DEV09-E/G/H）**：`VerifyDocument` 双读本地 ASCII；admission/grant **写者默认嵌入** `local_canonical/v1`。Evidence：**写者默认嵌入** `evidence_utf8/v1`；遗留无字段体控制面双读为同合同。夹具 `fixtures/local_doc_embedded_schema_vectors_v1.json`、`fixtures/evidence_embedded_schema_vectors_v1.json`。
- **独立生产者**：夹具由不导入待测模块的脚本生成；Go/Python 只做消费者。

## 本切片未做

- 真实 IdP / 生产密钥轮换（非 DEV09）
- 防回滚“严格递增”策略变更（当前同版本可接受，见 rulepack Load）
