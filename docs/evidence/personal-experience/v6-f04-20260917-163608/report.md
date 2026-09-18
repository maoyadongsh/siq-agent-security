# v6 F04 同候选本机真实验收复核（2026-09-17）

## 1. 范围与判定

本批在 `codex/personal-v6-integration-20260917` 的未提交集成树、基点 `9b8c09af742cb9df94c6d02e6f2db6ecccd68951` 上继续 F01–F04。最终运行使用 Linux/arm64 二进制 SHA256 `c8048691276590a064b5314837e35c80a2e8fba48471f1bf12c434f6b9ae9853`，真实 SIQ daemon、OpenShell 0.0.83 网关、独立沙箱及 Playwright 浏览器。D05 退出 0，步骤 **228 pass / 0 fail**；E01–E13 经必要的人工复核后为 **9 pass / 4 partial**。退出 0 只说明脚本无失败步骤，不代表四个 partial 已关闭，更不是发布验收。

F00 的隔离集成基线和 F03 的本机浏览器旅程已有证据；F01 加载确认、F02 停止/恢复、F04 真实执行仍有合同/能力缺口；F05 性能、F06 Linux 原生隐私/通知、F07 企业服务、F08 来源/WorkBuddy、F09 Windows/macOS、F10 最终集成发行均未整体完成。任务分母与解除条件见 [进度台账](../../../personal-v6-integration-progress-20260917.md) 和 [v6 任务书](../../../personal-v6-integration-and-acceptance-taskbook-20260917-135521.md)。

本批使用的是 Hermes 基础镜像中的真实 OpenShell 沙箱。Grant 的 `platform=openclaw` 是测试归属标签；**本腿没有运行 OpenClaw 原生宿主**，不能据此把 N09 Linux/OpenClaw 或九组合矩阵标为 complete_acceptance。

## 2. 实际验证与证据等级

| 项 | 结果 | 等级与边界 |
| --- | --- | --- |
| D05 最终 r7 | 228 pass / 0 fail，进程 exit 0；矩阵 9 pass / 4 partial | 真实 daemon + 真实网关/沙箱 + 浏览器；[公开矩阵](../v6-f04-r7-20260917-180500/d05-acceptance-matrix.json) |
| E02 | A/B 允许正控均 HTTP 200 且各有本批接收端新到达；收紧后 B 明确 HTTP 403、B 零到达；恢复原内容摘要 | 真实网关，接收端通过本批沙箱唯一来源地址校准；不把主机自检算作沙箱到达 |
| E09/E12 | SIGKILL + 同状态目录重启后无重放、链验签和预留读回；浏览器预览、确认、运行、结果、重载、键盘、移动端和失联门均通过 | 真实服务/浏览器；远端停止不在此证明范围 |
| E04/E06/E08/E11 | 仍 partial | 过期 SEC/缺必需 Authority、加载超时/旧 CLI、远端停止确认、持久化故障等子场景未在本腿全部执行 |
| Go | 46 包 `go test ./...`、`go vet ./...`、OpenShell/server `-race` 均 exit 0 | 组件/静态检查；不是其他 OS 实机 |
| Python 驱动 | 9 个回归、语法检查、`git diff --check` 均 exit 0 | 组件/源码卫生 |
| 四目标编译 | Linux amd64/arm64、Darwin arm64、Windows amd64 的 `go build` 均 exit 0 | 仅构建。首次封装脚本因报告相对路径错误 exit 1；已从四个成功产物重新哈希并[落盘](cross-builds.json)，未伪称封装脚本成功 |

逐项命令、退出码及前六次失败开发运行见 [checks.json](checks.json)。r1/r2 揭示既有策略 `Status: Effective` 没有 `Loaded` 时间戳；r3 揭示测试复用已污染会话；r4 揭示预留前拒绝不应假设有持久预留，并暴露进程内新修订加载确认无法重取；r5/r6 进一步定位 E02 多个安全边界共用会话。每次失败均保留公开矩阵，不能从 r7 的通过回填旧候选。

## 3. 实现修正与剩余缺口

