# OpenShell 链接：siq-research-engine 智能分析助手（siq_analysis）隔离网关，2026-09-26

本轮由使用者指定受控目标：**siq 投研决策引擎（`siq-research-engine`）的智能分析助手**所适配的 OpenShell 网关。

阅读顺序：**§一～§六 全部是只读**（未启动/重启/停止任何网关，未创建/删除沙箱，未 `policy set`）；
**§七 是使用者逐次许可后的一次受控写入闭环**（`policy set` → 读回 → 回滚），回收结果见该节，原始留痕见 `06-`；
**§八 是把 §五 那条结构性失败修掉的工具改动，全部在合成件上验证**（不碰任何真实网关），原始留痕见 `07-`。
**§九 与本目录主题不同**：它是 R09.17b 的**只读导入闭包核验**（`import-closure-check.py`）留痕——那条线
本来不属本目录，但被 §五 的工具改造过程撞出来后，原始留痕就一起放在这里，见 `08-`。
**§十 是 D-9 的只读结构核查**（只判定"策略模型是否支持按 binary 路径归因"）：全部只读，
零状态变更，**不** upload/exec/policy set，原始留痕见 `10-`；它同时**更正**了 §六/§七 里
原记的"8 条含 `_provider_siq_*`"口径（实测为 **4 条规则 / 7 个 endpoint**）。
**本分支 HEAD 检出无法 `import app.main`**（§九 / 执行记录 R09.17）。

链接方式沿用仓库既定契约（`AGENTSHIELD.md:76`）：设
`SIQ_AS_OPENSHELL_ENV_SH=/home/maoyd/siq-research-engine/scripts/openshell/env.sh`，不改对方仓库任何源码/配置/数据库。

## 一、本轮实际执行的命令

```bash
# 1) 我方兼容矩阵检查（只读：probe + sandbox list 解码路径）
cd /home/maoyd/siq/siq-agent-security/apps/control-api
SIQ_AS_OPENSHELL_ENV_SH=/home/maoyd/siq-research-engine/scripts/openshell/env.sh \
  .venv/bin/python ../../scripts/openshell_compat_check.py

# 2) 对方 env.sh 内钉住的 CLI 直连只读读回（不 source 进本会话，仅子壳）
cd /home/maoyd/siq-research-engine/scripts/openshell
source ./env.sh && "$SIQ_OPENSHELL_BIN" sandbox list
source ./env.sh && "$SIQ_OPENSHELL_BIN" policy get <sandbox> -o json
source ./env.sh && "$SIQ_OPENSHELL_BIN" policy list <sandbox>
```

## 二、事实（全部为读回，无自述）

| 项 | 读回值 |
| --- | --- |
| 网关名 / 端口 | `siq-openshell-dev` / `127.0.0.1:17671` + `172.23.0.1:17671`（health `127.0.0.1:17672`，现均 LISTEN） |
| 网关进程 | `var/openshell/toolchains/v0.0.83/bin/openshell-gateway`（pid 3704433，2026-09-22 00:29 启动，`ss -ltnp` 证实 17671/17672 三个监听全归它；**对方仓库既有进程，本轮未启停**） |
| 另一进程 | `var/openshell/build/v0.0.83/gateway-request-candidates/6e9baaac…/openshell-gateway`（pid 3010490，2026-09-22 20:13 启动，**不占** 17671/17672）——本文件不据它做任何结论 |
| CLI 版本 | `openshell 0.0.83`（与 `scripts/openshell_compat_matrix.json` 的 `v0.0.83` 条目同版本） |
| 兼容矩阵 | **8/8 一致**（`dynamic_network_update`/`static_filesystem`/`static_process`/`landlock`/`revision_support` = true；`interceptor`/`provider_credential_injection` = false；`sandbox_list_decodable` = false） |
| 沙箱 | `siq-analysis-canary-27d1289f98fa`（2026-09-21）、`siq-analysis-canary-d4a890ec23d3`（2026-09-21），均 `Ready` |
| 沙箱策略 | 两者均 `version=2`、`policy_source=sandbox`、`scope=sandbox`，网关自报 `status: "effective"`；各自 revision 见 `03-canary-policy-readonly.txt` |

