# R01（N05）可信 Skill 执行上下文 — 本地服务级活体验证报告

- 生成：2026-09-14T11:26:17.799046+00:00
- 候选二进制：`/home/maoyd/siq/worktrees/siq-personal-v4-r01-20260914/apps/agentshield/.tmp/r01-candidate/agentshield`（sha256 `e5280d6623078e7cc60023dc5efe06bc76adfbeb27598f3542ad9456aebbf9e8`，来源：explicit --binary）
- 仓库：`b303c6f92392f3a44c306d81ad7323c6291ef4f2`（工作树含未提交改动路径 84 条，即本批次 N05/R01 实现）
- 平台：Linux/aarch64；Python 3.13.12；脚本与证据只使用 Python 标准库与候选二进制
- 沙箱：HOME / HERMES_HOME / SIQ_AGENT_SECURITY_STATE_DIR 全部指向一次性 `tempfile.mkdtemp` 目录
  （运行结束即删除）；未触碰真实 `~/.hermes`、`~/.openclaw`，未启动任何模型，未访问外网
- 凭据脱敏：配对码、管理会话、ri- 运行时凭据只存在于内存；所有落盘文件经精确值替换脱敏
- 命令计数：CLI 18 次，HTTP 26 次（明细见 transcript.json 与 raw/）

**总体结论：PASS（本地服务级候选全部步骤通过；R01 原生宿主门槛仍为 partial）**

## 任务书 §5.3 验收场景逐行映射

| 场景（预期） | 结果 | 证据步骤 |
| --- | --- | --- |
| 真实受控调用、正确上下文与有效授权 → 同一实际调用、授权和脱敏回执关联一致 | pass | 51/52/73：decide 回执 skill_attribution（status/evidence_level/context_id/call_binding），call_binding 用 canonical JSON+sha256 本地重算一致 |
| 任意请求复制合法安装摘要、grantID 或 skill claim → 不能产生 verified 或 Skill 专属放行 | pass | 36：无 SEC 时逐字节复制的 claim 归属为 unknown 且 deny；37：未 enroll 会话在认证边界 401 |
| 同一 Agent 下两个 Skill；一个权限更宽 → 较窄 Skill 不能借用另一 Skill 权限 | not-covered | 本脚本只安装一个 Skill；组件测试覆盖 claim 切换与权限交集，双 Skill 宿主活体仍未覆盖（见「待复核项」） |
| 同 Skill 跨实例/会话/任务/调用复制 → 拒绝并且无工具副作用 | pass | 53/53a：换会话或任务后同一 claim 均 deny 且不产生 verified；测试只调用 decide，未执行工具 |
| 参数在许可后改变；同名 Skill 内容替换 → 旧上下文失效，必要时重新审批 | pass | 54：skill_id 替换硬拒绝；56/57：安装内容改变后旧 SEC 立即失效；58：恢复精确字节后重新全量校验通过 |
| Grant 撤销/修订、安装移除、服务重启 → 旧上下文不能恢复已失效权限 | pass | 61/63：撤销 SEC 后重放 → deny skill_context_revoked；75/76：撤销 grant 后不再 allow/verified（实际拦截层见「待复核项 (a)」）；serve 多轮重启后结论不变 |
| 缺来源或平台不支持 → unknown/明确不可用；不得默认可信 | pass | 36/37：无服务端绑定的 claim 恒 unknown；未注册会话明确不可用 |

## 待复核项复核结果

(a) **grant 撤销后的拦截层**（本轮已实测，步骤 75/76）：撤销被 pin 的安装 grant 后，下一次 decide
的实测拦截层为 `http-auth`（ri- 凭据每次请求都经 `GrantForReference` 重读 grant；撤销使凭据在认证
边界失效，请求不到引擎、不产生新回执；HTTP 401 `unauthorized`）。因此任务
预期的引擎层 `skill_context_grant_changed` 回执在 ri- 凭据路径上被认证层遮蔽，该 SEC 级语义由组件
测试承担。活体可证明的真实行为：撤销即时生效、无 allow、无 verified、无工具副作用。

(b) **同 Agent 两 Skill 权限借用交叉场景**：**unverified** —— 本脚本未构造第二枚 Skill 的 SEC
交叉用例；不以组件测试或推断冒充。

## 步骤实录