任务执行现在同时读取 `policy get --full` 的修订、摘要、状态和 `sandbox list` 的唯一 UUID、`Ready`、`current_policy_version`。0.0.83 对既有策略返回 `Effective` 且无 `Loaded` 时间戳时，只接受另一读回证明该**同一实例**已报告加载相同版本；待加载、版本/摘要/实例不符保持零启动。外部策略变为**新修订**后，新批准可依新的双读回执行，旧修订批准拒绝；未知先前修订或实例更换不能以旧事实解锁。组件负例与真实 K30/E02/E06/E10 共同覆盖这条路径。

驱动按独立用例隔离会话，避免 K60 的拒绝或 E10 的漂移拒绝产生的 taint 抢先挡住 E02 的端点边界；taint 规则本身没有放宽。接收端来源按该批沙箱实测地址校准，必须 A/B 同时匹配且任务产生新到达。E10 的预留前拒绝允许状态读回返回 `reservation_unknown`，不再捏造一个持久预留。E04 原始 r7 运行报告曾把该项写为 pass，但其 E04i 明确有两个未执行子项；[公开复核账本](public-evidence-review.json)保留修改前/后哈希，公开矩阵将 E04 改为 partial，原始私有运行记录仍保留。

尚不能关闭的边界：批准参数未签入沙箱 UUID，跨进程重名替换与策略/批准的原子性未证；网络 binary 范围未进入任务批准合同。OpenShell 0.0.83 的单任务远端停止确认不可用，不能把本地 CLI 终止写成远端 stopped。E04 的过期 SEC 与缺必需 Authority、E06 的加载超时/旧 CLI、E11 的持久化故障、其他 OS/宿主均须另测。F05 性能要求独占机器和冻结协议，本批没有启动，也没有借本批功能耗时充当性能结果。

## 4. 候选、证据与完整性

[candidate.json](candidate.json)记录二进制、CLI、embed、网关、专属沙箱和本机镜像身份；[source-manifest.json](source-manifest.json)列出本地 dirty 应用/合同路径及摘要。这是**本地实验候选**，没有干净提交的可复现发行身份。r7 之后仅调整驱动的公开报告脱敏、E04 等级与临时目录清理；运行时驱动的精确文件哈希未在启动时冻结，已在候选文件明示，不能将当前驱动哈希倒称为 r7 启动时哈希。

公开材料在 `v6-f04-20260917-163608/` 与 `v6-f04-r1…r7`（r1 即根目录）中。目录后缀是批次标签，实际运行时间以矩阵 `started_at` / `finished_at` 为准。七份公开矩阵已经别名化本机绝对源码/私有 env 路径，扫描无裸 32 位十六进制 token 和 Bearer 头；14 个 `*-private/` 根目录命中 Git 忽略，28 个目录均为 0700、1,406 个文件均为 0600。私有原始运行记录不进入公开清单。[SHA256SUMS](SHA256SUMS)只覆盖公开文件，不包含自身。

## 5. 影响、恢复与 Git 状态

修复涉及 OpenShell 加载证明和执行前复验、D05 驱动断言及文档；不改变旧 `policy_apply` 的任务执行语义。若撤销本批，需在本集成分支按文件差异回退代码、合同与本批证据，不得覆盖并行工作树。本批 **未 commit、未 push、未 merge、未签名、未发布**；正式发行种子、外部协作者实机和团队发布门独立判定。

## 6. 资源归属与清理

专属沙箱 `siq-v6-f04-163608`（UUID `de99ab6a-8e47-487d-8f69-6e5b6ae9c7a2`）删除前校验了精确身份、`Ready` 与原策略内容哈希。精确名称删除返回后，立即列表尚能看到该对象；**未重复删除**，下一次只读列表确认对象已消失。七次驱动遗留的 11 个精确归属 `/tmp` 状态根已按来源、UID、非符号链接及进程检查后清理。批次 daemon/浏览器进程和其环回监听已停止；共享 `siq-openshell-dev` 网关及监听 `:17671` 仍运行，未重启或修改。私有构建目录 `/tmp/siq-v6-f04-20260917-163608/` 暂留 r4 二进制与交叉构建产物，供 F05 同候选复核；它不是发布制品，详见 [resources.json](resources.json)。
