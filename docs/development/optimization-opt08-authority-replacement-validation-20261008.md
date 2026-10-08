# OPT-08/10：Skill 授权换代与新任务恢复验证

日期：2026-10-08。环境：DGX Spark＋智能分析助手＋Hermes 原生 Skill＋OpenShell＋SIQ Agent Security。

**本批确认：正式更新事务完成后，旧任务不能借用新 Grant 继续写入；新任务使用新安装记录和新 Grant，可以完成合法读写。** 这验证的是同一 Skill 内容的授权换代，不代表已完成 Skill 内容版本升级或旧授权原地续期。

## 1. 设计与授权边界

现行 ADR-056 要求 SEC 固定 Agent baseline、Skill Grant、安装声明和实际加载事实，每次调用重新验证。管理员批准另一个 Grant，不应使旧 SEC 自动继承它。合法更新后，也应保留新任务正常工作的路径。

本批通过公开管理 API 导入实际 `siq-research-draft` 内容并独立审批新的 Grant；原有 writer Grant 和独立 Agent baseline 保留，更新前不自动替换它们。新旧 Skill 字节相同，固定 Hermes 镜像及 runtime artifact 不变，避免将内容变化、模型变化与授权换代混在一起。

两个真实用例和驱动摘要在执行前登记：

| 用例 | 操作顺序 | 预期 |
| --- | --- | --- |
| v870：旧任务 | 模型原生加载旧安装 → 实际读取 → 正式更新事务 → 同一任务实际写入 | 旧授权失效，写入被拒，目标不存在 |
| v871：新任务 | 部署资料明确绑定新安装 → 新业务请求 → 模型加载、读取和写入 | 新授权链成立，文件内容正确，任务完成 |

v870 在成功读取后，核对该任务的受保护启动记录、真实进程、解释器、参数、cgroup 与 pidfd，短暂暂停该 Hermes 进程，以保证写入在更新完成之后发生。业务监管者、宿主裁决服务、模型服务和 Authority 正常运行。最后使用同一 pidfd 恢复进程，不伪造工具响应、不用进程退出替代拒写证明。

## 2. 正式更新流程

整个事务使用既有版本化 API：

1. 读取旧安装操作、移除预检、旧 Grant 与新 Grant，核对 revision、签名及已批准状态。
2. 调用 `update-comparison`，确认内容差异数量为 0；比较本身不授予权限。
3. 调用 `update-plans`，绑定精确旧操作、新 Grant、双方 revision 和当前安装绑定签名。
4. 调用 `/v1/skill-installations/updates` 确认执行；读回 `updated_unverified`、旧安装 `removed`、新安装 `installed_unverified`。
5. 使用新安装操作签名调用 `activate`。确认旧 Grant 已撤销，新 Grant 签名内容及 Agent baseline 不变，旧 SEC 内容不被重写，实际 Skill 字节保持原摘要。
6. 为下一请求生成独立部署资料，仅将原 writer 安装的 `install_id` 和 `claim_signature` 替换为新记录；reader、根身份、制品、控制通道及其他字段保持不变。

该配置更新是明确的受控部署动作，不声称现有所有日常配置会自动迁移，也不把管理 API 的 `updated_unverified` 改写成普遍运行时验证成功。实际运行结论来自随后新任务的工具与文件效果。

## 3. 真实结果

| 项目 | v870：旧任务更新后 | v871：新任务 |
| --- | --- | --- |
| 原生加载及读取 | 旧安装、旧 Grant，读取 allow | 新安装、新 Grant，读取 allow |
| 写入时旧 Grant | revoked | 仍为 revoked |
| Agent baseline | 完整签名及 revision 不变 | 保持相同基线 |
| SEC 自身截止时间 | 尚未到达；原签名内容不改写 | 新任务生成新 SEC |
| 实际 write_file | 发起后返回错误 | 成功 |
| 文件／符号链接 | 均不存在 | 文件存在，正文及摘要匹配 |
| 写入回执 | 0 条，无伪造 deny | 1 条签名 allow |
| 业务终态 | completed，模型回答报告工具失败 | completed，正常结果标记匹配 |
| 预登记检查 | 32 项通过 | 31 项通过 |
| 监管状态 | inactive/success/退出 0，PID 0 | inactive/success/退出 0，PID 0 |