与 2026-09-05 那次接入（`docs/evidence/agentshield/openshell-siq-research-engine-2026-09-05/`）的差别：
当时 L3 只有**握手**成立、**无可做读回闭环的分析沙箱**；本次分析助手侧**已有两个 `Ready` 的 canary 沙箱**，
链接面从「握手」推进到「有可读回的真实目标」。

## 三、没有做的事（边界）

- 未执行 `openshell gateway start/stop`、未操作宿主 systemd、未改对方仓库。
- 未 `policy set` / `policy update` / `sandbox create|delete|exec`——**没有任何真实权限变更**。
- 未读取对方 `env.sh` 的取值（只读变量名，避免读到令牌/机密），未读任何私钥、真实 `.env`、种子。
- 未产出 `effective` 或 `enforcement_verified`：上表 `status: "effective"` 是**网关侧对自身策略的自报字段**，
  不是我方产出的授权事实，本文件不据此宣称任何策略"已生效"。

## 四、诚实的天花板（为什么这还不能算 A7）

`enforcement_verified` 是**刻意保留值**，全后端无生产者：

- `apps/control-api/app/adapters/openshell/base.py:52-58`：`enforcement_verified` 需要**真实行为 fixture 证据**，
  「当前所有后端实现均无行为 fixture 通道，禁止产出该级别」。
- `apps/control-api/app/adapters/openshell/cli_backend.py:726-732`：`verify()` 只比对读回配置
  （revision + 网络允许集），**通过也只标 `readback_verified`**。

即：即便对上面任一 canary 沙箱执行 `openshell_compat_check.py --live`，能得到的上限是
**`readback_verified`**（真实 `policy set` → 读回 → 回滚闭环），**不是** `enforcement_verified`。
另外 `--live` 里的 `expect_deny: ["denied.invalid:443"]` 是**固定兼容样例**，其"拒绝"结论来自
*不在允许集里*，**不是**一次真实拒绝行为观测——不得把它当作行为验证。

CLI 侧的 `openshell policy prove`（`--policy` + `--credentials` + `--registry`）是对策略 YAML + 能力注册表的
**静态推演/反例搜索**，也不构成行为 fixture 通道。

## 五、用既有只读预览工具真跑该目标：**失败，且是结构性失败**（新发现）

`scripts/enterprise-experience/openshell-preview-live-check.py`（E149 验收工具）按它自己文档里记的命令跑同一目标：

```bash
apps/control-api/.venv/bin/python scripts/enterprise-experience/openshell-preview-live-check.py \
  --cli /home/maoyd/siq-research-engine/var/openshell/toolchains/v0.0.83/bin/openshell \
  --endpoint https://127.0.0.1:17671 \
  --xdg-root /home/maoyd/siq-research-engine/var/openshell/xdg \
  --target siq-analysis-canary-27d1289f98fa \
  --out-dir /tmp/openshell-link-20260926/preview-live-readonly-<ts>
```

结果：**rc=1**，在第 136 行 `post('/deployment-preview', body)` 处断言失败（期望 200，实际 **409**）。
探针本身是好的——`probe()` 成功：`handshake_verified=True`、`gateway_version=0.0.83`、
`endpoint_fingerprint=6225b824…28441`。为拿到正文，用 `/tmp` 下一次性只读复现脚本
（不落仓、不改任何文件）重放同一序列，得到：

```text
PREVIEW status: 409
PREVIEW body: {"detail": "deployment_target_authority_unverified"}
commands executed: ['gateway', 'status', '--version', 'gateway', 'status', '--version']
```

**命令列表里根本没有 `policy get`** —— 失败发生在读目标策略**之前**，不是网关状态问题。根因（读代码逐行）：

| 环节 | 事实 |
| --- | --- |
| 预览必经 `prepare_deployment` | `app/routers/policies.py:436`，openshell-cli 分支在 `:534-536` **无条件**调 `require_target_authority(binding, tenant_id, caps)` |
| 该闸强制算子授权目录 | `app/target_authority.py:136-151`：读 `SIQ_AS_OPENSHELL_TARGET_AUTHORITY_FILE` 指的本机绝对路径；缺该变量即 `target_authority_unconfigured` → **409 `deployment_target_authority_unverified`** |
| 该工具**不可能**提供它 | 工具在 `:58-62` 把 `os.environ` 清成白名单 `PATH/HOME/USER/LANG/LC_ALL` 后才设自己的变量，**从未**设 `SIQ_AS_OPENSHELL_TARGET_AUTHORITY_FILE`；因此无论外部怎么设都会被清掉 |
| 结论 | **在当前候选上，该工具按自身代码不可能通过预览断言**——不是这次配置不对，是构造性失败 |