| 步骤 | 标题 | 类型 | 结果 | 备注 |
| --- | --- | --- | --- | --- |
| 00-binary-version | candidate binary identity | cli | pass |  |
| 01-init-help | init usage probe (task requires reading --help first) | cli | pass | flag.ErrHelp exits 1 after printing defaults |
| 02-adapter-help | adapter usage probe (task requires reading --help first) | cli | pass | adapter subcommand has no flag help; usage error is the honest output |
| 10-init | initialize state directory | cli | pass |  |
| 11-discover-instance | discover isolated Hermes instance (CLI, pre-grant planning) | cli | pass |  |
| 12-admit | admit minimal fixture skill | cli | pass |  |
| 13-grant-create | create skill grant for the planned hri- subject (CLI) | cli | pass |  |
| 14-grant-challenge | approval challenge (CLI) | cli | pass |  |
| 15-grant-approve | human approve with challenge proof (CLI) | cli | pass |  |
| 16-grant-deploy | deploy CLI grant (allowed: admission is not import-reserved) | cli | pass |  |
| 17-adapter-install | install adapter plugin into the isolated HERMES_HOME instance | cli | pass |  |
| 20-serve-a-start | serve start on 127.0.0.1:38371 (mode=block) + admin pairing | cli+http | pass |  |
| 21-serve-instance-confirm | daemon-side instance discovery matches CLI planning | http | pass |  |
| 22-status | daemon status | http | pass |  |
| 23-grant-cli-under-lock | grant CLI must refuse while serve holds the state writer lock | cli | pass | documented single-writer behavior; CLI authority changes run with serve stopped |
| 24-skill-import | import skill from local dir | http | pass |  |
| 25-import-permission | derive import permission grant (draft) | http | pass |  |
| 26-patch-desired | scope grant to read_file/write_file and the sandbox workspace | http | pass |  |
| 27-grant-challenge | approval challenge (HTTP) | http | pass |  |
| 28-grant-approve | approve import grant (HTTP) | http | pass |  |
| 29-install-plan | stage install plan (grant must be approved) | http | pass |  |
| 30-install-apply | apply install plan | http | pass |  |
| 31-install-activate | activate instance-scoped runtime permission (grant stays approved) | http | pass |  |
| 32-runtime-identity | issue runtime identity pinned to the install grant | http | pass |  |
| 33-enroll-session-1 | enroll primary session (SEC subject) | http | pass |  |
| 34-enroll-session-2 | enroll second session (never SEC-covered; negative control) | http | pass |  |
| 35-bindings | read signed session bindings | http | pass |  |
| 36-forged-claim-no-sec | pre-SEC invariant: exact copied claim never verifies | http | pass |  |
| 37-unenrolled-session | scoped credential cannot decide for an unenrolled session | http | pass |  |
| 38-sec-cli-under-lock | skill-context CLI must refuse while serve owns the state writer | cli | pass |  |
| 40-serve-a-stop | serve stop (SIGTERM, drain) | process | pass |  |
| 41-sec-issue-task | issue task-scoped SEC (controlled_task evidence) | cli | pass |  |
| 42-sec-get | read back issued SEC | cli | pass |  |
| 50-serve-b-start | serve start on 127.0.0.1:42525 (mode=block) + admin pairing | cli+http | pass |  |
| 51-positive-task | positive: exact claim + bound task verified | http | pass |  |
| 52-call-binding-recompute | recompute call_binding locally from receipt fields (canonical sha256) | derived | pass |  |
| 53-negative-cross-session | negative (a): same claim on an enrolled but SEC-less session is denied | http | pass | Installed Skill grants require verified SEC attribution even when the legacy skill_attribution_enforcement switch is off |
| 53a-negative-cross-task | negative (a2): task-scoped SEC cannot be copied to another task | http | pass |  |
| 54-negative-claim-swap | negative (d): swapped skill_id claim conflicts with the SEC | http | pass |  |
| 55-negative-no-claim | negative (e): dropping the claim does not downgrade the SEC subject | http | pass |  |
| 56-content-replaced | replace installed Skill content after SEC issuance | filesystem | pass |  |
| 57-content-replaced-deny | changed installed bytes invalidate old SEC authority | http | pass |  |
| 58-content-restored | restoring exact installed bytes restores the still-live SEC | http | pass |  |
| 60-serve-b-stop | serve stop (SIGTERM, drain) | process | pass |  |
| 61-sec-revoke | revoke the task SEC (signed tombstone) | cli | pass |  |
| 62-serve-c-start | serve start on 127.0.0.1:47259 (mode=block) + admin pairing | cli+http | pass |  |
| 63-negative-revoked-replay | negative (b): replay after revocation hard-denies | http | pass |  |
| 70-serve-c-stop | serve stop (SIGTERM, drain) | process | pass |  |
| 71-sec-issue-session | issue session-scoped SEC (controlled_session evidence) | cli | pass |  |
| 72-serve-d-start | serve start on 127.0.0.1:36077 (mode=block) + admin pairing | cli+http | pass |  |
| 73-positive-session | positive: session-scoped SEC verifies without a task id | http | pass |  |
| 74-grant-readback | read grant before revocation | http | pass |  |
| 75-grant-revoke | negative (c) setup: revoke the install grant (HTTP admin) | http | pass |  |
| 76-negative-grant-revoked | negative (c): after grant revocation the call must not be allowed or verified | http | pass | denied at the credential-auth layer (grant reference re-validated on every request); the SEC grant-digest gate is shadowed here — see report |
| 80-receipts | receipt chain reads and verifies over HTTP | http | pass |  |
| 81-serve-d-stop | serve stop (SIGTERM, drain) | process | pass |  |
| 82-verify-chain | offline receipt chain verification (CLI) | cli | pass |  |

## 证据分层与限制

- **组件测试**：`internal/skillcontext`、`internal/receipt` 的正负向单测属于组件级（mock 依赖），
  本报告不重复其结论；两轮发现的矛盾正是组件层照不到的真实装配关系。
- **本地服务级活体（本报告层级）**：真实候选二进制、真实状态目录与签名、真实 HTTP 服务、
  真实 CLI 生命周期；适配器调用以**等价 HTTP 重放**（ri- 作用域凭据 + 与适配器相同的
  /v1/decide 载荷）代替宿主内插件进程。**未运行真实模型会话**，未在 Hermes 宿主进程内执行工具。
- **原生宿主门槛（仍未完成）**：未在原生 Hermes 插件进程中完成 pre_tool_call → decide → 执行的
  真实链路；按任务书，R01 原生门槛保持未完成，不得以本报告冒充。
- 威胁范围声明（逐字保留自 N05 规格 §1）：本设计抵御的威胁是**模型可控输入与其他 Skill 的
  文本/调用层伪造**（复制 claim、摘要、grantID、session/task 标识、SEC ID）。它不抵御：已攻陷的
  宿主进程（可绕过钩子）、同 UID 恶意本地代码（可读 0600 凭据文件并冒充适配器发起整个请求）、
  OS 层沙箱逃逸。desktop-same-uid 边界见 dev-spec §6。
- 其他限制：单一平台（hermes）单一实例；「同 Agent 两 Skill 权限借用」交叉场景未覆盖。
