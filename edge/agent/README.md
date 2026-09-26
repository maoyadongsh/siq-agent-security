# Edge Agent：受控采集与证据传输

Edge 是企业环境侧的 Go 命令行代理，连接 [Control API](../../apps/control-api/README.md)与 [Connectors](../../connectors/README.md)。它负责设备注册、签名任务核验、受限子进程采集、证据签名和回执，不承担模型规划或个人端工具授权。

## 协议与执行链

企业 `setup-enterprise` 在验签暂存后，先探测所选采集器的版本与范围兼容性，再按实测结果注册；失败在设备身份操作前停止。预检只调用 describe/validate_scope，不扫描配置。启动 `serve` 后会周期复核能力，并在非空能力心跳成功后按已确认、已签发计划申请一次指定设备首扫；原计划重试由控制面去重。首扫失败独立退避（30 秒起、最多 15 分钟），不连带降低正常心跳频率，也不标记首扫成功。当前主线还支持组织创建有界周期计划、设备独立确认、tick 领取与旧计划退役；发现、确认、心跳、领取和完成仍是不同事实。独立 `register`/`heartbeat` 保留历史行为，不能据此声称全部安装方式已迁移。服务端部署须执行全部 Alembic 迁移至当前 head（现为 0028）；正式签名包和真实设备全链仍待验收。合同见 [企业已安装能力](../../packages/contracts/enterprise-installed-capabilities.v1.md)、[首次扫描](../../packages/contracts/edge-initial-scan.v1.md)与[周期计划](../../packages/contracts/enterprise-discovery-schedule.v1.md)。

```text
控制面注册 → 固定设备身份/公钥 → 获取签名采集任务
Connector describe → validate_scope → plan_scan → collect → checkpoint
Edge 签名 → 上传候选/证据 → 任务回执 → 失败回执后续补交
```

Connector 通过 NDJSON 交换结构化消息，不能直接创建 managed 资产或 effective 权限。Edge 对任务和采集执行实施协议、期限与资源边界；控制面继续校验批次、租户、签名和证据引用。设备密钥和签名材料保存在私密状态中，不能连同运行目录上传作证据。

## 构建与使用入口

Linux 可先运行 `edge-agent inspect-host` 获取只读主机摘要：系统发行版、二进制架构、内核架构与固件/设备树型号，各自带来源和缺失/无权限状态。固定读取系统元数据，不读取密钥、用户配置或上传数据；环境名不构成 DGX 硬件证明。安装引导消费该摘要仍待集成，输出中的 `hardware_attested=false` 不得改写为认证成功。

从仓库根构建；命令中的注册码由目标控制面实际签发：

```bash
mkdir -p .tmp/bin
go -C edge/agent build -o "$PWD/.tmp/bin/edge-agent" .
.tmp/bin/edge-agent --help
```

| 命令 | 行为 | 前提 |
| --- | --- | --- |
| `serve` | Linux 常驻心跳 + 串行任务轮询，失败有界退避，信号取消后等待在途工作结束 | 已注册状态、私密设备目录；与 Linux `tasks` 共享排他锁。不自动注册、安装 systemd 服务或授予业务权限 |
| `service-unit --binary PATH --state-dir PATH --connector-dir PATH` | 只向 stdout 输出 Linux systemd 用户服务配置，不安装或启动 | 路径须明确、绝对且无展开字符；生成不证明制品签名、身份或目录权限已验证 |
| `user-service-status` | Linux 只读输出当前用户 SIQ 服务的加载、运行和启用状态 JSON | 不读取设备凭据，不注册/扫描/启动；active 不等于心跳、发现或防护已经核验 |
| `verify-enterprise-release --release FILE [--bundle DIR]` | Linux 验签；可选核对包内所有签名制品 | 固定公钥、不接受覆盖；未传 bundle 不核对制品；均不证明计划授权或安装成功 |
| `register --control-plane URL --enrollment-code-stdin` | 注册设备并保存服务端凭据与本地签名身份 | 有效注册许可，目标 URL 明确；从标准输入读取，不把真实 code 写入命令参数 |
| `heartbeat` | 30 秒心跳，失败退避 | 已注册状态；持续进程 |
| `tasks` | 获取待处理任务、执行扫描并提交回执 | 已注册且凭据有效；先补交本地 pending receipts |
| `run-once --connector NAME --scope JSON --connector-bin PATH` | 一次本地采集并输出 NDJSON | 可信 Connector 二进制与受控范围；不自动纳管或上传 |
| `confirm-discovery-schedule (--intent FILE \| --schedule-id ID \| --discover \| --resume)` | Linux 预览或明确确认有界周期计划；`--discover` 只读查找本设备待办 | 四种来源严格互斥；查询不授权，多项不自动选择；确认需真实终端 yes 或精确摘要 |
| `retire-discovery-schedule [--resume]` | Linux 预览或归档已在线复验为 revoked 的旧周期计划 | 不撤销业务权限、不停止服务、不取消已派发任务；历史和恢复记录保留 |
| `setup-enterprise --help` | Linux 串联计划确认、发行验签暂存、注册/恢复与用户服务配置 | 默认只配置；显式 `--start` 才启动发现服务；新设备的组织周期计划仍需另行创建和确认 |

