# OpenShell 链接：siq-research-engine 智能分析助手（siq_analysis）隔离网关，2026-09-26

本轮由使用者指定受控目标：**siq 投研决策引擎（`siq-research-engine`）的智能分析助手**所适配的 OpenShell 网关。

阅读顺序：**§一～§六 全部是只读**（未启动/重启/停止任何网关，未创建/删除沙箱，未 `policy set`）；
**§七 是使用者逐次许可后的一次受控写入闭环**（`policy set` → 读回 → 回滚），回收结果见该节，原始留痕见 `06-`。

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

`_live_check` 的 `desired` 只含 1 条 `example.com:443` 的 allow 规则，因此写入后该沙箱的 `network_policies` 段**只剩这一条**——该 canary 现有的 **8 条** provider/内部服务策略（`_provider_siq_kimi_coding`、`_provider_siq_minimax_cn_pool`、`_provider_siq_stepfun`、`_provider_siq_tavily_search`、`siq_agentshield_relay`、`siq_data_broker`、`siq_egress_guard`、`siq_internal_services`，读回见 `03-` 与本目录 `05-`）在变更窗口内**全部消失**。若分析助手此刻正在该沙箱内运行，其模型调用（Kimi/MiniMax/StepFun）、Tavily 检索、内部服务与 egress guard 会被一并阻断。

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
   全文搜不到任何原有 `_provider_siq_*` / `siq_egress_guard` / `siq_data_broker` 条目；
2. 兼容矩阵里冻结的 `sandbox_list_decodable: false` 在本次被独立复现（`sandbox get` 报 `Sandbox.id … not UTF-8 encoded`）。

**边界（不要越读）**：本次**未**产生 `enforcement_verified`，天花板仍是 `readback_verified`；
**未**做任何真实 deny 观测；`expect_deny` 仍是固定兼容样例。`readback_verified` 只说明"网关读回的配置与我方提交的一致"，
**不**说明"运行时真的按它执行了"。终态：canary 网络策略恢复原状，v3 作为**可审计历史修订**留在网关，未删除。
