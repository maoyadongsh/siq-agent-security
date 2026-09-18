# Windows 任务升级、回退与恢复：组件和原生证据

2026-09-18。本批实现 Windows 的 `service-upgrade` / `service-rollback` 分派，以及共享启动屏障保护下的签名任务切换。任务删除、排他创建、优雅停止、启动和目录/版本健康验证复用现有实现。

源码候选：`319d3ac4cf4f56a17f212ed45a927e7e29957490`。独立分支 `codex/windows-task-upgrade-20260918`，基于本地主集成 `1747f6c`。合同先于实现：`003964b` → `b6b9575` → 实现 `e7c14e3` → 原生拒绝原因断言 `319d3ac`。证据提交不改变运行时代码。本候选尚非整轮 Windows 最终集成候选。

## 实现边界

- `local-windows-task-switch/v1` 绑定源/目标 XML、签名归属、当前实例、目录、同一用户 SID 和二进制摘要；每个新事务使用随机 nonce，避免升级、回退后再次升级复用历史完成凭据。严格拒绝外层及嵌套对象的重复、大小写混淆、缺失、未知和 null 字段。
- Prepare 发布不可变事务和 pending；Apply 只替换两份已认证的 before/after 配置；系统目标任务核验为空闲后 Finish 才追加 done 并移除 pending。done 仅表示配置切换完成，实际运行及版本健康另验。
- 已完成且运行中的目标只有在本地配置、系统任务、摘要和版本健康一致时才幂等复用。恢复不能删除未知任务，也不能把运行中的源当作可删除对象。全部写入持对应主 Writer 和 service-control Writer；启动前释放主 Writer。
- 回退复用历史清单和二进制快照校验逻辑，反向绑定原事务；恢复读取原记录的 XML，不以当前 CLI 路径猜测旧配置。没有状态备份回放，不写业务授权或撤销记录。
- 生产发行信任根、历史签名清单及系统生命周期均未修改。

## 验证结果与真实退出码

| 检查 | 结果 | 证据 |
| --- | --- | --- |
| 新状态层与编排组件 | exit 0；10 个顶层、62 个子用例通过；无 skip | `component.jsonl` |
| Windows 生命周期与共享状态事务选中回归 | exit 0；15 个顶层、36 个子用例通过；无 skip | `regression.jsonl` |
| 补充回归 | exit 1；3 个顶层通过、3 个顶层失败；子用例 9 通过、7 失败；无 skip | `regression-extra.jsonl` |
| 修改前基线的 macOS 夹具复验 | exit 1；相同 3 个顶层测试失败 | `baseline-macos-fixture.jsonl` |
| Python 合同及签名互验 | exit 0；4 passed；依赖锁与既有 venv 相同 | `test_windows_task_switch_contract.py`、合同样例及 Go 反向对等断言 |
| Python 新文件 ruff | exit 0 | 初次 E501 已修复，未放宽规则 |
| 模块 `gofmt -l .`、`go vet ./...` | 均 exit 0，输出为空 | `static.json`、对应日志 |
| Windows amd64 两个测试版本、Linux amd64/arm64、Darwin arm64 构建 | 全部 exit 0；全部 `vcs.modified=false` 且源码 SHA 匹配 | `builds.json`、各产物 `.buildinfo.txt` |
| 干净 Windows 产物的真实计划任务旅程 | exit 0；1 passed，无 skip | `native.jsonl` |
| 测试后独立系统/进程核查 | exit 0；任务缺席、源/目标进程为零、无 pending 和主 Writer；2 个完成事务 | `independent-cleanup.json` |

组件测试在提交前执行，随后仅调整 Python 行格式、原生测试清理注册时机和原生拒绝原因断言；组件涉及的运行时代码及其测试与上述源码候选相同，因此保留原日志而不重复整批。原生旅程在固定候选的干净构建上重新执行。开发阶段曾有一次 Go 命令路径错误及一次测试辅助函数重名导致编译失败，均已修正；这些失败尝试不计作测试通过。

补充回归失败为 `TestSwitchLaunchAgentUpgradeThenRollback`、`TestSwitchLaunchAgentFailedStartRecovers`、`TestSwitchLaunchAgentRefusesWithoutMutation`。现有夹具将 Windows `t.TempDir` 路径交给 macOS 渲染器，得到 `launch-agent: canonical absolute UTF-8 paths required`。在隔离导出的修改前 `1747f6c` 源码中复现相同失败；未跳过测试、放宽产品路径规则或将其记为通过。主集成任务已接收修复。

