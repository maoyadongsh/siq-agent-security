# GLM5.3Flash：Edge 服务状态命令收口

请直接执行本任务，不只输出方案。项目：`/home/maoyd/siq/siq-agent-security`。
任务编号：CL-02-SERVICE-STATUS-CLOSEOUT。

## 1. 目标

用户要求禁止扩展功能、减少重复测试并尽快收口。本任务只完善既有 `edge-agent user-service-status` 命令的错误、取消、输出及帮助行为，不新增诊断能力、后台任务或生命周期操作。无可复现缺陷时可以报告无需修改，不为产生代码改动创造需求。

主开发者正在修改周期调度、确认、安装及 serve；Qwen 正在修改发行工具。禁止覆盖其成果。本任务不增加周期计划状态字段，不读取设备状态，不改变现有 JSON v1 合同。

## 2. 开始前

完整阅读 `/home/maoyd/siq/AGENTS.md`、项目根 AGENTS.md、相关目录 AGENTS.md（若有）、工作区 VIBECODING_SCIENTIFIC_METHOD.md。

阅读：

- `packages/contracts/enterprise-user-service-status.v1.md`
- `edge/agent/user_service_status_linux.go`
- `edge/agent/user_service_status_linux_test.go`
- `edge/agent/user_service_status_other.go`
- `edge/agent/main.go` 中现有命令入口及错误处理（只读）
- `docs/development/enterprise-auto-onboarding-closeout-20260926.md` 中 CL-02/07

检查 git status --short --branch、上述文件 diff。大量未提交/未跟踪文件属于其他开发者，不得清理、覆盖或还原。修改前重新读取文件，发现同文件正在并行修改则先报告冲突。

## 3. 允许文件

允许修改：

- `edge/agent/user_service_status_linux.go`
- `edge/agent/user_service_status_linux_test.go`

允许新增交接：`docs/development/enterprise-service-status-closeout-handoff.md`。

其余只读。尤其禁止修改 main.go、serve.go、setup*、install_user_service*、discovery_schedule*、confirm_schedule*、共享 Client、安全/权限逻辑、合同、非 Linux 实现、后端、前端、README、发行脚本、公共台账及锁文件。必须越界的问题写入交接交主开发者处理。

## 4. 必须保留的行为

- 只查询当前用户固定 `siq-edge-discovery.service`。
- 固定 `/usr/bin/systemctl --user show --no-pager --property=LoadState,ActiveState,UnitFileState`，不允许用户指定 unit、host、system scope 或 bus。
- 不使用 shell、sudo、PATH 查找，不重载/启用/停止/重启服务。
- 总命令超时维持 20 秒，stdout 上限 4096 字节，stderr 不回显。
- 精确解析三项属性，重复、缺失、额外或错误结构仍失败；未知属性值归一为 unknown，不能回显原值。
- JSON schema 和字段保持原样；heartbeat_verified、discovery_verified、protection_verified 永远 false。
- active 仅是服务管理器状态，不代表安装来源可信、联网、扫描完成或安全保护生效。
- 不读取身份、设备状态、确认日志、令牌或安装目录，不新增网络请求。

## 5. 重点核对与实现

### A. 取消与超时

现有 readUserServiceStatus 在调用 runner 前检查 ctx.Err。核对 runner 返回之后、解析和输出之前的取消行为：即使 runner 返回了看似有效的字节，已经取消的查询也不能被当作成功状态。

用可控 runner 构造“执行期间取消，同时返回有效三属性输出”的复现。问题成立才做最小修复。不要修改全局上下文/超时架构。

### B. 帮助入口

核对 `--help` / `-h` 是否给出可用说明且不调用 systemctl。当前使用 flag.ContinueOnError，不能将 flag.ErrHelp 一概当成业务诊断失败。

如需修复，仅在本命令内处理帮助：说明只读、固定用户服务和 active 的证据边界。正常状态查询的 stdout JSON 不得混入说明文本。未知参数和位置参数仍拒绝，不新增功能选项。

### C. 输出失败与执行失败

确认编码失败能返回错误；manager 不可达/非零退出/超大输出/解析失败不生成伪 inactive JSON，不泄漏原始诊断或环境值。不吞掉错误以让脚本看起来成功。

必要时可在允许文件内提取小型内部函数，以注入 writer/runner 验证真实命令路径。不得新增命令、全局可变替身或环境变量后门，不做无关重构。

## 6. 精简验证

先阅读现有测试名称，复用已有用例。只为确认的修复补少量直接回归，不新增大矩阵、浏览器脚本或整机验收脚本。

至少核对：正常状态未变；取消后不成功；帮助零 runner 调用；未知参数拒绝；错误输出不泄露；三个 verified 字段仍为 false。

在 edge/agent 下运行包含实际修改用例的聚焦 `go test -race -count=1 -run '<准确测试名称模式>' .`。最后执行一次 `go vet ./...`、改动文件 gofmt 检查、git diff --check。不要重复跑整个项目全量或全部模块 race。

所有进程行为使用注入 runner；禁止调用真实 systemctl，即使只是查询。不得为验证启动临时服务、读取真实设备目录或调用 API。不安装依赖。

## 7. 禁止操作

不读取 IDE 中 admin-password.private、真实 .env、密码、令牌、私钥和设备种子。不提交、推送、建分支/PR、部署、签发、发布、注册、扫描、上传、修改数据库。不使用 git reset、checkout --、clean，不清理他人临时目录，不删除或放宽安全测试。

## 8. 交付

写入 `docs/development/enterprise-service-status-closeout-handoff.md`：

1. 实际修改文件。
2. 每项问题的复现、仲裁与最小修复；未发现问题则明确写明。
3. 保持不变的 JSON/权限/只读边界。
4. 实际测试命令、通过/失败数量及未运行项。
5. 范围外发现（若有），不顺手修复。
6. 明确“未提交、未部署；仅此命令收口，不代表 CL-02/07 或整体项目完成”。

最后简洁汇报，不新增下一阶段产品建议或重新扩张任务书。
