# OPT-11：升级持久记录与运行阻断验证

日期：2026-10-08。分支：`codex/security-optimization-20261007`。
本批父提交：`5d8b13a3`。任务保持 **implementing**；主任务仍为 **11/16（68.75%）**。

## 结果及适用范围

本批补齐企业 Edge 升级恢复的基础组件：在当前私密设备目录持久保存精确绑定的 pending
记录，核验恢复所需的已知状态，阻止普通任务在未完成升级时运行。尚未提供公开的配置
切换或恢复命令，不将组件测试描述为已完成签名包升级、服务切换或业务恢复。

实现、合同和证据：

- [版本化日志合同](../../packages/contracts/enterprise-upgrade-journal.v1.md)。
- [机器可读证据、源码及日志摘要](evidence/optimization-20261007/enterprise-upgrade-journal.json)。
- [前批只读升级核验](optimization-opt11-upgrade-review-validation-20261008.md)。
- [ADR-061](../adr/0061-enterprise-service-upgrade.md)。

## 已实现的行为

| 场景 | 当前行为 | 验证方式 |
| --- | --- | --- |
| 创建恢复记录 | 重新核对完整升级 intent、显式确认摘要及旧/新暂存来源；排他创建 0600 日志、同步文件和目录、严格读回 | 真实文件系统、组件验签替身；固定发布者验证器另行拒绝替身制品 |
| 身份保护 | 日志保存计划和状态摘要，不复制设备令牌、签名 seed；恢复时重新绑定全部非计划 State 字段 | 8 类身份/摘要变化拒绝，Python 独立复算合成状态摘要 |
| 中断后的混合配置 | 原始状态、预期目标状态、重序列化旧状态与旧/新 unit 共 6 种已知组合可只读检查；均继续阻断任务 | 合成中间态文件矩阵；检查前后文件树摘要相同 |
| 非预期配置 | 额外空白、未知字段、第三份 unit、发行清单变化和核验中途漂移拒绝 | 定向负向与 race |
| 日志损坏 | 截断、未知/重复字段、超限、符号链接、硬链接、目录、FIFO、宽权限日志均拒绝 | 普通 `tasks`/`serve` 不读取执行计划、不执行任务；恢复锁仍可重新获取 |
| 进程退出 | 写入成功后子进程直接退出，内核释放 flock；另一个进程仍识别 pending 并阻断任务 | 独立进程退出与新进程调用；不等同切断机器电源 |
| 并发读取顺序 | `tasks`/`serve` 先获得任务锁，再读取 State；锁路径逐级固定并拒绝不安全祖先 | 持锁时提供非法状态，先返回锁冲突；符号链接及可组写祖先拒绝 |
| 其他未完成事务 | 凭据轮转、周期确认/确认回执、周期退出日志存在时拒绝新升级 | 保留所有原文件，无自动撤销、归档或确认 |

周期采集确认与旧安装计划绑定。现有已确认周期不能自动继承到新计划；应通过既有在线
撤销、显式归档流程退出旧确认，再进行升级。历史执行台账、已归档周期记录及身份均保留。
初次注册流程会保留 `registration-pending.json`，该历史文件不能单独被误判为仍未注册。

## 验证结果与修正

| 检查 | 结果 | 分母说明 |
| --- | --- | --- |
| 首轮新增定向测试 | 11 个顶层 / 63 个含子测试通过 | 包含供独立进程调用的测试 helper；后续另加 1 条祖先权限负向 |
| Edge 全量首轮 | 235 个顶层通过、2 失败、2 跳过；781 个含子测试通过 | 命令退出码 1，保留原始日志，不改写成一次全量绿灯 |
| 受影响修正回归 | 两个失败测试及新增祖先权限测试全部通过，启用 race | 两份旧夹具的临时父目录在本机 umask 下可组写；仅 chmod 自有夹具根为 0700，未放宽生产检查 |
| 本批合并唯一测试结果 | **238 个顶层通过 / 784 个含子测试通过，2 条跳过** | 全量与针对性修正合并去重；不是重复累计所有运行次数 |
| 升级及任务锁 race | 19 个顶层 / 99 个含子测试通过 | 加上上述 3 条修正 race；有重叠，不另加成全量分母 |
| Python 合同 | 26 项通过 | 新日志 15 项、既有升级 review 11 项；含独立规范化确认摘要与 State 编码摘要复算 |
| 静态检查 | Go vet、Ruff、gofmt、diff check 通过 | 初始 Ruff 有一条长行，拆行后通过，语义未变 |
| 构建 | Linux arm64/amd64、macOS arm64、Windows amd64 通过 | Windows/macOS 只证明构建，不证明受管执行支持或原生验收 |
| 真实 Linux CLI | 10 项通过 | 对截断日志、目录、符号链接、FIFO、无日志对照分别运行 `tasks`、`serve`；输入保持，私有临时 home 清理 |

既有跳过为 `TestInstallPlanWireParity`（由 Python 合同负责语料）及
`TestSkillAncestryNativeExport`（本批未提供其独立原生夹具）。Go overlay 仅排除不属于本批、
尚未跟踪的 `edge/agent/crash_recovery_test.go`；不移动、删除或提交该文件。

实际原生二进制 SHA-256：
`44e4c621d55795affea68a626e6b3e83177c2d38e615b1720ba2e77ae80f74ab`。

关键命令（完整日志位于 `var/optimization-20261007/opt11-upgrade-journal-logs/`）：

```bash
# edge/agent 下；overlay 排除项如上
 go test -overlay /tmp/siq-opt11-upgrade-journal-overlay.json -json ./...
 go test -overlay /tmp/siq-opt11-upgrade-journal-overlay.json -race -json . -run '^Test(Upgrade|TaskLock)' -count=1
 go test -overlay /tmp/siq-opt11-upgrade-journal-overlay.json -race -json . -run '^Test(RegistrationUsesMeasuredCapabilities|RegistrationUnknownOutcomePreservesIdentity|UpgradeTaskLockRejectsWritableAncestor)$' -count=1
 go vet -overlay /tmp/siq-opt11-upgrade-journal-overlay.json ./...
# apps/control-api 下
.venv/bin/pytest -q app/tests/test_enterprise_upgrade_journal_contract.py app/tests/test_enterprise_upgrade_review_contract.py
.venv/bin/ruff check app/tests/test_enterprise_upgrade_journal_contract.py
```

## 保留的边界与下一步

1. 正向日志测试使用明确的内部验签替身；公开 CLI 仍固定发布公钥，替身文件被真实验证器拒绝。
   `enterprise-upgrade-journal.synthetic.json` 是合同样例，不是某台实际设备的升级凭证。
2. 真实 CLI 检查仅证明本次 Linux 二进制的 pending 阻断。没有调用 systemctl、connector、模型、
   日常网关、控制面身份或业务项目；没有停止、升级或重启用户服务。
3. 老版本 Edge 若不包含 pending 阻断逻辑，不会因创建日志自动获得恢复安全性。早期
   `a9a8e91e` 未签名候选冻结保留，不能用作该能力已具备的旧版本证明。
4. 后续仍需：实际服务已停止核验、state/unit 持久切换、明确方向的恢复、完成归档、正式签名包
   和真实设备/服务验收。新目标计划必须在写入时有效；本批只读恢复检查不因窗口过期失去诊断能力。
5. 同 UID/root 管理员仍处于信任边界。无通用防降级、发布者在线撤回或 OS 沙箱保证。
6. 本批仅本地提交，未推送远端、发布制品或完成主线 CI/合并。
