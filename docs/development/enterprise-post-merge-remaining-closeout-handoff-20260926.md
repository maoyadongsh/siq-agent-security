# 企业主线合并后剩余开发收口 — 交接文档（2026-09-26）

- 任务书：[enterprise-post-merge-remaining-closeout-taskbook-20260926.md](enterprise-post-merge-remaining-closeout-taskbook-20260926.md)
- 仓库：`/home/maoyd/siq/siq-agent-security`
- 基线：`main` = `origin/main` = `2ab1ce2546b616675757ebc59244086aa094bbc0`
- 状态：**未提交、未推送、未部署，待主开发者复核**

> 本文件只交付事实：改了什么、证明到什么程度、哪些没跑、哪些没做。

---

## 1. 交付范围（F01 / F02 / F03）

### F01 — Edge CLI 只读发现 `confirm-discovery-schedule --discover`

新注册设备在**不知道 schedule_id** 的前提下，可只读发现"本机是否有等待确认的周期计划"。

- 参数来源严格四选一：`--intent FILE | --schedule-id ID | --discover | --resume`；任意组合冲突或全部缺失均在准备阶段拒绝。
- 发现阶段**只有 GET**：不发 POST、不写日志、不写回执、不写任何 `discovery-schedule*` 文件。
- 零 / 一 / 多三条固定分支，无任何自动选择；`integrity_failed` 一律失败关闭。

新增文件：

| 文件 | 作用 |
| --- | --- |
| `edge/agent/discovery_schedule_list_linux.go` | 待确认列表的严格分页读取与投影（精确字段集、拒绝额外字段/重复键/`null`/尾随 JSON、字节上限、拒绝重定向、条目严格升序并绑定请求 cursor、next_cursor 精确绑定末项、条目绑定复验） |
| `edge/agent/discovery_schedule_list_linux_test.go` | 24 项负向解析模式、畸形正文、状态/网络失败、有界性、完整性失败关闭、只读断言、取消 |

修改文件：

| 文件 | 改动 |
| --- | --- |
| `edge/agent/confirm_schedule_linux.go` | 新增 `--discover` 源分支、`reportPendingScheduleDiscovery`、`listPendingScheduleCandidates`、帮助文本重写 |
| `edge/agent/main.go` | 用法行加入 `--discover` 与其只读边界说明 |
| `edge/agent/setup_enterprise_linux.go` | `--help` 增加"组织创建计划 → 设备发现 → 独立确认"提示；保持 `enterprise-setup/v1` 既有 NDJSON phase/status 集合和 service 最终记录不变 |
| `edge/agent/setup_enterprise_linux_test.go` | 锁定四条既有进度记录及其顺序，防止帮助性下一步提示演变成未升版 wire phase |
| `edge/agent/confirm_schedule_linux_test.go` | 冲突源拒绝、帮助边界、零/一/多端到端（httptest 真实 HTTP）、完整性失败只列受控 ID、PTY 交互确认恰好一个计划、setup 指引 |
| `apps/control-api/app/routers/discovery_schedule_pending.py` / 对应测试 | 待确认列表把异常的 `pending_confirmation + revision>0` 归入 `integrity_failed`，与设备首次确认固定 revision=0 的合同保持一致 |

行为要点：

- **0 项**：输出固定文案（本机无待办、未创建请求、周期发现未启用、请组织控制台创建后重试）；纯查询返回成功，带 `--interactive` 或摘要确认参数时返回失败，因为实际未完成确认；两者都**不声称**周期接入完成。
- **1 项且无完整性失败**：进入既有本地预览路径，完整展示设备/组织/环境/范围/周期/预算/有效期/意图摘要；确认仍需真实终端 `--interactive`（默认取消，管道输入不构成同意）或精确 `--confirm-intent-sha256`。
- **多于 1 项**：只打印有界候选（`schedule_id` / `intent_sha256` / `status` / 起止时间），要求改用精确 `--schedule-id`，返回失败；**绝不自动挑选**。
- **任一页 `integrity_failed`**：失败关闭，只输出受控 `schedule_id` 与固定原因，不回显上游正文。
- 发现**不是授权**：不新增"默认确认""首项自动确认""复用安装范围"等任何捷径。