旧任务进程暂停约 **0.368 秒**；更新完成后约 **5.661 秒**收到写入开始事件。这是本次受控运行的观察间隔，包含模型和事件传输时间，不是权限撤销 SLA。

两例实际 OpenShell 策略均允许各自任务输出目录，规范化 run/nonce 后相同；输出目录设备号／inode 与启动记录一致，策略文件与资产摘要一致。拒绝不能归因于把目标目录改成不可写。实际写入开始事件中的路径也与独立观察目标相符。

## 4. 候选与证据

业务提交保持 `8851724`，安全二进制为 Git 导出 `32e10d54`，Hermes 原生镜像及 Skill 字节保持不变。每轮冻结 **1,874 个业务输入、289 个相对 HEAD 的独立登记差异**，候选摘要为 `5bbf4e90636c45ed58d801de1481d5bb10a216ecb68390e587bea18efc791521`。不把存在登记补丁的工作候选描述为干净签名发行包。

本批使用新的独立 Authority，完整链为 **5 条签名回执、2 份 SEC**。同时公开 **4 份 Grant 快照**（旧批准、旧撤销、新批准、Agent 基线）与 **4 份安装／更新签名记录**（新旧安装操作、旧安装移除结果、更新结果）。

- [候选、现场观察和配置变化范围](evidence/optimization-20261007/native-renewal-v870-v871.json)
- [完整 5 条回执链](evidence/optimization-20261007/native-renewal-v870-v871.receipts.jsonl)
- [新旧任务的 2 份 SEC](evidence/optimization-20261007/native-renewal-v870-v871.contexts.json)
- [授权与安装换代签名记录](evidence/optimization-20261007/native-renewal-v870-v871.authority-replacement.json)

负向绑定更新前的读取 allow，证明旧任务确实进入了原授权链；它不是签名写入 deny。到下一次工具执行前，旧授权依赖已失效，现场通过工具错误和目标不存在确认拒写。

完整管理事务材料保留在本地私有证据中；公开摘要不包含凭据、配置或私有部署路径。公开记录能够验证签名结果间的关联，不能据此重新观察操作员执行过程、原机器文件或精确时间先后。

## 5. 独立核验增强

离线核验器新增可选 `authority_replacement` 证据及绑定，两者缺一即拒绝：

- 核对全部导出记录签名，新旧 Skill Grant 与 Agent Grant 身份互不混用；旧 Grant 只发生状态和签名变化。
- 核对旧批准 → 旧撤销、新批准、有效 Agent 状态；批准事实不被当成当前执行许可。
- 核对新旧安装不同、移除记录对应旧 Grant 撤销签名、更新结果对应精确移除与新安装操作签名。
- 将每份 SEC 的精确 Grant 摘要、安装声明与对应新旧记录相连；所有回执仍绑定同一 Agent baseline。
- 要求两个授权阶段均有独立任务决定绑定；只提交一个阶段不能伪装成完整换代验证。

```bash
apps/control-api/.venv/bin/python scripts/research/verify_native_business_evidence.py \
  docs/development/evidence/optimization-20261007/native-renewal-v870-v871.json
```

现场独立观察器与公开离线验签均通过。相关核验器回归包含真实证据及修改摘要后伪造安装、签名记录错配、旧上下文借用新安装、未批准新 Grant、缺少阶段或元数据等反例；最终相关 **50 项通过**（原 34 项及本批新增 16 项），Ruff 通过。未修改 Go／Hermes 产品逻辑，未重复无关产品全量测试。

## 6. 清理与剩余范围

两个临时业务 API、数据库、沙箱、网关与模型桥已回收，三个服务配置恢复，原模型未重启，业务源码不变。API 运行依赖前后保持 **11,663 文件、4 链接**，摘要 `ec6da2fd01ce3ea539f3fc333ced90be3a7f6f17a469e54132d49f522979bd34`，不等同于最终全栈冻结。

本批两个用例均首次通过；前一批到期测试的脚本失败仍留在其原记录中。不同批次和 Authority 不累加成重复次数。

SEC 单独到期、实际内容版本升级、并发隔离、其他资源／工具入口、最终矩阵、正式签名交付和 Windows／macOS 原生验收仍需继续。OPT-08、OPT-10 保持 implementing，总体 **11/16（68.75%）**。