> **2026-09-26 追加（第二层根因，比上面这条更深）**：把 `SIQ_AS_OPENSHELL_TARGET_AUTHORITY_FILE` 加进工具的白名单**并不能**恢复 E149——
> 只是从"变量被清掉"变成"目录里找不到这条授权"。`authorize_runtime_target`（`target_authority.py:125-133`）对授权目录做**精确元组相等**判定：
> `(tenant_id, environment_id, asset_id, agent_instance_id, endpoint_fingerprint, gateway_name_sha256, backend_target_id)`，**没有通配**。
> 而该工具的 `environment_id`（`POST /environments` 服务端生成）、`asset_id`/`agent_instance_id`（工具在 `:109-118` 内 `flush()` 生成）**都是运行期新生成的**，
> 算子**不可能在运行前**写进目录。即：**要恢复 E149，必须让工具的身份 id 变成算子可预声明的输入**（工具改从算子目录里读它要用的那组 id，而不是自己现造），
> 这超出了"放行一个环境变量"的范围。本文件只如实记录该约束，**未改任何代码**。

对照 `docs/development/ux-openshell-live-preview-e149-validation-20260923.md`：该文档用**同一条命令、同一个目标**记录了
**8 项检查全通过**（前/后 revision 均为 2）。而引入该闸的 `app/target_authority.py` 是**未跟踪新文件**
（mtime 2026-09-25 16:34），晚于 E149 文档（2026-09-23 发布）。
即：**E149 的 8/8 在当前候选上已不可复现**，其证据已陈旧；这正属于交接文档 §5 要回答的
「同候选非退化证据」缺口，本文件只如实记录，**不修改**任何相关路径（`target_authority.py`、
`deployment_preview.py`、该工具、E149 文档**四条路径均不在本轮冻结允许清单内**）。

> 自查更正：R09.12 的前置方案里把 `openshell-preview-live-check.py` 写成"清单内既有工具"，
> **该表述有误**——经逐条比对，它**不在**允许清单之内（当时 30 条，现 39 条，两版均不含它）。已在执行记录 R09.13 更正。

## 六、`--live` 的前置核查：**当前候选上不能执行**（2026-09-26 追加）

原计划把链接再推进一步的动作是 `--live`（真实 `policy set` → 读回 → 回滚）。**本轮未执行它**，原因是先做前置核查时发现该动作在**当前候选**上有两个构造性缺陷——两个都不是配置问题：

**缺陷 1：写面是「整段替换」，不是「追加一条」。**（本节此前写成"短暂多出一条样例 endpoint"，**该表述有误，现更正**）

`apps/control-api/app/adapters/openshell/cli_backend.py:584-591`：

```python
merged = clone_policy(current.policy)
network = network_rules_to_gateway(compiled.artifact["network_policies"])
if network:
    merged["network_policies"] = network   # 整段替换
```

`_live_check` 的 `desired` 只含 1 条 `example.com:443` 的 allow 规则，因此写入后该沙箱的 `network_policies` 段**只剩这一条**——该 canary 现有的 **4 条**内部服务网络规则（`siq_agentshield_relay`、`siq_data_broker`、`siq_egress_guard`、`siq_internal_services`，共 **7 个 endpoint / 7 条 binaries**；**口径已由 `10-` §5 更正**，原写的"8 条含 `_provider_siq_*`"在实测读回里不存在）在变更窗口内**全部消失**。若分析助手此刻正在该沙箱内运行，其内部服务（relay / data-broker / egress-guard / internal-services）调用会被一并阻断。

**缺陷 2：脚本自己没有回滚能力。**（因此"同一 run 内回滚"作为回收手段**不成立**）

`scripts/openshell_compat_check.py:139` 的调用形态是 `backend.rollback(sandbox, receipt)`，**不传 `authorizer`**；而 `cli_backend.py:807-808`：

