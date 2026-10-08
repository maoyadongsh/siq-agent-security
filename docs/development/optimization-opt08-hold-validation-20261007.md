# OPT-08 C2a：原生调用审批重试与执行预留

日期：2026-10-07。状态：C2a 组件通过；版本/消费者兼容与日常业务接入仍未完成。

## 本批变更

按 [ADR-056](../adr/0056-native-skill-invocation-authority.md) 解除 C1 的临时重试拒绝。批准操作固定原 Intent 和 Agent baseline；读取批准状态、预留及执行前检查重新核验原调用完整权限链。重试必须由可信宿主另行登记不同的调用 ID，原调用和重试调用的会话签名、Agent authority、明确无 Skill 状态、全部上下文签名和授权摘要必须一致。

唯一 `hold_reservation` 仍是持久的执行预留事实，回执保存重试调用自己的 v3 证据和参数绑定。执行前检查同时重验原调用与该精确重试记录，且只允许本进程刚发布的原生预留成功检查一次。重建 Engine 或独立进程恢复只恢复签名事实，不恢复执行许可。并发重复检查不能得到第二次成功。

观察继承 reservation 的调用证明；执行后撤权不抹掉已发生的可关联结果。已预留而无 observation 的状态保持 uncertain，状态读取、重启、过期和撤权均不构成重执行许可。原 v1 行为保持，新流程尚未接入 serve 的原生宿主入口。

恢复时新增原生证据关联检查：审批须沿用原调用证明；reservation 必须切换到不同调用且保持相同权限链；observation/reconciliation 必须沿用实际预留的证明。即便文档签名有效，矛盾的关联记录也不恢复为可用动作状态。

## 验证范围

| 范围 | 实际验证 |
| --- | --- |
| 正向闭环 | 有 Skill 与明确无 Skill 均完成 hold → 人工批准 → 重试预留 → 一次最终检查 → observation；回执链可验签 |
| 两个真实签名 Skill Grant | 产品 Store 与 Engine 联测，在同一 Agent baseline 下建立两个不同 Skill Grant 和安装记录、父/叶 SEC、原调用与重试调用，完成上述组件闭环 |
| 未登记重试 | 原调用已批准也不能预留没有宿主调用记录的 retry；失败不追加 reservation |
| 权限链漂移 | 原调用/重试缺失或失效、受管模式降级、会话签名变化、父级改动/丢失、baseline 变化、无 Skill 降级及复用原 call ID 均拒绝 |
| 执行前变化 | 预留后原调用/重试失效、重试证明重签或任务结束均拒绝最终检查，uncertain 事实保留 |
| 并发 | 16 个并发最终检查仅一次成功；重复 reservation 拒绝，不提供再次执行许可 |
| 重启 | 新 Engine 与独立子进程从原签名链恢复后，最终执行检查拒绝，读取状态仍 uncertain；已完成链恢复为 completed |
| 真实存储依赖 | 父 SEC 撤销、原生任务结束、原调用租约到期、重试宿主事实缺失均经实际 Store 校验传播到执行门禁 |
| 签名但矛盾的事件 | 将原调用证明误当重试、审批/观察换证明或 v3 缺失证明的受控签名反例，恢复拒绝 |
| 跨语言链 | 两份产品实际生成的四事件合成链由 Python 独立校验 schema、seq/prev_hash、每行 hash/Ed25519，以及原调用/重试引用关系 |

此处使用实际产品签名 Store、决策引擎及回执恢复流程。原生宿主、安装内容等依赖仍由合成夹具提供，未运行 Hermes/模型，也没有把组件 observation 当成独立文件/网络业务效果证据。

## 检查结果

- `go vet ./...`、`go test ./...` 通过，44 个有测试包、10 个无测试包。
- `go test -race ./internal/receipt ./internal/skillcontext` 通过，包含旧 SEC 与新审批回归。
- Python native 合同及既有 schema 测试共 334 项通过，1 条既有 Starlette 弃用警告；定向 Ruff 通过。
- linux/amd64、linux/arm64、darwin/arm64、windows/amd64 四目标构建通过，未代替原生平台验收。
- 日志：`var/optimization-20261007/opt08-hold-{vet,go-all,race,contracts}.log`；定向过程日志为 `opt08-native-hold-{focused,store}.log`。日志和构建产物不提交。

## 剩余门禁

C2b 将更新新状态协议的读写能力声明及回退预检；后续同步 UI、导出等消费者，再完成可信 enrollment 必需路径、固定 Hermes 镜像宿主接入与真实业务验收。OPT-08 保持 implementing，当前不推送或宣称整体完成。
