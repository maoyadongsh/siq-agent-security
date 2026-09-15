# OpenShell O01/O02 组件与真实网关验收（2026-09-15）

结论：O01“策略保真”和 O02“安全回滚”的 Go/Python 实现、本机组件验证和隔离 OpenShell 0.0.83 真实读写验收均已完成，结论为 `fixed`。本报告的验证快照绑定工作树 `kimi/personal-v4-r01-20260914`、HEAD `b303c6f92392f3a44c306d81ad7323c6291ef4f2` 加当时未提交修改；用户随后授权提交并推送本候选，具体提交身份以 Git 历史为准；未合并、未发布。

## O01 实现与不变量

- Go/Python 都从 `policy get <target> --full` 保留完整解析策略，并分别计算 `policy_digest` 与排除 `network_policies` 的 `static_digest`。更新只克隆完整策略并替换网络段，Landlock、filesystem、process、扩展字段及未知但可无损表达的静态字段不会被重建成默认值。
- 严格接受唯一规范正十进制 revision。OpenShell 0.0.83 实际输出以 `Version` 表示有效 revision；兼容输出若同时包含 `Active`，两者必须相同。缺失、重复、非法或冲突均拒绝，不默认 revision 1。重复映射键、alias/anchor/tag/merge、非空 flow collection、非字符串键及歧义隐式标量均在写前拒绝。Go 继续只使用标准库，不能无损处理的 YAML 失败关闭。
- 网络写入只接受 `effect=allow`、单个 `host:port` 与至少一个显式绝对 binary path。deny、method/path/provider/protocol/purpose、`allowed_ips` 及未知字段零写拒绝。Go HTTP 生产入口使用 strict JSON decoder，避免调用方的 L7 字段被静默丢弃。
- Python 路由在创建 Deployment 前读取 live 策略，由 `plan_change` 比较真实静态字段；字段存在但值相同可走网络动态更新，真实静态变化仍以 `static_generation_unavailable` 零后端写拒绝。
- apply 写前再次核对 revision 与完整摘要，写后要求网关回执 revision 和完整策略摘要同时匹配。host/port 检查只作补充，不能代替完整策略核验。
- 根目录 `testdata/openshell-policy-safety.v2.json` 由两种语言共同消费，包含真实 `Version`、缺失/非法/冲突 revision、重复键、歧义 YAML、完整静态字段及不支持限制向量。

## O02 实现与不变量

- 每次 apply 生成不可预测 operation ID。进程级、有界私有 registry 保存 target、精确 base snapshot/revision/digest、applied revision/digest 与 no-op 状态；公开回执只用于索引与绑定核对，调用方不能用伪造 evidence 构造回滚权限。
- apply/rollback 按 target 在同一进程串行；每次写前、写后复核真实 revision 与完整摘要。revision 作为网关返回的精确身份使用，不以 `revision - 1` 推算，覆盖非连续 revision。
- no-op 回滚在 live revision/digest 仍匹配时零写完成。未知/已消费操作、进程重启或 registry 逐出、target/receipt 不匹配、外部漂移均拒绝。
- 改变状态的回滚从私有记录恢复精确 base 策略，并在写前通过可信回调重新查询 authenticated `policy:manage`、active RuntimeBinding、backend target、ChangeRequest、DesiredPolicy 与 selector 绑定。吊销 binding 后回滚零写拒绝。
- apply 已得到可信 operation binding、但后续补充验证失败时，Control API 保留绑定及“后端已变更”状态，不再用错误对象覆盖 receipt；该 failed deployment 仍能经过当前授权复核执行安全回滚。
- 本批没有新增持久化 operation 状态或绕过现有签名/状态锁。registry 丢失后安全拒绝是设计行为。

## 隔离真实网关验收

用户明确授权后，在 `/home/maoyd/siq-research-engine` 启动项目隔离网关 `siq-openshell-dev`；TLS endpoint 为 `https://127.0.0.1:17671`、health 为 `127.0.0.1:17672`，项目固定 CLI 和 gateway 均为 OpenShell 0.0.83。没有启动或修改其他网关。

- 先运行最小 Hermes POC：正常、工具、stop 三类 API 合同通过；sandbox 内只读 Landlock 写探针被内核拒绝，POC sandbox 随后按精确身份清理，网关保留运行。
- 对已确认属于历史 AgentShield demo 的 `siq-as-live` 做真实 O01/O02 验收。base revision 7；应用网络变更后 revision 8；授权回滚精确恢复 base 策略后 revision 9。base/final 完整摘要同为 `237ea4ad962c095a7d08ddd7ddb6059df2dd233bf0efe23eb198b8a205ed1b6c`，证明没有用 `revision-1` 猜测目标。
- 同一 live test 验证 deny、缺失 revision、非规范 `01` revision 均零写；no-op apply/rollback revision 不变；伪造回执、撤销授权、新 coordinator（重启等价的未知 operation）均拒绝；完整静态摘要在更新期间保持一致。
- 验收后先确认 base 策略已恢复，再删除该精确 demo sandbox，为业务 canary 释放隔离网关；该 sandbox 删除不可恢复，但其策略与摘要证据已记录。未删除业务资产。
- 当前业务 `siq_analysis` canary 策略含 provider L7、method/path、`allowed_ips` 等 0.0.83 扩展。AgentShield 对这类无法无损重写的 policy 按设计拒绝，因此没有把业务 canary 当作 O01/O02 写入靶标。