```python
if authorizer is None:
    raise VerificationFailed("openshell_rollback_authorizer_required")
```

隔离实测（`/tmp/a7-precheck/rollback_reachability.py`，对网关只有一条只读 `policy get --full`）：

```text
[call] backend.rollback(target, receipt)   # 与 _live_check:139 完全同形：不传 authorizer
[result] VerificationFailed: openshell_rollback_authorizer_required
```

回滚在**写之前**就失败，会被 `_live_check` 的 `except Exception` 打印成「FAIL: 回滚失败」并把 `ok` 置 `False`（退出码 1）——**而 `policy set` 已经发生**。即：执行 `--live` 会把该 canary 留在「网络策略只剩 `example.com:443`」的状态，直到有人手工恢复。

**因此本轮拒绝执行 `--live`**（不是执行失败留痕）。完整原始判定见 `05-live-prereq-blocked.txt`。

若后续要继续，本轮已捕获但**未使用**的恢复材料：BEFORE 全文（`policy get --full`，version 2）+ 网关侧 `policy list` 仍保留 version 1/2；手工恢复 = 用 BEFORE 文档 `policy set` 回该沙箱，**这本身也是一次真实权限变更，同样需要该次授权**。

**要往下走的三条路**（任选，均超出本轮已获许可范围）：

1. **先修脚本再加作者**：给 `_live_check` 补上 `rollback(..., authorizer=...)`（作者从私有操作记录构造，拒绝请求正文覆盖）并加"写后必回滚"的断言，使其**先具备回收能力**再跑；
2. **换一个专用一次性沙箱**：由目标侧提供/授权一个与生产隔离的复制沙箱，变更窗口内的爆炸半径与该 canary 无关；
3. **停在只读**：链接层维持现状，`--live` 保持未执行。

**产出上限仍然是 `readback_verified`**：即便走 1 或 2，`verify()` 只比对读回配置，**不产生 `enforcement_verified`**，其 `expect_deny` 也是**固定兼容样例**（"拒绝"结论来自*不在允许集里*），**不是**一次真实拒绝行为观测。

## 七、走路径 1：补 authorizer 后的真实闭环**已执行**（2026-09-26 追加，原始留痕见 `06-`）

使用者在第二轮问询中选定**路径 1（先补 authorizer 再跑）**。补齐内容：

- `scripts/openshell_compat_check.py` 的 `_live_check`：从**私有操作记录**构造 `RollbackAuthorization`（只认本次 `operation_id` + `target`），
  `finally` 里**必定**尝试回滚，回滚后**重新读回**并要求 digest 等于写入前 BEFORE；后端私有基线与我方 BEFORE 不一致时**只告警不拒绝回滚**。
- 新增 `scripts/enterprise-experience/test_openshell_compat_live.py`（8 条隔离单测，全过；负对照指向补齐前的脚本版本时 5/7 失败）。

**执行中才暴露的第三条缺陷**：fixture 的网络规则缺 `binary_paths`，`policy_safety.validate_network_rules` 在 `compile()` 阶段即抛
`openshell_network_binary_required`——首跑**一个字节都没写**。这条 `--live` 路径此前**从未真正写成功过**，
也正因如此 §六 的写面风险此前没被实测撞上。补上 `_LIVE_FIXTURE_BINARY` 后重跑成功。

**执行结果**（退出码 0）：`BEFORE revision=2（7 条归一化网络规则）` → `policy set 成功 revision 3` →
`读回验证通过（level=readback_verified）` → `已回滚 revision 4（result=restored）` → `回滚后读回 digest 与 BEFORE 相同`。

**独立复核**（对方 CLI，只读，可复现）：网关 `siq-openshell-dev` `Status: Connected` / `Version: 0.0.83`；
`policy list` 显示 v4 `fed6cc8072d1` **Loaded**，v3 `dfdefc3465ef` Superseded（= 本次写入，此前不存在的修订），
**v4 的 hash 与 v2 完全相同**；`policy get --rev 2 --full` 与 `--rev 4 --full` 的差异**只有头部 4 个元数据字段**
（Version / Status / Created / Loaded），去掉头部后两份载荷 SHA-256 相同（`3126e203…`）⇒ **策略载荷逐字节相同**。

