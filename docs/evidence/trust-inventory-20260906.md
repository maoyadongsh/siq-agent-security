# 信任材料指纹台账（DEV01-A）

- 日期：2026-09-06
- 计划：[DEV01](../development-plan-20260906-022735.md#dev01)
- 基线 commit：`0723f88cf4a242be6bf3f679996f5795ef75028e`
- 处置边界：**本文件不执行生产撤销、对外通知或 Git 历史重写。** 历史清理需单独操作单与授权。
- 复核方法：`python3 scripts/trust-fingerprint.py`（只打印公钥与 SHA-256；种子只进 `go run scripts/ed25519_pub.go` 的 stdin）
- 负责人：本切片记录人（开发会话）；**在役设备事实待安全负责人 / SRE 受控核查**
- 数据来源：本仓库 Git 对象与公开常量。不是生产 Secret Manager 的实时导出。

## 用途分类

| 用途 | 材料位置 | 消费者 | 生效 / 撤销 | 在役状态 |
| --- | --- | --- | --- | --- |
| 本地发布 / Skill 清单验签 | `skillmanifest.ReleasePublicKeyB64`，bootstrap 内嵌同一公钥 | `manifest-verify`、bootstrap.sh/ps1、控制台展示 | 轮换须同时改常量、bootstrap、`--write-bootstrap` | 当前树在用（公钥常量） |
| 控制面任务签名（历史 Git 对象） | `364dade:apps/control-api/signing-key.seed`；`145e53f` 从工作区删除 | 曾经可能被 Edge 钉为 `control_plane_public_key` | **未在本任务中撤销** | **未核实** |
| 控制面任务签名（当前生产） | `SIQ_AS_TASK_SIGNING_KEY_SEED`（Secret Manager） | Edge `VerifyTaskSignature`；规则包外部签名也复用该加载路径 | 生产轮换不在本切片 | **未核实**（仓库内无种子） |
| 本地回执身份 | `<state>/keys/signing.seed`（O_EXCL 生成，0600） | `siq-agent-security verify`、admission/grant 签名 | 每台机器独立 | 仅本机，不进 Git |
| 外部规则包 | `SIQ_AGENT_SECURITY_RULEPACK_PUBKEY` + `<file>.sig` | 本地 Go / 控制面 Python 加载器 | 验签失败回退内置包 | 可选；内置包无单独私钥 |

测试夹具公钥 `A6EHv/POEL4dcN0Y50vAmWfk1jCbpQ1fHdyGZBJVMbg=` 来自合成种子 `bytes(range(32))`，**不是**历史 Git 对象，不得当作生产根。

## 公开指纹（2026-09-06 本克隆）

| 记录 | 公钥（standard base64） | SHA-256（公钥原始 32 字节） |
| --- | --- | --- |
| 本地发布根 v1 | `LtEknKeTxzUQwErXI0MboUQQXKqrGp+R2x2RUv9/ZHY=` | `69b30fca302322915b7b26e327a1e152ccd11a14678e0feac4a0e81d330a8702` |
| 历史任务签名（Git blob 仍可达） | `JOyyWund4cHjinmbLw/ZE84J7bd1rJUdMfdZ3KNkB5c=` | `ffccdef01aedc404f110421151baec4aceb34409d9e63ddb1b803093d965eb55` |

当前工作区已无 `apps/control-api/signing-key.seed`。blob `6e4fa3f250953dee6e489455b5915118b89a1c2f` 仍在 `origin` 历史中。CI 只拦截相对 base **新加入**的 `signing-key*.seed`，不把清历史当作关闭条件。

## 在役影响（已知 / 未知）

- **已知：** Edge 在注册时把控制面公钥钉在设备状态里（`edge/agent/state.go` 的 `control_plane_public_key`）。本仓库没有生产 Edge 清单，因此不能证明历史公钥「从未被钉」或「已经轮换」。
- **未知 / 未核实：** 任何真实环境的 Secret Manager 当前值、已注册设备列表、离线恢复是否会重新加载旧根。
- **禁止的关闭方式：** 仅用已暴露旧 key 签署新根公告；把「应该已轮换」写成结论；在日志/工单粘贴种子。

后续由持有生产只读权限的人：导出各 Edge 钉住的公钥 SHA-256，与上表历史指纹比对。若命中，按 [GitHub leaked-secret 处置说明](https://docs.github.com/en/code-security/tutorials/remediate-leaked-secrets/remediating-a-leaked-secret) **先撤销/更新信任**，再考虑历史清理操作单。本文件保持「未核实」，直到那次比对有书面结果。