## 原生旅程的实际覆盖

本次使用同一源码的两个明确测试版本：

| 测试产物 | 版本 | SHA-256 |
| --- | --- | --- |
| source.exe | `0.0.0-win-switch-source` | `f8fadd2fc44f41643fbac5885045cc17483e65d8553d1c7d5a41108933cc01bc` |
| target.exe | `0.0.0-win-switch-target` | `581c027f329dc6761567d300a5090e4dafd249e52ce0988663b6942278b957e3` |

在独立私密状态目录内创建本实例当前用户任务，真实运行 source，核验目录和版本健康。实际调用生产 CLI，以测试清单执行升级，必须明确返回 `skillmanifest: untrusted signing identity`，且 source 仍健康。

正向切换由显式 opt-in 原生测试驱动产品编排函数，使用真实 Task Scheduler 和真实服务进程，按实际文件摘要校验候选。目标任务实际创建成功后，测试驱动故意返回失败，模拟系统响应丢失。验证 pending 仍存在、普通启动入口拒绝、系统目标为空闲；再以记录 ID 恢复，目标真实运行且健康，重复恢复不重新启动。最后执行反向事务，source 版本重新健康，`config.json` 字节保持一致。

这里的测试版本、测试驱动候选校验和生产 CLI 的负向拒绝各有明确边界：**未提供或替换正式发行私钥，未宣称通过生产 CLI 的正式签名正向升级，也不是两个历史正式发行版本的兼容性证明。**

测试结束后通过产品的签名优雅停止及精确注销清理任务。另以独立 COM 枚举查询精确任务名、查询精确产物路径对应的进程，并核查 pending/Writer 缺席和完成事务数量；原生输出不是唯一判据。私密状态及构建文件保留作恢复/审计材料，不上传密钥、token、原始系统任务 XML 或真实用户 SID。

## 复现

在 Windows 的本候选干净工作树中，使用仓库要求的 Go 工具链构建两个产物：

```powershell
go build -ldflags '-X main.Version=0.0.0-win-switch-source' -o <私密测试目录>\source.exe ./cmd/agentshield
go build -ldflags '-X main.Version=0.0.0-win-switch-target' -o <私密测试目录>\target.exe ./cmd/agentshield
```

上述命令工作目录为 `apps/agentshield`。将 TEMP/TMP 指向本轮私密测试根，设置 `SIQ_TEST_WINDOWS_SWITCH=1`、`SIQ_TEST_WINDOWS_SOURCE`、`SIQ_TEST_WINDOWS_TARGET` 为实际绝对路径，设置两项 `SIQ_TEST_WINDOWS_*_VERSION` 为表中测试版本，再执行：

```powershell
go test ./cmd/agentshield -run '^TestWinTaskSwitchNative$' -count=1 -json
```

该 opt-in 用例会创建和清理单个隔离当前用户任务；没有 opt-in 时明确 skip，不冒充原生通过。正常组件验证：

```powershell
go test ./internal/state ./cmd/agentshield -run '^TestWin(Switch|TaskSwitch)' -count=1
```

没有 opt-in 的后一条命令会明确跳过原生用例；本批组件日志使用新增原生用例前的同一组件代码执行，原生验证另有实际 opt-in 的完整日志。

## 未完成的验收与交接

本批只为 P03-STATE-16/17/20/21 提供部分实现及证据，保留原验收状态，不增加 303 项的已通过数：

1. 正式 v3 签名发行清单与生产 CLI 正向暂存、升级、恢复、回退仍需完整验证。
2. 真实撤销/业务权限记录在升级及回退中保持拒绝、旧/新二进制文件占用、缺失二进制恢复、v3 摘要与状态兼容边界尚需补齐原生组合证据。
3. 整轮最终集成候选尚未固定；未执行最终 `go test ./...`，所需全套回归及受影响宿主复验由主集成继续完成。已知 macOS 夹具失败保留，不能声称全量检查通过。
4. 系统重启、注销、睡眠等仍为用户要求本轮不执行；未调用模型、未扩展 WorkBuddy 额度、未合并 main 或发布制品。

本批结论为“Windows 可恢复任务切换实现及限定原生旅程已验证”，不是本轮 Windows 验收全部完成。

公开文本做路径脱敏、统一 LF 换行；buildinfo 移除行尾空白。未改测试结果、退出码或失败原因，原始输出保留本机。目录内 `.gitattributes` 保持公开证据跨平台字节一致，`sha256sums.json` 对应公开文件字节。
