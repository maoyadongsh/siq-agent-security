# OpenShell 链接：siq-research-engine 智能分析助手（siq_analysis）隔离网关，2026-09-26

本轮由使用者指定受控目标：**siq 投研决策引擎（`siq-research-engine`）的智能分析助手**所适配的 OpenShell 网关。
本次只做**链接与只读读回**；未启动、未重启、未停止任何网关，未创建/删除沙箱，未 `policy set`。

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

对照 `docs/development/ux-openshell-live-preview-e149-validation-20260923.md`：该文档用**同一条命令、同一个目标**记录了
**8 项检查全通过**（前/后 revision 均为 2）。而引入该闸的 `app/target_authority.py` 是**未跟踪新文件**
（mtime 2026-09-25 16:34），晚于 E149 文档（2026-09-23 发布）。
即：**E149 的 8/8 在当前候选上已不可复现**，其证据已陈旧；这正属于交接文档 §5 要回答的
「同候选非退化证据」缺口，本文件只如实记录，**不修改**任何相关路径（`target_authority.py`、
`deployment_preview.py`、该工具、E149 文档**四条路径均不在本轮冻结允许清单内**）。

> 自查更正：R09.12 的前置方案里把 `openshell-preview-live-check.py` 写成"清单内既有工具"，
> **该表述有误**——经逐条比对，它**不在**允许清单 30 条之内。已在执行记录 R09.13 更正。

## 六、待许可的下一步（§3.2 逐次许可）

真正会把链接推进到「真实部署闭环」的动作是 `--live`，它**会真实修改**智能分析助手沙箱的网络段：

- 目标：`siq-analysis-canary-27d1289f98fa`（或使用者另指定）
- 命令：`SIQ_AS_OPENSHELL_ENV_SH=... .venv/bin/python scripts/openshell_compat_check.py --live --sandbox <name>`
- 变更：对该沙箱提交一条网络 allow 段（`example.com:443`，rule_name `siq-compat-live-check`，`enforcement_mode=block`），
  `policy_id=siq-openshell-compat-live`
- 回收：同一次执行内 `rollback` 到上一 revision，并打印回滚后 revision；沙箱不删除（对方资产）
- 产出上限：`readback_verified`
- 已知风险：该沙箱是**分析助手 canary**（对方在用的资产），变更期间其网络允许集会短暂多出一条样例 endpoint

在得到明确许可前，本轮**不执行**该命令。