### F02 — OCSF 导出截断事实声明 `X-SIQ-Export-Truncated`

`GET /api/v1/export/ocsf` 现在按 `limit + 1` 探测，正文最多 `limit` 行，并在**所有成功响应**上带 `X-SIQ-Export-Truncated: 0 | 1`。

| 文件 | 改动 |
| --- | --- |
| `apps/control-api/app/routers/export.py` | `probed = ... limit(limit + 1)`；`rows = probed[:limit]`；`truncated = len(probed) > limit`；响应头新增该字段；审计 `summary.count = len(rows)`；模块 docstring 增补截断与"非归档"不变量 |
| `apps/control-api/app/tests/test_ocsf_export_closeout.py` | 新增 6 个截断测试；并在既有拒绝路径与失败关闭路径补 `assert "x-siq-export-truncated" not in resp.headers`，空结果补 `== "0"` |

不变量：

- 探测行**只**用于计算响应头：不进正文、日志、审计、错误。正文行数任何情况下 ≤ `limit`。
- 审计 `count` 是**实际返回条数**，不是探测条数；`summary` 仍精确为 `{class, count, since}`。
- 保留 `Cache-Control: no-store`、`application/x-ndjson`、每行一个完整 JSON、末尾换行、空结果空正文、时间升序再按 ID 稳定排序。
- 失败路径（403 / 422 / 审计或提交失败）**不返回**该头，也不产生"成功导出"审计。
- **不**新增删除、归档、游标、全量导出或 `published` / `verified` 状态。

### F03 — 合同、README、runbook 同步

| 文件 | 改动 |
| --- | --- |
| `packages/contracts/enterprise-ocsf-export.v1.md` | **新建**：端点、权限、参数、`since` 语义、NDJSON、`no-store`、截断头语义、导出审计、失败行为、非归档边界、不做事项 |
| `packages/contracts/enterprise-discovery-schedule.v1.md` | **追加**"设备 CLI 发现增量（只读）"一节（append-only，未改动既有段落语义） |
| `packages/contracts/enterprise-discovery-schedule-pending-list.v1.md` | 修正过期表述：该端点**已**随共享应用注册并对外可达（`app/main.py:182`），删除"尚未注册/接线前不可达"的错误描述 |
| `packages/contracts/README.md` | 合同清单新增 `enterprise-ocsf-export.v1.md` 一行 |
| `README.md` | 新增"新注册设备的周期发现接入（两步）"小节，给出 `--discover` → `--discover --interactive` 两阶段示例；更新部署段落中的周期调度与导出截断表述 |
| `README.en.md` | 新增 "Enterprise Edge: new device periodic discovery (two steps)" 等价小节；同步周期调度收口与导出截断事实（中英结论一致） |
| `docs/enterprise-production-runbook-v1.md` | 新增 §9.1：0 项 / 多项 / 完整性失败 / 恢复日志 / 服务起不来 / 导出截断的排查顺序 |

---

## 2. 安全不变量（本次实现实际遵守）

- `tenant_id` / 环境 / 设备只来自验证身份；发现与导出都不接受客户端指定的租户/环境/设备参数。
- 可见性不是授权：**发现 ≠ 确认**，**预览 ≠ 执行**，`active` / `0 项` / `Truncated=0` 都不构成业务授权或保护生效证明。
- 未知 / 缺失 / 截断 / 完整性失败一律**诚实呈现**，不转换为空、0 或成功：`integrity_failed` 显式列出而非静默跳过；`X-SIQ-Export-Truncated` 显式声明而非让客户端猜。
- 取消 / 预览 / 发现阶段**零业务写入**（无任务、预约、权限、审计、outbox、确认日志或回执）。命令会创建或复用既有 `tasks.lock` 做本机互斥；该文件不含业务事实。
- 高风险写入的审计失败**失败关闭**（导出审计失败 → 无正文、无头、不提交）。
- 上下文取消后不返回成功：发现的三处取消点均有测试。
- 不通过删除测试、放宽解析、`strings.Trim`/大小写归一或 `String()` 转换来掩盖合同违背。
- 未新增依赖、未改 lockfile、未做无关格式化或重构。