**顺带得到两个实测确认**：

1. §六 缺陷 1 的「**整段替换**」判定由**读代码**升级为**实测**：`--rev 3 --full` 的 `network_policies` 段**只剩写入的那一条**，
   全文搜不到原有 `siq_agentshield_relay` / `siq_data_broker` / `siq_egress_guard` / `siq_internal_services` 条目
   （原写的 `_provider_siq_*` 属误记，**已由 `10-` §5 更正**：该名单在本目标任何可达读回里都不存在）；
2. 兼容矩阵里冻结的 `sandbox_list_decodable: false` 在本次被独立复现（`sandbox get` 报 `Sandbox.id … not UTF-8 encoded`）。

**边界（不要越读）**：本次**未**产生 `enforcement_verified`，天花板仍是 `readback_verified`；
**未**做任何真实 deny 观测；`expect_deny` 仍是固定兼容样例。`readback_verified` 只说明"网关读回的配置与我方提交的一致"，
**不**说明"运行时真的按它执行了"。终态：canary 网络策略恢复原状，v3 作为**可审计历史修订**留在网关，未删除。

## 八、把 §五 的结构性失败修掉：预览工具改从算子授权目录读身份 id（2026-09-26 追加）

§五 的结论是「在当前候选上，该工具按自身代码**不可能**通过预览断言」。本轮把它修了，
改动与逐条留痕见 `07-preview-tool-operator-authority-2026-09-26.txt`。摘要：

- 新增必填 `--target-authority`（算子签发的 `enterprise-runtime-target-authority/v1` 目录）与
  可选 `--assignment-id`；tenant / environment / asset / agent_instance 全部改从该目录读取，
  再显式落隔离库，使门禁的**精确元组相等**判定有可能成立；
- 读目录复用门禁自己的 `_read_authority_bytes` / `_unique_object` / `TargetAuthority`，
  不另写一套判定；
- 新增 5 条隔离测试（合成 CLI + 合成目录，不联网）；**负对照**：改动前的工具在同一合成 bench 上
  仍在同一行、以同一症状失败（`('/deployment-preview', 409)`，rc=1）；
- **顺带更正 §五/本节的机制描述**：上下文变化时被拒的断面**已经换了**。实测得到的判别码是
  `deployment_target_authority_unverified`（授权闸在 `_prepare` 内先跑），而不是
  `deployment_preview_changed`（`deployment_preview.py:252`，本路径不可达）。性质仍在，位置更靠前；
  工具检查项已据此改名为 `changed_context_refused_without_writes`，并把实际判别码记进
  `changed_context_detail`。

**这一节仍不构成 E149 的恢复**：合成跑法下 `real_gateway` 只是工具常量；真跑需要**算子签发**一条授权
条目（由执行者代签 = 自己制造授权，越界）。E149 文档记录的 8/8 即使目录完全正确也**不可逐字复现**
（断言观测码必为授权闸的码）。天花板不变：无 `enforcement_verified`、无真实 deny 观测。

## 九、顺带撞出来的 R09.17b：本分支的导入闭包缺口（只读核验，2026-09-26 追加）

§八 的**负对照**本想在 `git archive HEAD` 的干净检出里跑改动前的预览工具，结果**那棵树连导入都做不到**：
`ImportError: cannot import name 'DiscoveryScheduleRecord' from 'app.models'`。由此单独立项 **R09.17**，
并在使用者就 D-8 选定 **C（只诊断不修）** 后落地为**可重复的只读核验** R09.17b。

- 工具 `scripts/enterprise-experience/import-closure-check.py`（**未接线**、不参与门禁）：
  `git archive <ref> apps/control-api` 到临时树 → 在只指向该树的白名单环境里试 `import app, app.main`
  → 缺模块就从**工作树**定位补入再试。**只读**：不写仓库、不切共享工作树、不提交；子进程环境是白名单
  （含 `SIQ_AS_DEV=1` 合成身份），不读 `.env`/私钥/种子。
