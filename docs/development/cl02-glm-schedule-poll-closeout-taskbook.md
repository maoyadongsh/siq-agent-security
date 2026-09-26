# GLM：周期轮询取消与重试状态收口

任务编号：CL-02-SCHEDULE-POLL-CLOSEOUT。
项目目录：`/home/maoyd/siq/siq-agent-security`。

请直接完成修复与定向验证，不只输出方案。禁止扩展功能，不增加接口、配置、命令、依赖或第二套轮询器。用户要求减少重复测试、加快收口。

## 1. 开始前

阅读工作区 `/home/maoyd/siq/AGENTS.md`、项目及相关子目录 AGENTS.md（若有）、工作区 `VIBECODING_SCIENTIFIC_METHOD.md`。
检查 git status、目标文件内容和 diff；未跟踪文件也是既有成果，不覆盖或还原。

必读：

- `packages/contracts/enterprise-discovery-schedule.v1.md`（当前行为，注意近期已更新）
- `edge/agent/discovery_schedule_poll_linux.go`
- `edge/agent/discovery_schedule_poll_linux_test.go`
- `edge/agent/initial_scan.go` 中取消/独立退避的既有约定
- `edge/agent/serve.go` 及相关定向测试（只读）

## 2. 问题与目标

主开发者检查时，scheduleHeartbeatLoop 在 heartbeat 返回后检查 ctx，但 tick 返回后没有再次检查 ctx：tick 返回错误时更新退避并返回 nil；返回 active=false 时会将本地 stopped 置为 true。

请先用合成回调验证：tick 内取消 context 后返回错误，或返回合法 true/false，当前实现是否仍吞掉取消或改变轮询状态。若成立，做最小修复：tick 返回后首先检查 ctx.Err，传播取消，不把取消当成业务成功、停用或普通失败退避。

这不是修改服务端授权；不更改 active、撤销、到期或预算语义。不把模拟回调证明描述为真实服务退出验收。

## 3. 文件所有权

仅允许修改：

- `edge/agent/discovery_schedule_poll_linux.go`
- `edge/agent/discovery_schedule_poll_linux_test.go`

仅允许新增：`docs/development/enterprise-schedule-poll-closeout-handoff.md`。

其他文件只读，尤其禁止修改：discovery_scheduler.py 及其测试（Qwen 在做）、confirm_schedule*、setup_enterprise*、日志/回执、服务状态命令、serve.go、共享 HTTP Client、合同、README、台账、后端、前端和依赖。发现超范围缺陷只记录，不顺手处理。主开发者会维护合同与台账。

## 4. 具体要求

1. 保留 heartbeat 先行、窗口控制、30 秒起步/15 分钟上限、成功重置退避、非 active 停止本次生命周期等现有行为。
2. tick 返回后的取消优先于成功/失败处理，返回 context 取消错误，不修改 stopped/retryAt/delay，也不输出“普通失败重试”日志。
3. 未取消时的网络失败仍独立退避，不抑制健康心跳，不因单次失败永久停止。
4. 不增加自动重放、补扫、自动确认、日志修复、重签或后台 goroutine。任务 ID 仍只由原任务循环领取/验签/执行，不能在轮询处执行。
5. 不改变请求/响应 JSON、认证、超时、大小限制、禁止重定向、严格字段验证及固定错误文案。
6. 不为核对取消而放宽状态判断；未确认/回执不匹配的启动拒绝保持原样。

## 5. 最少验证

先补一个集中参数化测试复现旧实现，再修复。复用已有注入时钟与回调，不真实等待、不运行 systemctl、不访问真实设备。

覆盖 tick 内取消后分别返回：错误、active=true、active=false。断言返回 context.Canceled。必要时在同一闭包上用新的未取消 context 和相同注入时刻再次调用，证明之前取消没有引入 stopped 或退避副作用（这仅是检查闭包状态的测试手段，不是生产自动恢复策略）。既有测试继续覆盖正常停用、窗口与退避，不重复建立新框架。

在 edge/agent 中执行：

```bash
go test -race -count=1 -run 'TestSchedule' .
go vet ./...
gofmt -l discovery_schedule_poll_linux.go discovery_schedule_poll_linux_test.go
```

先确认实际测试名称与前缀；如不覆盖目标文件，使用准确正则并在交接中记录。调试只跑新增/失败用例，完成时相关测试统一一次即可。不得跑全项目或全模块测试、安装依赖、联网下载工具链、新增浏览器验收。git diff --check，并单独检查新交接文档空白。

## 6. 禁止操作

不读 admin-password.private、真实 .env、密码、令牌、私钥、设备种子；不启动/停止/重启/部署服务；不注册、扫描、上传或签发；不提交、建分支、推送、打标签或发 PR；不运行 git reset、checkout --、clean；不更改他人文件。

## 7. 交付

写入指定交接文档：旧行为复现、实际最小修复、修改文件、运行命令及通过/失败结果、未运行事项与证据边界。若未复现问题，提供反证，允许无需代码修改，不制造需求。

明确：未提交、未部署，待主开发者复核。仅完成该取消/轮询子任务，不代表 CL-02、CL-07 或整个目标完成。
