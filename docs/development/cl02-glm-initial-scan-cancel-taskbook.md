# GLM：首扫成功返回后的取消状态修复

任务编号：CL-02-INITIAL-SCAN-CANCEL。项目：`/home/maoyd/siq/siq-agent-security`。

请直接实现、验证并交付，不只给方案。此任务不是上一轮 discovery_schedule_poll 的重复任务；本次目标是 initial_scan.go 的另一个闭包。禁止扩展功能，减少重复测试。

## 1. 开始前

阅读工作区和项目 AGENTS.md、相关下级指南（若有）、工作区 VIBECODING_SCIENTIFIC_METHOD.md。
检查 git status 和允许文件的现有内容/diff；保护所有未提交及未跟踪成果。
阅读：

- `edge/agent/initial_scan.go`、`initial_scan_test.go`
- `edge/agent/serve.go`（只读，确认调用路径）
- `edge/agent/discovery_schedule_poll_linux.go` 的已完成取消检查（只读）
- 与 initial-scan、首扫幂等有关的 packages/contracts 合同（先 rg 定位实际文件，不猜文件名）

## 2. 已观察到的缺口

主开发者检查时，initialScanHeartbeatWithClock 调用 initial(ctx, state) 后：

- 返回 error 的分支已经检查 ctx.Err；
- 返回 nil 的分支直接 requested=true，然后返回 nil。

因此需要验证“initial 回调内取消 ctx 后返回 nil”是否仍被当作成功，且改变 requested 导致后续闭包调用跳过首扫。

请先复现，再最小修复：无论 initial 返回成功或错误，都在改变 requested/退避状态前检查取消并传播。保留原服务端幂等，不增加客户端自动重发机制。取消并不证明服务端未创建任务，不删除远端或本地历史，不生成新 plan。

## 3. 文件所有权

只允许修改：

- `edge/agent/initial_scan.go`
- `edge/agent/initial_scan_test.go`

只允许新增交接：`docs/development/enterprise-initial-scan-cancel-handoff.md`。

其他文件只读。特别禁止再改上一轮的 discovery_schedule_poll 文件；禁止修改 Qwen 的 discovery_scheduler.py/测试、主线的 confirm_schedule/setup/Hermes 来源相关文件、serve.go、共享 Client、后端、前端、合同、README、公共台账、依赖和锁文件。若需要超范围修改，报告证据与最小建议。

## 4. 必须保持

- 心跳和能力测量顺序、首扫成功后单次本地抑制、同一原安装计划的服务端幂等。
- 首扫失败独立退避，30 秒起步、15 分钟上限，不影响健康心跳。
- 已取消不更新 requested/retryAt/retryDelay，不输出普通失败重试日志。
- 不改变 v1/v2 首扫请求/响应、技能拆分、任务数量与 ID 校验、范围和身份约束。
- 不新增 goroutine、配置、命令、网络端点或恢复状态。
- 不将取消处理等同于服务端任务撤销；不假称没有发生远端副作用。

## 5. 有限验证

复用现有合成时钟、能力测量和回调夹具。补一个集中测试，至少覆盖 initial 内取消后返回 nil，以及取消后返回 error。先确认旧行为失败，再修复。

断言返回 context.Canceled；用同一闭包、新的未取消 context、相同注入时间继续调用，检查取消未将 requested 置真、未产生退避。此二次调用只是观测闭包状态的测试手段，不是新生产恢复策略。正常成功仍只能请求一次、普通失败退避仍成立，用已有测试覆盖即可，不重复造框架。

先确认真实测试名称，使用本机已有 Go 环境：

```bash
cd edge/agent
go test -race -count=1 -run 'TestInitial' .
go vet ./...
gofmt -l initial_scan.go initial_scan_test.go
```

若前缀不足以覆盖该文件，替换为准确正则并记录。调试仅跑新增/失败测试，最终相关测试合跑一次。不跑全项目/全模块全量、浏览器或实机服务；不安装依赖、不联网下载工具链。执行 git diff --check，并单独查新文档空白。禁止删除、跳过或放宽安全断言。

## 6. 禁止操作

不读取 admin-password.private、真实 .env、密码、令牌、私钥、种子；不调用真实 systemctl、不启停或部署服务；不注册设备、不扫描真实目录、不上传、不签发；不提交、建分支、推送、打标签、发 PR；不清理或还原他人成果。

## 7. 交付

记录实际复现、修复、修改文件、命令和通过/失败结果、未运行事项及证据边界。若当前工作树已被其他人修复，核对反证，允许无需代码修改，不重复实现。

结尾明确：未提交、未部署，待主开发者复核；仅该首扫取消子任务完成，不代表 CL-02、CL-07 或整体目标完成。