- **逐 ref 实测**：`HEAD`(`033f50d`) / `6ba1f7c` / `ad3116e` → `import_closure_open`，补件 **25** 条且**逐条相同**；
  负对照 **`ebaaf3b`（父提交 / `main`）→ `import_closure_closed_at_ref`、0 补件、退出码 0**。
  即：缺口生于分支**第一个**提交，此后每个提交都带着它、从未恶化；工具不是"无论给什么 ref 都报缺口"。
- **补件构成**：3 条已跟踪被修改（`app/models.py` `+252/-3`、`deployment_preview.py` `+109/-5`、
  `deployment_submission.py` `+39/-16`）+ 22 条未跟踪。**这更正了首次手工 graft 的目测（「1+24」）**，
  总数 25 不变——`deployment_preview.py`/`deployment_submission.py` **在 HEAD 里存在**，只是工作树版本更新。
- **天花板**：只说明「该 ref 的导入面是否自足」；**未**证明补入后控制面能启动/迁移能过/测试能收集，
  **未**证明这 25 条「应该」并入（它们是并作者在飞的工作），不使任何门禁变绿，不产生 `enforcement_verified`；
  结论**绑定 ref sha**，分支再提交必须重跑。原始留痕见 `08-import-closure-check-2026-09-26.txt`。

## 十、D-9 只读结构核查：模型**支持**按 binary 归因，且目标自身在用（2026-09-26 追加）

**授权依据**：使用者选定 D-9 的「先只读结构核查」——只判定一个结构性问题：网关的策略模型
**是否支持**按 binary 路径限定网络规则。**不** upload、**不** exec、**不** policy set。

**结论（声明面）**：两个 canary 的 `--full` 载荷**逐项相同**——`network_policies` 下规则只有
`name`/`endpoints`/`binaries` 三个键，实测 **4 条规则 / 7 个 endpoint / 7 条 binaries，
缺 binaries 的规则 0 条**。其中 `siq_egress_guard` 是 **1 个 endpoint × 4 个二进制**
（python/curl/git/node），`siq_internal_services` 是 **4 个 endpoint × 1 个二进制**——
**endpoint 集合与 binary 集合是两个独立维度**，这正是"按 binary 归因"的形态。
⇒ 行为 fixture 的**主方案在结构上是有意义的**，不属于"可能因模型不支持而整体作废"那一类。

**交叉验证**：R09.15 当年实测"现存条数 = 7"（与适配器展开口径一致），本次另写的结构清点脚本
独立得到 `endpoints 合计 = 7`——两条不同解析路径同值。

**两条硬结果（只读路走死了）**：① `logs` 报
`failed to decode Protobuf message: Sandbox.id … not UTF-8 encoded`，即兼容矩阵里
`sandbox_list_decodable: false` 的**同一条**冻结缺陷 ⇒ **该版本上网关的"运行期日志/沙箱状态"
只读通道不通**，且该命令在管道下出现过 `rc=0` 而错误正文照旧 ⇒ **退出码不可单独作判据**；
② `policy get --global --full` 返回 `NotFound: no global policy revision found` ⇒ 策略面**只有沙箱级**。
故**执行面**（运行期是否真的按 binary 判定）**不可能**靠只读回答，仍需写入型探针。

**一处更正**：原记的「network_policies 条目名 8 条（含 4 条 `_provider_siq_*`）」在 rev1/rev2 与
另一个 canary 三方读回里**都不存在**（`_provider_` 命中 0 次），且它指向的 `03-` 里只有 `-o json`
元数据、没有 `--full` 正文。已在 `05-` 顶部、本文件 §六/§七、交接文档 R09.14 行、
行为 fixture 方案 §7 逐处更正为 **4 条规则 / 7 个 endpoint**；**R09.14/R09.15 的结论不变**
（依赖"整段替换"这一代码事实与 `--rev 3` 实测，与原有条目计数无关）。

**没有做什么**：未 upload、未 exec、未 policy set、未启停网关、未建删沙箱、未改对方仓库；
本次零状态变更。**天花板**：拿到的是**声明面**——"schema 里有且被使用" **≠** "运行期真的按它判定"；
不产生 `enforcement_verified`；结论**绑定**本次读到的修订与哈希（rev1/rev2、`Active: 4`、
`hash=fed6cc8072d1`）。原始留痕见 `10-d9-structural-readonly-2026-09-26.txt`。