---

## 3. 已执行的验证（命令与结果）

### 3.1 F01 聚焦（`edge/agent`）

```bash
GOPROXY=off go test -race -count=1 -run 'Test.*(PendingSchedule|DiscoverySchedule|ConfirmSchedule|SetupEnterprise)' ./...
GOPROXY=off go vet ./...
gofmt -l .
```

- 验收修复后聚焦用例：**21 个顶层用例 / 89 条 PASS（含子用例）全部通过**（`-race`）。
- `go vet ./...`：无输出（通过）。
- `gofmt -l .`：无输出（本次修改文件均干净；未顺手格式化无关文件）。

### 3.2 F02 聚焦（`apps/control-api`）

```bash
uv run --no-sync pytest -o addopts='' -q app/tests/test_ocsf_export.py app/tests/test_ocsf_export_closeout.py
uv run --no-sync pytest -o addopts='' -q app/tests/test_discovery_schedule_pending.py app/tests/test_discovery_schedule_confirmation.py
uv run --no-sync ruff check app/routers/export.py app/routers/discovery_schedule_pending.py app/tests/test_ocsf_export.py app/tests/test_ocsf_export_closeout.py
```

- OCSF 两文件：**41 passed**。
- 待确认端点两文件：**24 passed**（另加 `test_discovery_schedule_management.py` 一组运行同为通过）。
- `ruff check`：`All checks passed!`

### 3.3 受影响模块全量（各一次）

```bash
cd edge/agent && GOPROXY=off go test -race -count=1 ./... && GOPROXY=off go vet ./...
cd apps/control-api && uv run --no-sync pytest -q && uv run --no-sync ruff check app
```

- `edge/agent` 全量：4 个包全部 `ok`（`edge/agent` 9.9s），退出码 0。
- `apps/control-api` 全量：**2258 collected / 2257 passed / 1 skipped / 0 failed / 0 errors**，退出码 0；随后独立 collect-only 复核为 2258。
- `ruff check app`：`All checks passed!`

### 3.4 仓库检查

```bash
git diff --check      # 无输出
git status --short    # 见 §5
python3 scripts/repository/check.py   # {"result": "passed", "documents": 222, "local_links": 1617, ...}
```

---

## 4. 未执行 / 未验证项（不得当作已通过）

- **未触碰 `apps/web`**：本任务按 §10.3 不要求重跑前端测试或浏览器 smoke；因此**没有**重跑 `npm test` 或正式构建。前端未做任何改动。
- **未做真实设备验收**：F01 的全部证据是源码级 + 隔离级（`httptest` 合成控制面、合成设备密钥、临时状态目录）。**没有**在真实设备、真实 Control API 环境或真实组织账号下运行过 `--discover`。
- **未连接生产/开发数据库**，未注册真实设备，未提交真实采集任务，未启动/停止任何真实 OpenShell 网关或沙箱。
- **未做发行签发、打包或部署**。
- **未运行**：一次性 PostgreSQL 容器、企业前端 30/30 浏览器旅程、OpenClaw / Hermes 原生采集全量、Windows / macOS 原生验收（与 §10.5 一致）。
- 前端构建未以 `VITE_DEV_MODE=false` 验证 —— 因为本任务未改 Web。

---

## 5. 与外部窗口 / 主开发者相关的门禁

- 本窗口**未创建提交、分支、推送或 PR**（未获该窗口用户明确授权）。
- 验收修复后工作树包含 15 个已修改文件 + 5 个未跟踪文件（含任务书本身与本交接文档）：