Linux 后台服务、心跳和任务命令读取设备身份时要求绝对、私有状态目录及安全父目录，
拒绝符号链接、硬链接、组/其他用户可访问的状态文件、超大或歧义 JSON。
旧目录不满足要求时会停止，不自动改权限、删除身份或重新注册；应先由设备所有者
检查目录归属与权限。具体边界见 [设备状态读取合同](../../packages/contracts/enterprise-device-state-read.v1.md)。

企业控制台的“环境与设备”提供创建环境、生成一次性码、命令选择与真实状态读回。已有本地 `state.json` 时注册会拒绝，请使用原身份启动心跳和领取任务；不要通过删除状态重试，以免失去原设备身份。旧 `--enrollment-code` 参数仍兼容，与标准输入模式互斥。

Bash 示例（不把注册码写进历史或进程参数）：

```bash
read -r -s -p '注册码：' siq_enrollment
printf '\n'
printf '%s\n' "$siq_enrollment" | ./edge-agent register \
  --control-plane https://security.example.com --enrollment-code-stdin
unset siq_enrollment
./edge-agent heartbeat
# 另开终端，在同一用户下运行：
./edge-agent tasks
```

注册、心跳和扫描回执是不同事实。页面只有读到扫描完成回执才展示完成；候选发现不自动纳管，也不代表运行时策略生效。批次签名先转换为实际 wire JSON，再规范化签名，支持 Connector 产生的结构化候选/证据数组。E143 的真实 Edge + Hermes Connector + Control API 验收见 [记录](../../docs/development/ux-enterprise-onboarding-e143-validation-20260923.md)。

实际可选模块见 [Connector 列表](../../connectors/README.md)，范围字段以 [protocol](protocol/)和各模块的验证器为准。不要对未知目录或整机根目录运行试探扫描。

## 实现与验证

安装前先预览：`setup-enterprise --review-only --plan FILE --tenant ID --environment ID --control-plane ORIGIN [--start]`。输出组织/环境、有效期、采集器及 roots/include 文件范围和确认摘要，明确是否请求启动服务。预览不需要注册码或发行包，不读取设备私密身份、不落盘、不启动扫描；其中 release_signature_verified=false，不能把它当成制品认证。阅读后由用户另行确认，再运行安装入口，禁止脚本仅凭预览摘要自动批准。

统一开发入口：`setup-enterprise --help`。将确认计划、可信暂存、环境绑定注册/原身份恢复/既有身份复用、采集范围保存和用户服务安装串为一次调用。自动化采用确认摘要和 --enrollment-code-stdin；Linux 终端可改用 --interactive，直接阅读组织/环境/范围后输入 yes，默认取消，首次注册码在验签后提示且不回显，不进入命令参数。交互确认期间计划变化或过期拒绝。输出逐阶段 NDJSON（交互模式另有提示），暂存成功后即返回 stage_path，后续失败可用 --resume-stage 重验继续。默认只配置，显式 --start 才启动发现服务，不批准业务权限。未签名制品在注册前拒绝，失败不删除身份或暂存。serve 已接入确认范围内的去重首扫申请，但包下载、完整生产签名包/systemd 一次安装与结果页真实验收仍未完成，不作为已发布一键安装承诺。

Linux 用户服务安装开发入口：`install-user-service --release FILE --stage DIR [--start]`。要求本机已注册并确认仍在安装期限内的 user 模式计划，重新验签和核对暂存文件后写入当前用户 systemd 单元；相同内容可重试，不覆盖不同配置。默认只写配置，显式 --start 才执行用户级 reload/enable/start 和 active 检查，不提权、不启用 linger。失败保留状态和制品，可能留下已启用但未运行的单元；完整升级/回滚及真实登录退出/重启验收待完成。命令使用中的 Edge 排他锁会拒绝并发安装，测试仅使用模拟服务管理器，当前不承诺部署即开机自启。

Linux 范围确认底层入口：`confirm-discovery-plan --plan FILE --tenant ID --confirm-plan-sha256 DIGEST`。核对已注册状态、当前计划与明确确认后，仅保存本机扫描限制；不注册、不扫描、不授权业务。需先停止 serve/tasks 以取得排他锁，确认后重新启动服务。已确认设备的签名任务仍必须使用明确采集器及允许的 roots/include 子集，超范围返回 discovery_scope_denied；旧设备未保存计划时仍属 legacy，不能声称已验证范围。统一安装入口已复用该确认阶段，但制品信任、设备注册和周期计划仍保持独立核验。