## `siq_analysis` 真实链路

research-engine 同时完成了真实链路修复，详细见 `/home/maoyd/siq-research-engine/docs/reports/2026-09-15-siq-analysis-openshell-canary-recovery.md`：

- 处理已提交但进程已消失的旧 gateway runtime evidence；只有证明精确 PID/start ticks 已消失且两个 gateway 端口无监听时才删除陈旧记录，不能证明则拒绝。
- 停止冲突的旧 `finsight_analysis` systemd user service，启用并验证正确的 `hermes-gateway-siq@analysis.service`；未删除任何 profile 数据。
- broker 以 `request_identity_required=true` 启动；新镜像 `siq/hermes-openshell-siq-analysis:f470321d2fb2b2cda14b7c3b` 完整 smoke 通过。
- 项目 `env.sh` 现在把交互式 `openshell` 绑定到固定项目 CLI；固定 0.0.83 可正常 list/get 当前 sandbox。全局旧 CLI 不再被静默选中，项目 CLI 缺失时不 fallback。
- 当前保留 `canary-a01b02c91503`，公司 `cn/600104-上汽集团`，slot `9bc20683a73220cad2e19d40`，本地 `127.0.0.1:28652`；status、认证 forward、sandbox exec health、guard 和全量业务边界 probe 通过。runtime selection 为 `openshell/session_mode=all`，pool resolve 不返回 credential。
- 轮换后的真实模型请求完成：create/SSE/terminal 合同通过，事件为 8 个 `message.delta`、1 个 `reasoning.available`、1 个 `run.completed`；配置主模型 `custom/Qwen3.6-35B-A3B-FP8` 不可用时，实际按配置 fallback 到本地 `custom:gemma4-local/Gemma-4-26B-A4B-it-NVFP4`。模型输出只记录 54 字节和 SHA256 `be3f7ace80ab49e322d345a0c2548980642f8ec6fba00792cc6bca1aaa8fdd3c`，未落盘提示词、回复或凭据；本次未产生付费模型调用。

## 验证结果

Go（`apps/agentshield`）：`go test ./...`、`go vet ./...`、`go test -race ./internal/openshell ./internal/server` 均通过；`gofmt` 和 `git diff --check` 通过。

Python（`apps/control-api`）：`uv run pytest -q` 全套通过；`uv run ruff check app` 和本批文件 `ruff format --check` 通过。仅有既存 Starlette/httpx 弃用警告。全仓 `ruff format --check app` 仍报告 43 个本批范围外或既有格式基线文件，未批量重排用户改动。

Web（`apps/web`）：24 个测试文件、93 项测试通过，生产构建通过；生成资源随当前源码重建。

research-engine：OpenShell tests/control distribution 共 1312 项通过；受影响定向集合 34 项通过。最终全套结果及源码摘要写入 research-engine 报告。

四目标使用 `CGO_ENABLED=0 GOOS=<os> GOARCH=<arch> go build -trimpath` 重新构建；linux/amd64、linux/arm64、darwin/arm64、windows/amd64 的摘要见 [cross-builds.json](cross-builds.json)。临时文件已清理；交叉构建不代表 Windows/macOS 实机通过，也不替 sunbo/Luke 声明平台验收。

## 限制与状态边界

- 目标锁与 operation registry 仅在单进程内共享。网关没有可用原子 CAS 时，其他进程或外部 writer 仍可能在最后一次写前检查之后竞争；写后读回能检测观察到的漂移，但不能阻止瞬时覆盖，不能宣称跨进程原子事务。
- Python HTTP transport 在尚未证实 full-policy CAS 前对 apply/rollback 失败关闭；当前生产部署路径使用已验证的 CLI transport。
- 当前 canary 是 `NOT_PRODUCTION_CANARY`，`readiness_effect=none`、总体 formal readiness 仍为 `unchanged_no_go`；这次真跑证明项目固定公司作用域的分析助手链路，不提升 OpenShell V0.6 正式生产结论。
- Windows/macOS 仅交叉构建，平台实机仍由 sunbo/Luke 原分工继续；O04/O05/O06、团队 T01–T06 均未开展。
- 本批源码形成新的候选二进制身份；旧 N09 二进制及六条原生腿的通过状态不自动继承，本报告不提升 N09 或总体产品状态。