```
 M README.en.md
 M README.md
 M apps/control-api/app/routers/export.py
 M apps/control-api/app/routers/discovery_schedule_pending.py
 M apps/control-api/app/tests/test_discovery_schedule_pending.py
 M apps/control-api/app/tests/test_ocsf_export_closeout.py
 M docs/enterprise-production-runbook-v1.md
 M edge/agent/confirm_schedule_linux.go
 M edge/agent/confirm_schedule_linux_test.go
 M edge/agent/main.go
 M edge/agent/setup_enterprise_linux.go
 M edge/agent/setup_enterprise_linux_test.go
 M packages/contracts/README.md
 M packages/contracts/enterprise-discovery-schedule-pending-list.v1.md
 M packages/contracts/enterprise-discovery-schedule.v1.md
?? docs/development/enterprise-post-merge-remaining-closeout-taskbook-20260926.md
?? docs/development/enterprise-post-merge-remaining-closeout-handoff-20260926.md
?? edge/agent/discovery_schedule_list_linux.go
?? edge/agent/discovery_schedule_list_linux_test.go
?? packages/contracts/enterprise-ocsf-export.v1.md
```

- 验收已冻结的边界：
  1. `--discover` 的退出码按“查询”和“确认请求”区分：纯查询 0 项成功；明确请求确认但 0 项失败；多项与完整性失败同样失败。
  2. 新合同使用 `enterprise-ocsf-export.v1.md`（此前无对应公共合同，命名遵循既有 `enterprise-*.v1.md` 约定）。
  3. `enterprise-setup/v1` 不新增 `next_step` wire phase；下一步只进入帮助、README 和 runbook，避免严格消费者兼容性回归。

---

## 6. 未完成 / 遗留（本任务范围内未做，且**不在**本窗口宣称完成）

- 真实设备上的周期发现与确认旅程验收。
- 组织侧为新注册设备自动创建绑定计划的时序衔接（既有未完成项）。
- 企业前端未提供 `--discover` 对应的浏览器侧入口（本任务按范围未改 Web）。
- 共享运行时影响/批量执行仍**冻结**：`shared_runtime_occupants = unknown`、`skill_isolation = not_established`、`execution_confirmation_supported = false`（未触碰）。
- 未新增审计保留/删除能力；未做真实 OpenShell 行为探测。

---

## 7. 结论

仅完成企业主线合并后的 F01/F02/F03 收口，不代表 CL-01～CL-08、真实 OpenShell 行为验证或正式发行全部完成。本工作**未提交、未推送、未部署，待主开发者复核**。

---

## 8. 主开发者验收修复（2026-09-26）

复核全部变更文件后确认并修复以下问题：

1. **分页完整性**：初版只检查 `next_cursor` 递增，没有把条目 ID、请求 cursor 和响应 `next_cursor` 绑定。异常响应可能跳过待办后把残缺列表误当成唯一候选。现要求条目严格升序且都大于请求 cursor，非空 `next_cursor` 必须等于本页最后一条记录 ID，空页伪推进、跳跃、重复和回退均失败关闭。
2. **确认退出码**：初版在 0 个候选时总是成功退出，即使调用方带了 `--interactive` 或确认摘要。现区分查询与动作：纯发现 0 项成功；明确请求确认但无候选时失败，避免自动化误判为已确认。
3. **setup wire 兼容性**：初版给冻结的 `enterprise-setup/v1` NDJSON 新增了 `next_step` phase，严格消费者可能拒绝。现移除该 wire 变化并增加精确阶段顺序回归测试；下一步提示只进入帮助、README 与 runbook。
4. **本地写入措辞**：初版文档声称发现阶段“不写任何本地文件”，但任务锁可能创建或复用 `tasks.lock`。现统一改成“不写确认日志、回执或业务状态”，并明确任务锁只是本机互斥文件。
5. **异常 revision**：服务端和设备端现在都拒绝 `pending_confirmation + revision>0`；服务端将其列入 `integrity_failed`，设备端也要求首次确认候选 `revision=0`。

验收修复没有改变设备认证、显式确认、租户隔离、OCSF 正文或导出审计合同。安全差异复核未发现仍存的可报告安全漏洞；真实设备与真实控制面的原生旅程仍属于未执行项。