注册失败注意：首次请求发送前会保存私密 `registration-pending.json`，含设备签名种子，切勿上传、提交或在聊天中粘贴。注册不会自动重试；若结果不确定，再次注册会停在 `registration_pending`。请保留该身份，不要删除后盲目重注册。成功身份仍使用 state.json。

安装计划接入时，`register` 应携带 `--environment ID`（来自确认的计划）。新服务端在消费注册码前检查其真实环境，不匹配不消费；客户端还会核对返回环境，且恢复时不得改变首次保存的预期环境。未传此参数仅为旧客户端兼容，不算已绑定安装计划。旧服务端可能拒绝新字段，不得自动去掉参数重试。

Linux 开发恢复入口：`edge-agent recover-registration --control-plane ORIGIN --environment ID`。仅适用于服务端已部署恢复接口和迁移 0018、注册后 15 分钟内且尚未心跳的设备；必须明确原控制面与环境。先持久化 0600 随机恢复凭据，再以原设备私钥签名；响应丢失后重复命令沿用同一凭据。已有 state.json、环境/origin 不符或凭据文件异常时拒绝，不自动删除文件、不执行扫描。恢复凭据文件也不得上传。原生流程已在隔离环境验证，尚未上线或集成到最终安装引导；过期、已活跃或已吊销设备不能通过此入口重新接入。

开发中的企业安装入口：`edge-agent prepare-install --help`。它接受已认证控制面取得的计划、发行清单、制品目录、私密暂存父目录、预期组织/环境/origin 和用户确认的计划文件 SHA-256。先核对当前期限及本机架构，再调用固定发行公钥验签和暂存；只输出 `staged_only`，不注册、扫描、启用服务或授予权限。确认摘要前必须审阅该计划的组织和采集范围，不能用下载后自动计算摘要替代用户确认。

这是面向安装引导开发的底层入口，**不是最终用户一键安装流程**。暂存父目录及祖先须由调用者控制且稳定；不自动创建父目录或提权。缺少正式签名企业包时不能用测试公钥绕过。输出失败可能已留下完整暂存目录，后续恢复必须重新验证，不能盲目依赖 READY；安装/注册恢复及服务激活仍待实现。

暂存恢复：用 `--resume-stage DIR` 替代 `--bundle DIR --staging-parent DIR`，其余计划、确认摘要及预期上下文参数仍必填。恢复只读验证已有私密目录、发行签名、清单/READY 和实际制品，不创建新暂存，不自动修复残留。过期计划仍拒绝；这是文件准备阶段的恢复，不是设备注册或服务生命周期恢复。

[main.go](main.go) 是 CLI；[state.go](state.go) 管理本地状态；[protocol](protocol/)是 Connector 共享类型；完整线协议见 [connector-protocol.v1](../../packages/contracts/connector-protocol.v1.md)。开发检查：

```bash
go -C edge/agent vet ./...
go -C edge/agent test ./...
```

当前 `run-once` 可选择 12 种 Connector（新增 `siq` 本地业务安全事件投影）；注册请求的 capabilities 仍只声明 hermes、docker、directory、openclaw 四种。模块可构建不能证明所有 Connector 已通过远程任务调度或客户环境验收，部署者须核对实际能力声明。采集到配置/进程只证明对应证据存在，不证明宿主已经受运行时保护。

周期计划入口是当前主线源码能力，尚未包含在公开 `0.3.1` 或较早的本机 `0.4.0-rc.2` 候选中。隔离测试证明零/单/多待办、完整性失败、取消与恢复边界；它不替代真实组织身份、真实 systemd 用户服务、长期轮询、升级恢复或多架构原生安装验收。

Linux 凭据轮换开发入口：`edge-agent rotate-credential --confirm-device DEVICE_ID`，需控制面支持轮换接口及迁移 0026。操作者须先按部署流程停止共用状态目录的服务；命令不会自动停止服务，任务锁占用时拒绝执行。轮换只改变 Edge 控制面凭据，不授予业务权限、不更换设备签名私钥。

命令发送前私密保存待恢复日志。结果不确定时保留原状态和日志，使用 `edge-agent rotate-credential --confirm-device DEVICE_ID --resume` 核对同一请求；不要删除日志或重新注册。只有验证成功且状态未变化时才持久激活新凭据并清理该次日志。日志含新凭据，不得上传、粘贴或提交。吊销、状态漂移或文件损坏不能靠自动重试修复。此入口目前只有隔离测试证据，未证明真实服务升级、正式发行和实际设备生命周期验收。
