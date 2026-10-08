# OPT-11：企业升级切换与显式恢复验证

日期：2026-10-08。分支：`codex/security-optimization-20261007`。
父提交：`12023f31`。任务仍为 **implementing**，总体 **11/16（68.75%）**。

## 本批结论

企业 Edge 已提供明确确认的配置升级和恢复命令。它们在任务排他锁下核验已停服条件、
旧/新来源、准确状态及服务配置，持久切换，先归档完成记录再清理 pending。服务启动和
业务效果不包含在成功回执中。组件故障恢复、独立进程退出恢复及原生 CLI 拒绝检查通过；
正式签名包的正向升级、真实 systemd 和设备迁移验收尚未完成。

- [执行及完成合同](../../packages/contracts/enterprise-upgrade-apply.v1.md)
- [源码、构建与原始日志摘要](evidence/optimization-20261007/enterprise-upgrade-apply.json)
- [前批持久日志验证](optimization-opt11-upgrade-journal-validation-20261008.md)
- [ADR-061](../adr/0061-enterprise-service-upgrade.md)

## 行为与权限边界

| 步骤 | 实现行为 | 失败处理 |
| --- | --- | --- |
| 操作确认 | apply 沿用完整 review intent 摘要；recover 明确 target/previous 和同一摘要 | 缺参、错摘要、任意额外参数拒绝，不增加绕过签名选项 |
| 服务状态 | 固定 systemctl 用户单元，要求准确 FragmentPath、无 drop-in、MainPID/ControlPID=0、inactive/dead 或 failed/failed | 活动、启动中、未知/不可读取状态拒绝；不自动停止用户服务 |
| 程序兼容 | 两份暂存固定发布者验签；固定实际 ELF 文件描述符后读取恢复协议与编译版本 | 旧包不识别 pending 协议、错误摘要/版本拒绝；不继承 HOME、设备环境或凭据，不回退 PATH |
| 状态切换 | 状态和 unit 原子替换，各自同步文件及目录；保留身份、凭据和执行历史 | 保留 pending，普通任务拒绝；没有依赖进程内补偿的假回滚 |
| 恢复 | 重新读盘、核验来源/已知中间态，显式完成或恢复原计划 | 目标过期不能继续新切换；旧安装窗口过期仍可恢复 previous；第三份配置拒绝 |
| 完成 | daemon-reload 后确认仍停服且配置准确；排他写完成归档再清理 pending | 不同完成方向不能覆盖；已归档结果可在新窗口过期后仅完成同方向清理 |
| 输出 | status=configured_not_started，service_started=false、business_permissions_granted=false | stdout 写失败不回滚已持久的配置；从完成文件核对，不凭失败输出推断安装被撤回 |

旧周期确认绑定旧安装计划，必须经现有在线撤销及显式归档流程退出，不自动迁移或重签授权。
新事务与凭据轮转等未完成事务互斥。旧版无 pending 保护能力的 Edge 不会被静默视为兼容；
早期 `a9a8e91e` 两份候选保持冻结，不把新测试倒算到其身份上。

## 验证与结果

| 检查 | 结果 | 证据含义 |
| --- | --- | --- |
| Edge 全量 | **251 顶层 / 820 含子测试通过，2 条既有条件跳过**，退出码 0 | 本批最终生产代码的一次完整模块回归 |
| 新增独立进程退出恢复 | **1 项 race 通过** | 子进程在 state/unit 写入并同步后直接退出；父进程重新读盘，普通任务被阻断，再恢复旧配置和身份 |
| 去重合计 | **251 顶层 / 820 含子测试通过** | 最终全量已含上述进程测试，不重复累计 |
| 升级与任务锁 race | 31 顶层 / 134 含子测试通过 | 包含旧 review/journal 与本批切换测试，不能另加到全量分母 |
| 连接器可信文件 race | 6 顶层 / 18 含子测试通过 | 复用文件描述符核验器后，原 allowlist、替换、权限、执行和输出限制保持 |
| Python 合同 | **38 项通过** | 本批完成合同 12 项 + journal/review 26 项；嵌套契约与“不代表启动/授权”负向 |
| 真实 ELF 协议探针 | 成功、错摘要、错版本、取消检查通过 | 本机编译的合成 helper，固定 FD 执行且不继承私密环境；不是正式 Edge 包验收 |
| 真实 Linux CLI | **10 项通过** | 协议输出/帮助、额外参数拒绝、固定验证器拒绝伪造来源、损坏 pending 拒绝恢复、tasks/serve 阻断 |
| 静态与构建 | vet、Ruff、gofmt、diff check；Linux arm64/amd64、macOS arm64、Windows amd64 构建通过 | 跨平台构建不等于 Windows/macOS 原生受管支持 |

全量跳过仍为 `TestInstallPlanWireParity` 和 `TestSkillAncestryNativeExport`，本批没有把其缺失原生输入改成通过。
Go overlay 只排除不属于本批的未跟踪 `edge/agent/crash_recovery_test.go`。初次定向命令因测试误引用
既有 short-writer helper 名字而编译失败，修正后通过；原 stderr 保留。没有掩盖全量失败或重写历史日志。

收尾补严了协议字段精确匹配，拒绝大小写别名、重复字段、null/数字锁标记；2 项协议定向 race 通过后，
运行最终全量、重建四目标并在最终二进制重做原生 CLI 检查。初次全量（249 顶层/818 含子测试）
及原构建保持冻结，当前结论使用最终快照。

真实 Linux 二进制 SHA-256：
`bd5e74bfc15af4b955ce939c5060dddb3009b88831d6504cd25a21f37bcb4ed5`。

主要命令：

```bash
# edge/agent
 go test -overlay /tmp/siq-opt11-upgrade-journal-overlay.json -json ./...
 go test -overlay /tmp/siq-opt11-upgrade-journal-overlay.json -race -json . -run '^Test(Upgrade|TaskLock|ConnectorTrust|ManagedConnector)' -count=1
 go test -overlay /tmp/siq-opt11-upgrade-journal-overlay.json -race -json . -run '^Test(VerifiedConnector|VerifiedDescriptor|NoPATHFallback)' -count=1
 go test -overlay /tmp/siq-opt11-upgrade-journal-overlay.json -race -json . -run '^TestUpgradeApplyRecoversAfterAbruptProcessExit$' -count=1
 go vet -overlay /tmp/siq-opt11-upgrade-journal-overlay.json ./...
# apps/control-api
.venv/bin/pytest -q app/tests/test_enterprise_upgrade_apply_contract.py app/tests/test_enterprise_upgrade_journal_contract.py app/tests/test_enterprise_upgrade_review_contract.py
```

原始日志位于 `var/optimization-20261007/opt11-upgrade-apply-logs/`；最终原生驱动与输出位于
`var/optimization-20261007/opt11-upgrade-apply-final-native/`。
正向切换的 publisher 验签和服务管理器均为明确内部替身；Go wire fixture 也是合成样例。
没有使用真实发布私钥，没有声称操作过真实用户服务、已完成采集或业务恢复；原生 CLI 的
伪造包拒绝不能替代正式签名包正向验收。

## 后续验收

需要基于包含新协议的精确提交重新生成企业候选，再通过受控签发取得固定公钥可验证的旧/新包，
完成真实用户服务的安装、停服、升级、恢复、重启与采集，以及既有设备迁移。不能自行给旧候选
补签名字段或以个人客户端 `0.4.0` 安装包替代企业发行协议。当前本机阶段仍未提供这份正向证据。
本批仅本地提交；远端推送、发行、CI 和主线合并尚未执行。
