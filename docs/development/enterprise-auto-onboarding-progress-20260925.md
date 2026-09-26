# 企业自动接入持续开发记录（2026-09-25）

关联[22 项任务书](enterprise-auto-onboarding-taskbook-20260925.md)。用户已明确要求设为持续目标并持续开发，目标状态为 active；实施、源码验证、在线部署和正式发行分别记录。

## 第一批：现场/安全基线与设备入口修复

### 范围与所有权

- Agent Security：ENT-001 的源码/安全基线脚本与记录，ENT-020 初始回归。
- Gateway：ENT-002 专用 Edge 路由及其回归，复用现有代理，不复制设备授权逻辑。
- Platform：只读核查，未修改；三个仓库原有脏工作树均保留，不提交、不重置。
- 尚未操作真实设备注册、资产采集上报、OpenShell 策略或在线容器切换。

### 实际基线

经现有 IAM 登录后只读查询企业 API，确认仅有 1 个环境，名称匹配用户已建的 DGX Spark，模式 discovery，设备 0、证据 0；查询完成后退出临时登录。没有通过开发身份访问生产，也没有在文档或输出中保存管理员凭据。

新增 `scripts/enterprise-experience/source-baseline.py` 只记录白名单源码目录与扩展名的摘要，排除忽略文件、私密状态及符号链接，不覆盖已有证据。源基线见[三仓源码身份](../evidence/enterprise-auto-onboarding-20260925/source-baseline.json)：Agent Security 1630、Gateway 33、Platform 46 个文件。摘要记录时 Gateway 本批路由尚未修改，可用于区分本批与既有改动。

复用原有 `scripts/personal-experience/security-baseline.py` 执行无缓存全量本机 Go 回归，成功记录 3689 条测试通过事件（含子测试），273 个受保护文件；不把事件数当作独立顶层用例数。完整结果位于本机 `.tmp/enterprise-auto-onboarding-20260925/before.json`，SHA-256 为 `af735d8975db7b31310e36a044de5e6d1399be654e681a54e851c31f98b920e0`；测试日志摘要为 `f966488aacb716e1cf8698f0b3a46c8cd781f59ece32ac2c0f708aa9d99cf9bb`。

此轮未修改运行状态，不把源码快照称为状态备份。部署前须新建当时状态的私密备份并复验恢复；既有恢复依据为[企业部署记录](enterprise-runtime-delivery-20260924.md)和[个人端部署记录](personal-console-deployment-20260925.md)，不能将旧备份当作后续新增数据的恢复点。ENT-001 的部署前备份门槛仍保留。

### ENT-002 源码修复

Gateway 的 `src/siq_gateway/main.py` 新增 `/edge/v1/` 到既有 `SIQ_AGENT_SECURITY_URL` 下 `/edge/v1` 的转发；浏览器 API 前缀保持不变。`edge.py` 将 `/edge` 与 `/edge/*` 纳入禁止 SPA 兜底的命名空间，未配置版本返回 404，不再把网页 200 当成设备接口成功。

协议说明位于 Gateway `docs/agent-security-edge-route-v1.md`；新测试 `tests/test_agent_security_edge_route.py` 验证默认映射、请求体/查询/身份头原样转发、上游拒绝、HEAD/OPTIONS、路径拒绝和匿名请求不注入凭据。采用合成上游，不冒充实际设备端到端注册。在线 Gateway 仍未更换，现场路由问题尚未宣称解决。

### 验证

| 命令 / 所属仓库 | 结果 / 范围 |
| --- | --- |
| `python scripts/personal-experience/security-baseline.py --output .tmp/enterprise-auto-onboarding-20260925/before.json` / Agent Security | 通过；全量本机 Go 回归和受保护源码基线 |
| `uv run pytest -q tests/test_agent_security_edge_route.py tests/test_m1.py -k 'edge or Edge or stream'` / Gateway | 47 passed，36 deselected；包含现有真实 HTTP 传输测试及新增合成上游路由测试，不等同实际企业跨服务旅程 |
| `uv run pytest -q` / Gateway | 168 passed，4 skipped，68 warnings，74.84 秒；跳过项不计通过，不替代实际部署验收 |
| `uv run pytest -q app/tests/test_environment_onboarding.py app/tests/test_enrollment_flow.py` / Control API | 11 项通过；隔离数据库与开发身份的接入、租户边界及注册回归，不替代生产 IAM 验收 |
| `uv run ruff check scripts/enterprise-experience/source-baseline.py` / Agent Security | 通过 |
| 两仓 `git diff --check` | 通过 |

保留已有 Starlette/httpx 弃用警告及 Gateway 测试短 HMAC key 警告；未修改生产算法、依赖或测试秘密以掩盖提示。

### 当前缺口与接续

ENT-001、ENT-002、ENT-020 为 doing；没有整体完成项。Gateway 全量回归已通过；下一步补真实隔离 Control API 与 Gateway 的注册/心跳/任务/上报/吊销链路，再推进 ENT-003 安装与实际能力合同。ENT-002 未达实际链路/上线门槛之前不得标记 delivered。

回退仅针对本批明确增加的路由和条件，不得用 `git checkout/reset` 覆盖 Gateway 原有身份、计费、反代等用户改动。当前没有在线回退动作。

## 第二批：真实隔离网关链路与安装合同设计

上一目标轮属于 progress：已实际修改路由、生成基线并执行测试。本轮重新核对工作树和台账后继续，不重复创建目标或重跑无变化的全量回归。

新增 `scripts/enterprise-experience/gateway-edge-smoke.py`，以各仓库自己的 Python 环境启动真实 Gateway 和 Control API，使用新构建的原生 Edge / Hermes Connector，经真实 loopback HTTP 执行；两个独立临时 SQLite、合成租户、临时 HOME 与仅含合成配置的 profile，不导入兄弟仓库模块或访问在线用户数据。

最终[第三轮证据](../evidence/enterprise-auto-onboarding-20260925/gateway-edge-smoke-r3.json)记录 7 项通过：匿名拒绝/未知版本不落 SPA、跨租户环境拒绝、原生注册/已有身份保留/一次性码重放拒绝、原生心跳读回、其他环境任务不可领取、原生 Connector 签名上传和回执读回、吊销后心跳/任务/批次上传在线拒绝。证据绑定测试脚本、Edge/Connector、Gateway 及 API 源码摘要；不是生产 IAM、PostgreSQL 或在线交付证明。

复现命令（先分别构建 `edge/agent`、`connectors/hermes` 到临时 bin）：

```bash
python scripts/enterprise-experience/gateway-edge-smoke.py \
  --gateway ../siq-gateway \
  --edge .tmp/enterprise-auto-onboarding-20260925/bin/edge-agent \
  --connector-dir .tmp/enterprise-auto-onboarding-20260925/bin \
  --out .tmp/enterprise-auto-onboarding-20260925/new-run.json
```

脚本拒绝覆盖已有证据。进程仅监听回环，成功/失败均停止本轮创建的子进程并清理临时库和凭据。R1 在完成采集回执后，吊销注入辅助进程因未调用 init_db 失败；失败证据保留为 `gateway-edge-smoke-r1.json`。修正后 R2 七项通过，R3 增加代码身份摘要后重跑通过，未改变业务断言。Ruff 检查通过。

当前产品尚无设备吊销管理端点，本次通过 Control API 所属进程直接在**本轮临时库**注入 revoked_at，再经 Gateway 验证在线拒绝。这是显式故障注入，不冒充用户可操作的吊销管理流程；ENT-021 仍需补该管理能力与审计。

ENT-002 的隔离实际传输/原生采集路径已验证，仍为 doing：生产身份、部署前恢复点及在线切换未完成。ENT-003 开始 doing，新增[安装接入合同设计](enterprise-install-contract-design-20260925.md)，明确可信传输、实际能力、安装状态与响应丢失恢复；尚未产生可运行的新安装 API。

新确认的部署条件：现有 Edge 仅允许 HTTPS 或回环 HTTP，当前 LAN HTTP 网页地址不能直接用于远程 Edge 注册。后续交付需可信 TLS 或明确同机回环接入方案，不能放宽到明文私网注册。该条件不阻断源码开发，在线配置按授权处理。

下一步：落实 ENT-003 版本化安装/实际能力 Schema 及兼容测试，再实施安装器和常驻生命周期。真实设备接入、业务权限变更和线上服务保持未动。

## 第三批：安装计划可执行合同

上一轮为 progress：实际隔离端到端七项验证及失败原因记录已完成。本轮复核现场源码后，新增 `enterprise-install-plan/v1` Schema、`app/install_plan.py` 严格线格式模型及 `test_enterprise_install_plan.py`。

模型拒绝未知字段/凭据混入、非 Linux 或未知架构、非 discovery 用途、空列表、重复 Connector ID、非法摘要、远程 HTTP、origin 用户信息/路径/查询/端口异常、危险根目录/路径穿越/秘密文件名。安装期限最多 15 分钟，明确区分可供审计的历史解析与执行前当前时间验证。字段中的 tenant/environment 仍必须由未来签发 API 从可信上下文派生；校验成功不是身份验证或业务授权。

首轮 88 项新合同测试通过；随后补充 `http://LOCALHOST` 的模型/Schema 一致性拒绝，新测试共 89 项。与原 Schema、环境向导、注册回归合跑 **378 passed，1 条已有弃用警告**，耗时 2.96 秒；Ruff、git diff --check 通过。[命令及源码摘要](../evidence/enterprise-auto-onboarding-20260925/install-plan-contract-r1.json)。

设计文档第 6 节同步具体边界：当前 scope 是文件型，容器/进程等非文件范围需要独立类型化合同，不能用假目录代替。12 种 Connector 枚举不代表已完成实际能力校验、发行或自动调度。

ENT-003 仍为 doing；本轮没有计划签发路由、Go 消费者或已可用的安装器，不将合同测试称为自动接入完成。下一步完成 Go 对等消费/线格式回灌与受认证计划生成，继续实际能力声明和安装生命周期。原生产 API、个人安全核心及 Gateway 在线实例未改动。

## 第四批：Edge 安装计划消费与跨语言对等验证

上一轮属于 progress（新增可执行 Schema/Python 模型与验证）；本轮重新检查工作树后补 `edge/agent/installplan`。该包严格解析全部层级的精确字段，拒绝缺失/额外/大小写变体字段、null、重复键、尾随 JSON、超大输入和过深嵌套，固定错误码不回显输入。语义校验覆盖 origin、端口、UTC 时间与 15 分钟期限、版本/摘要/采集器唯一性及范围；RequireCurrent 核对预期租户、环境、控制面和架构，边界时刻拒绝。

新增 Go 正向、身份替换、到期、JSON 歧义与非法字段测试；Python 生成独立临时共享语料并调用实际 Go 消费，接受结果再序列化回灌 JSON Schema/Python 模型。不是仅比较手写类型。普通 Go 测试中 wire parity 项会提示需要 Python 语料；本批 Python 测试已实际执行该路径，未以跳过代替通过。

验证：Edge `go vet ./...`、`go test -count=1 ./...`、`go test -race ./installplan` 通过；Python 新合同 90 项、组合回归 **379 passed，1 条原有弃用警告**；Ruff、gofmt、git diff --check 通过。[证据与源码摘要](../evidence/enterprise-auto-onboarding-20260925/install-plan-go-r1.json)。上一批源码摘要作为历史快照保留，新测试变更由本批摘要承接。

安装计划消费库仍不是已经接入的安装命令：可信发行签名、实际制品/宿主核对、用户范围确认、受认证签发路由和设备注册恢复继续待办。ENT-003 保持 doing。下一批先接受认证的计划产生方，禁止让客户端自报 tenant/environment 或 release digest 成为可信计划；实际安装权限与企业业务权限仍分离。线上服务、设备状态与既有防御没有改动。

## 第五批：受认证计划生成 API

已实现环境下 `POST /install-plans`，要求验证租户内环境及 `edge:manage`、`env:manage` 权限。请求合同仅接受架构、服务模式、采集器选择，拒绝租户/环境/origin/摘要/范围覆盖。组织归属由服务端派生，制品与范围来自显式部署目录 `SIQ_AS_INSTALL_CATALOG_FILE`；目录加载拒绝非法权限、末级符号链接、重复键、超大及非法数据，无法使用时固定 503，不回显内部内容。部署目录不代替发行签名验证，父目录可信由部署者保证，范围见设计第 7 节。

计划仅 discovery_only，15 分钟期限，无注册码和业务 grant。返回前提交 ID/摘要/数量审计，审计失败不返回计划；不创建设备/注册许可或任务。重复请求生成不同计划，不声称已有安装幂等。在线实例未配置目录、未部署接口。

首轮接口 18 项测试通过，Ruff 发现 7 处超长行，限定三个新文件格式化后通过。补请求 Schema 和实际 API 响应 Go 消费后，组合 **399 passed**，Control API 全量 **1206 passed，1 skipped，1 条既有弃用警告，22.71 秒**。跳过项为需外部线格式样例的旧批量合同测试，不计作通过。Ruff、diff 检查通过。[源码摘要与结果](../evidence/enterprise-auto-onboarding-20260925/install-plan-issuer-r1.json)。

本轮沿用隔离数据库和开发测试身份，未将其外推为生产 IAM 验收。ENT-003 仍 doing：实际能力、注册恢复与完整安装合同尚未结束；下一步构建可信企业制品清单与安装器/后台生命周期，不能停留在计划生成。既有业务权限与在线防御均未改变。

## 第六批：Linux 统一常驻运行

新增 `edge-agent serve`，以既有注册身份并发运行心跳和串行任务轮询（30 秒周期、失败退避至 15 分钟）；复用原任务签名、账本、pending receipt 和上报流程。取消时等待两个循环和在途工作结束后释放锁。Linux `serve` 和旧 `tasks` 共享排他 flock，锁文件不删除以免出现两个 inode 的所有者；拒绝不私密目录、符号链接/多链接/非普通文件和错误所有者。非 Linux 的旧 tasks 不改，serve 明确不支持，不外推跨平台常驻能力。

添加独立心跳、取消等待、故障重试、参数、锁排他/释放和非法锁文件测试。首轮竞态测试失败于 t.TempDir 的目录权限不符合 0700 条件，修正测试夹具权限后 `go vet ./...` 与 `go test -race -count=1 ./...` 全部通过；未放宽运行时检查。新增服务外层重试日志不输出原始错误；复用的旧任务日志仍需后续完整隐私复核，不据此宣称所有日志都已完成脱敏。

实际构建原生 Edge，扩展既有隔离 Gateway/Control API 脚本的 `--serve` 模式，不再手动执行 tasks。真实心跳、后台自动领取/签名扫描/上传/回执、跨环境拒绝、吊销在线拒绝等 **8 项通过**，包含服务运行时手动任务执行器被排他锁拒绝。[实际证据](../evidence/enterprise-auto-onboarding-20260925/edge-serve-r1.json)绑定当前脚本、二进制及服务代码，所有夹具进程终止，临时用户/数据库清理；未连接真实设备或切换在线实例。Ruff 与 diff 检查通过。

ENT-005 从 todo 进入 doing，仅常驻进程与排他链路实现；尚无 systemd 安装、可信制品升级、掉电/登录退出生命周期验证。ENT-004 可信发行安装器与 ENT-007 实际能力/调度合同仍待完成，不将“一个命令可常驻”当作完整自动安装交付。

## 第七批：可验证的 Linux 用户服务配置

上一轮为 progress（真实 serve 与采集链路）；本轮检查工作树后新增 service-unit CLI，显式接受二进制、状态、Connector 目录并只输出 systemd 用户单元。规范路径校验拒绝控制/换行、相对路径和展开字符，ExecStart 直接调用 Edge serve，不经 shell；固定私密 umask、禁止提权、有限重启与进程组停止行为。

四个新增测试覆盖模板/非提权边界、路径注入、只输出和真实 systemd 离线语法。首轮原生解析拒绝带引号的 WorkingDirectory，移除不必要字段后通过；追加含空格的实际可执行路径仍通过。`go vet ./...`、`go test -race -count=1 ./...` 通过，显式 `TestServiceUnitSystemdSyntax` PASS，非跳过。差异检查通过。[证据与源码摘要](../evidence/enterprise-auto-onboarding-20260925/user-service-unit-r1.json)。

没有写入本机用户单元目录、调用 systemctl 或启用 linger。生成器不等于 installer，不验证签名、不注册设备，升级原子性、注销/重启及端到端自动安装继续待办。ENT-005 保持 doing，下一步须把发行验证与安装动作接通，不能将离线 unit 解析充作原生生命周期验收。

## 第八批：企业发行清单验签与计划绑定

新增 enterprise-release/v1 合同与 Edge 验证库，沿用现有发行公钥，不允许包内密钥或环境变量替换信任根。严格拒绝重复/未知/缺失字段、非整数大小、异常路径、重复制品、无对应 Edge 的架构、非法摘要和篡改签名；清单必须包含对应 Linux 架构的 Edge 和 Connector。安装计划摘要绑定原始清单字节，并核对发行版本、架构、所选 Connector 的摘要/版本/协议。

测试仅生成内存临时密钥，正向路径使用包内私有验证函数；公开生产入口明确拒绝测试签发者。另锁定公钥与已有 skillmanifest 一致。首轮夹具有缺失字段替换未命中和 bootstrap 路径/公钥位置假设错误，修正夹具并将公钥一致性检查指向实际定义文件后通过，未放宽验签。

验证：Edge `go vet ./...`、`go test -race -count=1 ./...` 通过；Python `test_enterprise_install_plan.py` 与 `test_install_plan_issuer.py` 合跑 110 项通过，包含实际 Go 线格式回灌，1 条既有弃用警告；diff 检查通过。[源码摘要与结果](../evidence/enterprise-auto-onboarding-20260925/enterprise-release-verifier-r1.json)。

ENT-004 进入 doing，不算可信安装器交付：尚未校验磁盘制品、解包/安装、注册恢复或服务启动；计划当前时间/组织范围确认仍由执行入口另行调用。未读取实际私钥、签发新包或更改在线服务。下一步接通文件完整性验证和可恢复安装状态机。

## 第九批：Linux 磁盘制品完整性预检

新增 VerifyBundle：先验证原发行身份及计划绑定，再仅检查目标架构的 Edge 和所选 Connector。绝对目录的每一级和制品路径通过 openat/O_NOFOLLOW 逐级打开，拒绝符号链接；检查普通文件、单硬链接、可执行位、禁止组/全局可写和 set-ID，按声明大小加一的上限读取，核对精确大小和 SHA-256。FIFO 用非阻塞打开后拒绝，不挂起检查；错误不回显路径或内容。非 Linux 明确拒绝。

13 个夹具场景覆盖正常文件、同长篡改、短/长文件、缺失、文件/父目录/根目录符号链接、硬链接、目录、FIFO、宽权限和无执行位。测试只使用临时目录内不执行的合成字节及临时签名；公开入口始终拒绝测试发行身份。Edge `go vet ./...` 与 `go test -race -count=1 ./...` 全量通过，git diff --check 通过。[源码与结果](../evidence/enterprise-auto-onboarding-20260925/enterprise-bundle-preflight-r1.json)。

这是时点预检，不是安装/执行句柄：合同明确禁止检查后直接信任原路径重新执行，下一步必须私密暂存、核对暂存内容再激活。尚未实现可恢复安装、注册或服务启用；ENT-004 仍 doing。线上服务、真实设备、私钥及业务权限均未触碰。

## 第十批：复制校验与私密暂存

新增 Linux StageBundle，公开入口先执行发行身份/计划绑定验证，未知发布者不产生目录。已存在的暂存父目录必须为当前用户所有且无组/其他用户权限；逐级无符号链接打开后，以描述符相对方式独占创建随机 0700 子目录及文件，不覆盖已有安装。复制过程限长并计算摘要，随后从暂存文件读回重验；制品改为 0500，清单和 READY 改为 0400，并同步文件和目录。保留签名清单的相对路径，READY 只含清单摘要。

五个场景验证正常暂存、错误内容、宽权限父目录、符号链接父目录和未知签发者；正常场景另验证源文件被修改后暂存仍有效、失败重试不会覆盖先前成功副本。错误内容保留本轮私密残留但不写 READY；调用方只获得固定错误，无可激活返回路径。残留未删除，后续恢复必须重新验签和核验文件/当前计划，不信任 READY 作为授权。

Edge `go vet ./...`、`go test -race -count=1 ./...` 全量通过，包含前批 13 个预检场景回归；diff 检查通过。[证据](../evidence/enterprise-auto-onboarding-20260925/enterprise-private-staging-r1.json)。测试使用临时目录和不执行的合成制品；没有真正掉电模拟、服务重启或正式发布证据。

父目录及祖先的稳定性由调用者保证，不宣称能防同用户/root 改写。此库仍非安装 CLI：组织范围确认、到期检查、注册恢复、服务安装与原子激活继续待实现。ENT-004/005 保持 doing；既有线上实例和业务权限未动。

## 第十一批：计划确认与暂存 CLI 接通

新增 Linux prepare-install 开发命令，固定调用生产验签暂存库。要求明确确认计划原始文件摘要，核对预期组织、环境、控制面、本机架构及开始时的期限；在这些门禁通过前不调用暂存写入。输入文档非阻塞打开，拒绝末级符号链接/目录/FIFO/过大文件；参数错误不回显原始值。成功输出 staged_only，不声称安装、接入或保护生效。

十个入口场景覆盖正确编排、组织/环境/origin/架构替换、过期、未确认、确认后变更文件、暂存失败以及真实生产函数拒绝未知发行身份。编排正向使用测试依赖，真实密钥验签/文件复制沿用前批独立测试，不将此称为正式签名包端到端。另测试文件类型/限额、帮助和参数隐私。Edge go vet ./...、go test -race -count=1 ./... 全量通过；实际 go run . prepare-install --help 成功。

此命令的参数是安装引导内部接口，不替代任务书要求的便捷用户体验。尚需安装引导范围预览、注册恢复、正式包和服务激活；继续 ENT-004/005，未触碰在线设备、发行私钥或业务权限。

## 第十二批：暂存阶段只读恢复

新增 VerifyStagedBundle 与 prepare-install --resume-stage，要求再次验证发行签名和计划绑定、私密当前用户目录、只读且单链接的清单/READY，并逐项重新计算实际制品摘要。READY 缺失或内容伪造、清单变更、元数据符号链接、制品变更、目录权限异常都拒绝；不写入、删除或修复残留。CLI 恢复与新建暂存参数互斥，重复当前计划确认/期限/组织环境校验，仅返回 staged_only。

六个文件恢复负向场景加正常恢复通过，生产入口拒绝测试签发者；四个 CLI 编排场景证明恢复不触发复制、过期/混合参数/坏暂存拒绝。CLI 编排使用测试依赖，文件恢复使用前批实际暂存生成的合成制品，不冒充生产签名验收。Edge go vet ./... 与 go test -race -count=1 ./... 全量通过；git diff --check 通过。[源码证据](../evidence/enterprise-auto-onboarding-20260925/stage-resume-r1.json)。

本批只补文件准备阶段恢复，真实注册响应丢失恢复、服务安装/激活/回滚及用户一键安装体验仍未完成；ENT-004/005 继续 doing。无线上写入、制品执行或新发行签名。

## 第十三批：注册前持久化身份，禁止模糊结果盲重试

复核发现旧 register 使用通用重试器，最多重复发送四次一次性注册请求；身份/签名种子也直到响应后才落盘。现改为发送前独占写入私密待确认身份文件，Linux 同步文件与目录，再仅发送一次请求。失败保留待确认身份，重复 register 不覆盖、不另发网络请求；注册错误不透传服务端响应正文。成功仍保存原 state.json 并复用原心跳/任务链路，待确认文件保留，不作自动删除。

新增模拟 503 的真实 HTTP 测试，服务端收到请求时核对待确认身份已存在且匹配；断言只收到一次、错误不泄漏正文、重试不换身份、无假成功 state.json。另验证八个并发本地注册只有一个获得文件、宽权限目录拒绝。Edge go vet ./...、go test -race -count=1 ./... 全量通过。

重建原生 Edge 后运行隔离 Gateway → Control API → Edge serve → Hermes Connector 验收，[8 项通过](../evidence/enterprise-auto-onboarding-20260925/registration-pending-smoke-r1.json)，包含成功注册、重复注册保护、后台心跳/签名采集/回执、跨环境和吊销拒绝。测试进程退出，临时凭据/数据库清理；未使用线上设备或个人真实配置。

这只是防止身份丢失和盲重试的必要前置，不是完整自动恢复：当前不确定结果会停在需受控处理的状态，后续仍要实现持钥证明的恢复协议及安装引导，不能把手工阻断当成最终便捷体验。ENT-003/004/005 保持 doing。固定错误降低当前诊断粒度，待恢复协议提供不泄密的结构化状态。

## 第十四批：持钥证明约束的注册恢复 API

新增 edge-registration-recovery/v1 合同、严格请求模型及 POST /edge/v1/registration-recovery。验签公钥仅取自既有设备，环境从设备记录确定且要求请求一致；首次恢复限注册后 15 分钟、尚未心跳、未吊销。客户端将来须先持久化随机恢复凭据，此 API 只接收已签名的凭据摘要，不返回秘密。凭据更新、唯一恢复记录和审计同事务，相同请求幂等；另一摘要/签名无效/环境不符/过期/已吊销均拒绝，不改变能力或业务权限。

新增迁移 0018 和每设备唯一恢复表；降级遇到已有记录拒绝删除。8 项新测试覆盖恢复后旧凭据拒绝与新凭据心跳、心跳后的同请求重试、不同凭据拒绝、签名/环境/期限/活跃状态/吊销拒绝、审计失败回滚。首轮测试的心跳夹具漏 version 导致 422，修正夹具后组合 15 项通过；未改变拒绝断言。重跑 API 全量 **1214 passed、1 skipped、1 条既有警告，23.13 秒**；Ruff 与 diff 检查通过。

全新临时 SQLite 数据库 Alembic upgrade head 从 0001 回放至 0018 成功；未在生产库迁移，亦未验证 PostgreSQL 并发竞态，不将 SQLite 证据外推为生产验收。[源码与结果](../evidence/enterprise-auto-onboarding-20260925/registration-recovery-api-r1.json)。

下一步接入原生 Edge：先持久化恢复 secret，再签名请求，核对返回环境/控制面并原子保存身份。当前 CLI 仍保守阻断，服务端代码未上线；ENT-003/004/005 保持 doing。端到端原生恢复、长期管理凭据轮换和过期后的管理恢复都未完成。

## 第十五批：原生 Edge 注册恢复与真实 API 连通

接入 Linux recover-registration：校验明确控制面/环境、私密待确认身份与原签名种子，独占持久化 256-bit 随机恢复凭据，然后发送原私钥签名请求。失败保留凭据，重试不重生；返回 schema/environment/public-key 长度校验后，以原 identity/seed 保存恢复 secret。旧 register 与恢复共享 Linux 排他锁，避免同时完成两条注册路径；已有正式 state.json 拒绝覆盖。局部文件读取有大小、所有者、权限、普通文件、单链接及末级无符号链接限制，固定错误不回显秘密。

原生 HTTP 测试模拟首个恢复响应 503，证明发送前凭据已落盘、第二次仍使用相同摘要、签名与身份不变、成功后禁止覆盖；另验证 origin 不符不创建凭据。Edge go vet ./...、go test -race -count=1 ./... 全量通过；Linux amd64、darwin arm64、windows amd64 交叉编译成功（非 Linux 恢复命令明确拒绝，并非跨平台运行验收）。

扩展隔离 Gateway/API/Edge/Hermes 验收的 --recover-registration：仅移动本轮临时最终 state.json，保留 pending，再执行原生恢复命令。实际 Go 签名被 Python API 接受，旧凭据心跳拒绝，恢复后 serve 完成心跳/扫描/签名上传/回执及吊销拒绝，[9 项通过](../evidence/enterprise-auto-onboarding-20260925/native-registration-recovery-r1.json)。这是“最终本地文件不可用”故障注入，不是代理丢包；响应再次丢失由独立 Go HTTP 测试覆盖。全部本轮进程退出，临时凭据/数据库清理，Ruff/diff 检查通过。

原生源码恢复路径已连通，但尚无最终安装引导、线上迁移/部署、生产 IAM/PostgreSQL 并发或长期凭据管理验收；ENT-003/004/005 保持 doing。恢复文件为本机秘密，README 已提示禁止上传。下一步继续与安装计划/用户范围确认及服务安装状态机整合。

## 第十六批：本机确认范围约束签名任务

新增 edge-discovery-consent/v1 本地合同，State 可保存已确认计划和紧凑 JSON 摘要；Linux confirm-discovery-plan 要求明确原文件摘要、当前计划、预期租户、已注册环境/origin/本机架构及私密状态，在排他锁内持久化限制，不进行网络/扫描/业务授权。范围是持久同意，安装计划的短期到期仅用于首次确认，不在后台擅自终止已确认采集。

Runner 在验签和期限验证后、台账复用及启动 Connector 前核对同意：计划/摘要完整，环境和 origin 一致，扫描类型、采集器、明确非空 roots/include 且逐项属于确认列表。不同路径表达不推断等价；非空 exclude 暂拒绝，直到采集器语义验证。旧状态无两个字段保持 legacy 兼容，任一字段单独缺失失败关闭。13 个范围场景、真实签名超范围任务拒绝、确认落盘/格式化后摘要稳定与到期拒绝测试通过。

检查实际采集器发现 Hermes 额外读取 config.yaml 提取属性和计算游标，未服从 include，且该旁路读取缺少 profile 内符号链接检查。本批修正：仅显式包含 config 时提取其属性，拒绝配置链接逃逸；游标只哈希显式选中、未逃逸且非 .env 的文件内容。两条负向测试证明 SOUL-only 时配置变化不影响事实/游标、外部配置链接不影响结果；选中 SOUL 内容变更会改变游标。原有 secret_ref 文件名/大小元数据防御保留，绝不读取 .env 正文。

Edge 与 Hermes 各自 go vet ./...、go test -race -count=1 ./... 全量通过，diff 检查通过。[证据](../evidence/enterprise-auto-onboarding-20260925/discovery-consent-r1.json)。本批未跑新的全链路范围确认验收，其他 Connector I/O 一致性及非文件 scope 合同仍待落实，不将任务信封校验称为全部采集器安全边界完成。安装引导、自动调度及服务生命周期继续开发，线上状态未改变。

## 第十七批：范围确认/拒绝审计的原生端到端验收

扩展隔离验收 --consent：本轮临时受控 catalog 生成 API 计划，原生 confirm-discovery-plan 确认后启动 serve，实际下发允许和越界两种签名任务。允许任务完成 Hermes 采集/签名上传/回执，越界任务在企业接入进度变为 failed，并通过只读审计 API 核对 discovery_scope_denied、candidate_count=0、evidence_count=0。与注册恢复、跨环境、排他锁和吊销验证合并运行，[11 项通过](../evidence/enterprise-auto-onboarding-20260925/discovery-consent-native-r1.json)。

此 catalog 是显式合成测试配置，清单摘要为占位值；该场景验证计划产生/确认/执行范围约束，不执行发布验签或暂存，不冒充已存在正式企业包。真实二进制摘要、API/Gateway 源码及脚本身份在证据中记录。全程仅临时用户、回环服务、合成配置和数据库，所有夹具进程已退出。

进一步复核 OpenClaw，发现原 collect 固定读取 openclaw.json，忽略 Include 排除该文件的情况。现 validate_scope 和 collect 均拒绝未选中配置、非空 exclude；保留旧空 Include 的明确默认行为，且 consent-bound Edge 仍不接受空 Include。新增测试验证两条拒绝及正常显式选择，OpenClaw go vet ./... 与 go test -race -count=1 ./... 通过。脚本 Ruff 和 diff 检查通过。[源码记录](../evidence/enterprise-auto-onboarding-20260925/discovery-consent-native-source-r1.json)。

尚未完成其余 Connector 范围语义、实际能力声明/调度、用户安装引导和 systemd 完整生命周期；不提前关闭 ENT 任务，也未上线新 API 或制品。

## 第十八批：验签暂存与用户服务安装入口

新增 Linux install-user-service --release FILE --stage DIR [--start]。在现有排他锁内读取私密已注册状态，验证已确认计划摘要、当前安装期限、环境/origin/架构和 user 模式，独立调用固定公钥与暂存制品验证，再生成服务配置。用户配置目录逐级拒绝符号链接及不可信/可写祖先，最终目录要求当前用户所有且无组/全局写入；单元以 0600 文件同步并原子无覆盖发布。相同内容允许重试，不同内容/危险链接拒绝，不改既有配置。

默认只安装单元；显式 --start 才释放 Edge 锁并执行固定 /usr/bin/systemctl --user daemon-reload、enable --now、is-active --quiet，每次最多 20 秒，不经 shell、不 sudo、不启用 linger、不回显原始输出。任一步失败即停止并保留已写配置和身份；可能留下已启用但未运行单元，不宣称自动回滚。已有运行进程持锁时拒绝安装，完整升级/停止/回滚流程仍待实现。

测试验证独占安装/相同重试/拒绝覆盖/临时文件清理、五类危险目录/文件、模拟管理器正常顺序及三处失败停止、未确认身份在写配置前拒绝。补充祖先权限检查后测试夹具权限不满足要求，显式将本轮临时目录设为 0700 后 Edge go vet ./...、go test -race -count=1 ./... 全量通过；未放宽生产检查。diff 检查通过。[源码与结果](../evidence/enterprise-auto-onboarding-20260925/user-service-install-r1.json)。

未调用本机真实 systemctl、未安装到真实用户配置目录；测试正向覆盖安装/服务管理编排组件，尚无正式发行签名包贯穿完整命令的正向验收，也未证明重启/登出自启或心跳。合同明确 active 不等于纳管或运行时保护。ENT-004/005 保持 doing，继续最终安装引导及真实生命周期验证。

## 第十九批：注册前服务端核对预期环境

新增可选 expected_environment_id 合同及 register --environment。服务端定位注册码所属环境后，在任何消费/设备创建之前核对预期环境；错误环境统一 enrollment_invalid。Edge 发送前保存预期环境，并在收到响应时再次比较；恢复命令也必须符合 pending 中的预期环境。没有新租户自报来源，也不授予业务权限。旧客户端省略字段仍兼容，旧服务端拒绝新字段时不自动降级重试。

后端新增“错误环境不消耗代码/不创建设备/不写注册审计，正确环境复用同码成功”和空字段拒绝/旧客户端兼容测试；原生测试覆盖正确/错误/缺失响应环境和恢复不改变保存的预期环境。组合 17 项通过，API 全量 **1216 passed、1 skipped、1 条既有警告，23.50 秒**；Edge go vet ./... 和 go test -race -count=1 ./... 全量通过，Ruff/diff 检查通过。

更新隔离脚本，在 --consent 场景从首次注册起发送预期环境，并贯穿原生恢复、计划确认、范围内扫描、范围外拒绝审计、吊销检查，[11 项通过](../evidence/enterprise-auto-onboarding-20260925/environment-bound-registration-r1.json)。所有环境/码/设备和扫描文件均为临时合成夹具，未改线上环境。[源码结果](../evidence/enterprise-auto-onboarding-20260925/environment-bound-registration-source-r1.json)。

任务书状态表同步当前事实，ENT-003/004/005 仍 doing；最终用户安装编排、正式包、实际能力合同和真实服务生命周期仍待完成。

## 第二十批：统一安装编排开发入口

新增 Linux setup-enterprise，以单入口串联现有门禁：读取并核对显式确认计划及 user 模式/当前期限/上下文，检查本机身份是否新建/待恢复/已注册，固定调用发行验签和暂存（或暂存复核），随后仅选择环境绑定注册、原身份恢复、已有身份复用之一，再保存范围并安装用户服务。默认只配置，--start 才请求启动，首次注册要求 stdin 取码，不在命令行传秘密。

阶段进度为 NDJSON，仅含 phase/status/stage_path。暂存成功即输出恢复位置，中途失败停止，保留已有身份与暂存，不回滚、不删除、不切换新身份；配置完成和服务 active 的描述都不冒充心跳、盘点或保护。旧的多个开发命令仍保留供诊断，统一入口尚未替代最终图形化安装体验。

六种身份/启动分支、五个阶段失败停止、进度输出失败停止、本机身份分类不覆盖测试通过。增加真实 cmdSetupEnterprise 未签名清单负向：即使选择 --enrollment-code-stdin --start，仍在暂存验签阶段拒绝，未创建设备目录。另修复注册响应缺少 secret/edge ID/environment 或控制面公钥长度不合法时不应写正式状态的问题，保留 pending 供恢复，新增测试覆盖。

Edge go vet ./...、go test -race -count=1 ./... 全量通过，实际 go run . setup-enterprise --help 成功，diff 检查通过。[源码与结果](../evidence/enterprise-auto-onboarding-20260925/enterprise-setup-orchestrator-r1.json)。正向流程使用注入动作测试顺序，各底层已完成各自验证；本批没有正式签名包贯穿全命令和真实 systemd 的正向验收，不将模拟编排称为已发布一键安装。

最终范围预览、下载/打包发行、实际能力和自动首扫调度、服务升级/卸载与真实生命周期仍待完成。ENT-003/004/005 保持 doing；未注册真实设备、读取发行私钥或更改线上服务。

## 第二十一批：安装取消不再推进后续阶段

统一安装编排增加 context 检查：开始前取消不执行任何动作，暂存/注册或恢复/范围确认完成后的取消均停止下一阶段，已完成进度和暂存位置保留。11 个身份分支/取消时点组合验证后续动作不调用，尤其取消后不启动服务。正在进行的暂存有界文件工作可能先结束再观察取消，不宣称瞬时撤销或回滚。

注册码 stdin 等待改为可取消读取，在落盘 pending 前再次检查取消。测试用 pipe 确认已进入真实阻塞读取后再取消，调用在一秒内返回，且不返回注册码；另保留正常读取验证。辅助 goroutine 不关闭调用者流，CLI 退出或输入关闭后结束；明确仅用于会退出的 CLI，不作为常驻输入循环。

Edge go vet ./...、go test -race -count=1 ./... 全量通过，diff 检查通过。新证据为单元/竞态验证，没有新的正式签名安装或真实 systemd 验收；总体 ENT 任务仍在进行，线上未改动。

## 第二十二批：安装范围只读预览

统一安装命令新增 --review-only，复核当前计划/预期租户环境/origin/宿主架构后，输出 enterprise-install-review/v1：完整计划（包含选定采集器、目录和文件）、原文件确认摘要、是否启动服务、需显式确认、未验签制品、不授予业务权限及中文边界提示。该路径在读取设备身份/暂存/注册/服务动作之前返回，不要求发行包或注册码，也不自动批准后续安装。

四类测试覆盖正常预览、请求启动但仍只预览、上下文不符、计划过期；预先放置无法作为身份解析的合成私密文件，证明预览不依赖/修改/输出其内容，临时目录没有新增状态或制品。Edge go vet ./...、go test -race -count=1 ./... 全量通过；实际 setup-enterprise --help 展示预览用法；diff 检查通过。

这是安装引导可消费的只读确认模型和 CLI，不是已完成企业前端向导。图形化确认、可信包下载、正式签名全安装验收及其他 ENT 任务继续推进，线上环境未改动。

## 第二十三批：前端安装选项数据源

新增 GET /environments/{id}/install-options 和 enterprise-install-options/v1 合同。先定位租户环境，再校验 env:manage/edge:manage；返回受控架构/发行版本/采集器范围及安装器当前支持的 user 模式，明确 release_signature_verified=false。只读，不产生计划、注册码、设备或审计写入；响应 no-store。配置缺失/非法/origin 不安全/仅 system 模式统一 503，不泄露内部路径或配置正文。

受控目录加载增加复用安装计划的 origin 语义校验，避免选项页面展示签发时才会拒绝的来源。6 项新测试覆盖成功只读、跨租户/权限拒绝及四种不可用配置，组合 116 项通过；首轮 Ruff 提示导入 fixture 与参数重名，改为模块引用复用后通过。API 全量 **1222 passed、1 skipped、1 条既有警告，22.97 秒**；Ruff/diff 检查通过。[源码结果](../evidence/enterprise-auto-onboarding-20260925/install-options-r1.json)。

页面尚未接通选项/计划生成/范围确认；该数据源不证明制品已正式发布，也不消除客户端验签门禁。继续企业安装引导开发，未改线上配置或服务。

## 第二十四批：企业环境页安装计划入口

环境页新增 Linux 安装计划卡片：按后台实际发行配置选择 ARM64/AMD64，逐个展示采集器版本、目录和文件；默认不勾选，用户确认后才 POST 生成计划，提供限时 JSON 下载。现有注册、心跳、发现进度与手动接入保留；配置不可用明确提示，不伪造安装成功。页面不会登记设备、上传发现或授予业务权限。

API 客户端核验环境、来源、架构、发行摘要、采集器/范围及有效期，拒绝范围扩大和过期计划；请求体不允许前端覆盖租户/来源/采集范围。按 React 技能将写入放在点击处理器而非 effect，架构选择派生当前发行，环境切换通过 key 重置并忽略已卸载组件的异步结果；按钮即时互斥防止重复提交。

前端定向 25 项通过，全量 58 个测试文件、332 项通过； TypeScript + Vite 生产构建通过，diff 检查通过。此批测试是 API 合同单测和构建，尚无浏览器交互/E2E 证据，不能声称环境切换/下载交互已由真实浏览器验收。源码证据见 install-plan-ui-r1.json。未部署、未正式签发包；安装器调用、可信下载和简化主路径继续开发，ENT-004 保持 doing，整体目标保持 active。

## 第二十五批：企业安装实测采集能力

企业 setup 在固定发行验签暂存之后、注册之前，仅对选定的暂存二进制执行有界 describe/validate_scope，不扫描资产。核对计划版本、输出上限、对象/类别标签、范围确认；失败或取消在身份操作之前停止，保留暂存位置。注册不再走该主路径原有的四项静态声明，而携带实测 ID、版本及类别；不上传包含本机路径的权限说明。新增版本化合同说明这是申报能力，不是策略生效证明。

测试覆盖选中制品路径、5 秒 deadline、单采集器精确投影、9 类失败拒绝、提前取消、真实子进程协议握手以及本地 HTTP 注册原样传递实测能力。Edge go vet ./...、go test -race -count=1 ./... 和 diff 检查通过。子进程为合成协议 fixture，注册服务器为 httptest，未作正式签名包全流程验收、真实设备注册或部署。

ENT-007 开始 doing。历史独立 register 静态声明、心跳更新及旧 API/UI 四采集器展示仍须迁移；本批不宣称持续能力更新或设备级任务调度完成。没有更改防攻击判定、授权或审计逻辑。

## 第二十六批：能力变化的心跳合同与事务接收

新增 edge-capability-heartbeat/v1 合同和严格 InstalledCapabilities 输入模型。心跳可选携带实测能力，ID/版本集合必须一致，类别有界且不可重复，拒绝来源/环境等额外字段；空集合清除可用能力，省略/null 保持旧客户端兼容。服务端按验证设备的真实绑定环境确定租户，只更新该设备；变化时同事务写 edge.capabilities.update 审计，重复心跳不重复写事件。不删除历史资产或改变权限。

Go 客户端增加 HeartbeatWithCapabilities，测试区分省略与明确空集合。当前 serve 仍使用旧入口，周期实测、失败原因展示和 UI 全采集器消费尚未接通，不把接收接口上线能力冒充持续发现。

新增 13 个 API 测试覆盖替换/清除/旧客户端、10 类非法输入、跨设备凭据与吊销拒绝、审计失败回滚。首轮失败暴露设备无 tenant_id 字段及测试共享库身份重名，改为环境派生租户和独立测试身份后全部通过。API 全量 pytest 通过（1 个既有 skip、1 条既有依赖警告），Ruff 通过；Edge go vet ./... 与 go test -race -count=1 ./... 全量通过，diff 检查通过。未部署或执行真实设备上传。

## 第二十七批：serve 心跳接入周期能力实测

已确认安装计划的 Linux serve 每次心跳前复核计划摘要、环境、origin、本机架构与可信暂存路径，使用固定发行公钥重新验签并核对制品，再实测 describe/validate_scope。不重新应用短时安装期限；持久采集同意仍有效。未确认的旧设备保持旧心跳。核验失败撤回全部可用声明（空集合），固定日志说明 unverified；不删除历史资产、不授予权限。取消期间不发送空快照，发送失败仍走既有退避。

6 类心跳生命周期测试、8 类信任门禁测试通过，包括真实生产验签函数拒绝未签名发行清单且不执行采集器。正常核验分支使用注入验签/探测函数，不是正式签名包端到端证据。Edge go vet ./...、go test -race -count=1 ./... 全量通过，diff 检查通过；本轮无生产启动或数据上报。实测类别并集增加 64 项上限，与服务端合同一致。

目前是整批保守失败，暂不返回每个采集器的失败原因；UI 状态、独立 register/heartbeat 迁移、任务按能力过滤/设备绑定、自动首扫和正式包全链路验收仍待完成。时点验签不声称抵御同用户恶意进程并发替换制品的完整隔离。ENT-007 继续 doing。

## 第二十八批：实测能力约束任务领取

带 inventory_schema 的设备仅在严格能力合同通过且心跳在有效窗口内时领取对应采集器的扫描；空/无效记录、过期/未来心跳不回退旧模式。SQL 在 LIMIT 10 前过滤，并在条件 UPDATE 时重用过滤和环境条件。不兼容任务不占领取名额。已 uploaded 且本设备持有的任务保留回执恢复路径，其他无能力设备不能接管；非扫描任务保持原流程。历史未带 inventory_schema 的设备仍兼容，未声称全设备迁移完成。

新增 8 项测试，和既有租约用例组合 15 项通过。全量首跑暴露共享测试库的任务污染（跨用例遗留任务与配额），改为专用环境并将本测试创建的任务终结为 expired 后，API 全量 **1243 passed、1 skipped、1 条既有警告，24.65 秒**；Ruff 与 diff 检查通过。没有放宽真实配额、删除用户数据或修改上线服务。

此批验证为 SQLite 测试库，未完成 PostgreSQL 并发领取验收；能力为请求时快照，本地范围门禁仍必需。指定设备绑定、首扫自动签发、旧设备迁移及完整可视化继续开发，ENT-007 保持 doing。

## 第二十九批：指定设备扫描绑定

普通扫描创建接口增加可选 target_device_identity：核对本租户环境内设备并拒绝吊销设备，目标进入现有签名 payload。无目标仍为环境级任务。领取候选与条件 UPDATE 都按目标过滤，租约过期也不能由其他设备接管；上传批次与回执在幂等分支之前检查目标，避免直接调用绕过。新增 Edge 在签名/期限后、范围检查及本地台账复用前拒绝目标不符或非法目标。

API 集成测试覆盖跨租户/不存在目标、目标领取、其他设备不可领取/不可越过过期租约、批次与回执绕过拒绝、终态重放拒绝和吊销目标创建拒绝。Go 测试覆盖无目标兼容、匹配/不匹配/非法目标以及已签名错设备任务在有无本机确认计划时均拒绝；修改目标会破坏签名。API 全量 **1244 passed、1 skipped、1 条既有警告，25.14 秒**，Edge go vet ./... 与 go test -race -count=1 ./... 通过，Ruff 和 diff 检查通过。

此批未新增表或迁移，未改线上服务；测试使用 SQLite/合成签名，不代表正式包全链路部署。UI 设备选择、自动首扫、旧设备迁移与 PostgreSQL 并发验收仍未完成，ENT-007 继续 doing。

## 第三十批：前端明确选择目标设备

环境接入页面新增目标设备选择，只列出当前状态为 online 且声明支持所选框架的设备，不默认选第一台、不提供含糊的随机分配。切换框架清空目标；提交期间锁定框架/目标选择，提交前重新读取状态确认仍为同一可用设备，失败不自动改派。成功提示区分后台服务自动领取与手动模式领取，保留现有注册/心跳流程。

onboarding.scan 必须携带目标身份，检查任务响应，OpenClaw 范围明确 include=openclaw.json（此前无 include 会被已确认安装计划的范围门禁拒绝）。按 React 技能使用渲染派生可选设备与有效选择，网络写入仅在点击处理器执行，不用 effect 自动提交。既有互斥/卸载保护继续保留。

新增 4 项 API/选择逻辑测试，前端全量 **58 个文件、336 项通过**； TypeScript + Vite 生产构建与 diff 检查通过。没有真实浏览器交互/E2E 验收，不将单测和构建冒充此类证据。未部署。待自动首扫、精简安装主路径、状态详情及全链路浏览器测试继续推进。

## 第三十一批：原计划绑定的首次扫描签发

新增 /edge/v1/initial-scan：在线验证设备凭据，核对真实环境/租户，计划规范摘要必须匹配同环境 install.plan.create 允许审计；首次要求有效期内、最近心跳实测能力及版本覆盖选中采集器。按原 scope 创建签名且绑定本设备的扫描，保留 pending 配额守卫。范围不能由设备任意扩大，签发审计缺失失败关闭。

新增 edge_initial_scan 与迁移 0019，以设备主键持久去重。同计划重试返回原任务编号，不重复创建；不同计划拒绝，后续重扫走管理入口。任务、首扫记录、审计和 outbox 同事务，唯一冲突回滚并要求重试原计划。已完成首次签发后重试不再要求短安装期限，设备凭据和环境绑定仍校验。

8 项新增测试覆盖原范围/目标/重试、篡改范围、其他环境/租户、能力缺失、签发记录缺失、过期拒绝和审计失败回滚。API 全量 **1252 passed、1 skipped、1 条既有警告，26.20 秒**；Ruff/diff 通过，空临时 SQLite 迁移从基线回放至 0019 成功。未在生产应用迁移。并发首扫/配额的 PostgreSQL 验收、安装器自动调用及实际发现上报仍待完成；ENT-006 开始 doing，不能声称自动首扫已端到端交付。

## 第三十二批：企业后台服务自动申请首扫

Linux serve 单心跳循环接入初次扫描调用：已确认计划经实际能力复核、非空能力心跳成功后才请求 /edge/v1/initial-scan；成功后本次运行不再申请，重启交由服务端持久去重。失败仍用同一确认计划，走既有循环退避；无确认计划旧设备、能力失败、心跳失败和取消都不申请。setup 默认仅配置，只有用户启动服务（含 --start）才走此流程。

Go 客户端复核本机计划摘要及环境/origin，原样发送已确认计划，并校验返回 schema、replay、任务数/ID格式/唯一性。6 类序列测试与 7 类 HTTP 合同测试通过；首轮测试发现 do 参数为额外重试次数，修正为 0，统一由后台循环重试。Edge go vet ./...、go test -race -count=1 ./... 和 diff 检查通过。

测试使用注入能力探测与 httptest 服务，不是原生正式签名发行全流程，不宣称线上自动扫描已生效。未启动真实设备、应用生产迁移或上传主机数据。主机探测、旧路径迁移、完整原生链路与浏览器验收仍待推进。

## 第三十三批：首扫隔离原生链路验收

扩展原有 Gateway/Control API/native Edge/Hermes 验收脚本，新增 --initial-scan（要求 --consent）：使用合成 HOME 内配置、真实二进制 describe、设备凭据心跳上报对应版本能力，通过真实 Gateway 请求首次扫描两次，核对同一任务及原范围/目标，再由原生 tasks 执行并签名上报。首扫 HTTP 请求由验收驱动发出，不伪称由已验签的自动安装服务发出。

组合恢复/范围拒绝检查共 **11 项通过**；证据 [initial-scan-native-r1.json](../evidence/enterprise-auto-onboarding-20260925/initial-scan-native-r1.json) 包含制品与源码摘要。匿名及未知路由拒绝、跨租户环境拒绝、注册身份保留与注册码重放拒绝、原身份恢复/旧凭据失效、原生计划确认与心跳、跨环境任务拒绝、首扫去重与指定目标、真实签名上报、超范围拒绝审计以及吊销后在线拒绝均通过。全部临时进程已停止，未读取真实用户框架配置。

脚本明确拒绝 --serve 与合成 --consent 混用：此 fixture 没有正式签名发行清单，新的周期验签应撤回能力，不能再用旧假设期待服务自动扫描。统一服务旧设备兼容路径另行回归，正式包/真实 systemd 自动安装首扫仍需独立证据。未弱化发行签名门禁；源代码验收不等于生产部署。Ruff 与 diff 检查通过。

独立 --serve 回归完成，**8 项通过**，包括真实后台心跳/任务执行、服务运行时手动 tasks 排他拒绝、签名上传与吊销拒绝；[native-service-regression-r3.json](../evidence/enterprise-auto-onboarding-20260925/native-service-regression-r3.json) 确认所有临时进程已停止。此路径为未保存确认计划的 legacy 兼容场景，不作为正式企业安装验签成功证据。

## 第三十四批：固定范围的主机只读识别

新增 Linux inspect-host，输出 enterprise-host-inspection/v1：仅从 os-release、DMI 产品名、设备树型号和 uname 提取有界元数据，区分二进制架构与内核架构；不读 hostname/机器 ID/序列号/用户配置，不联网，不执行 shell 格式配置，不授予权限。缺失/权限拒绝/异常各自标识，用户填写的环境名不影响探测结果。固件产品标签仅作系统报告，不成为硬件认证或有效隔离证明。

测试覆盖允许字段投影、来源边界、缺失/权限/异常、命令替换文本、重复字段、控制字符、超大文件、非普通文件、FIFO 非阻塞以及有参数时先拒绝读取。Edge go vet ./...、go test -race -count=1 ./... 与 diff 检查通过。

实际 `go run . inspect-host` 本机只读执行成功：Linux，二进制 arm64、uname aarch64，Ubuntu 24.04，DMI 报告 NVIDIA_DGX_Spark，设备树型号未观测；hardware_attested=false、uploaded=false。未读取用户配置或自动登记到企业端。安装预览/前端消费、框架发现和全流程交付仍待继续。

## 第三十五批：发现资产和证据的设备边界

检查框架/角色/Skill 的关系基础时发现现有来源键仅含 tenant/source_type/locator，会合并不同设备同名 profile；证据同环境同外部 ID/摘要也会丢失另一设备的观察。新合同 enterprise-discovery-identity/v1 与迁移 0020 将资产键增加服务端已认证 Edge ID（discovery_scope），证据键增加 collector_id；写入、去重、确认时默认实例环境推导及资产证据读取均使用对应设备边界。客户端 attributes 不能覆盖该作用域。

历史资产迁移为 legacy，不猜测过去已合并的设备归属，不自动把新发现覆盖到历史资产；已有证据及签名保留。降级明确拒绝自动合并设备来源。新增双设备同名同 locator/同 evidence ID/同内容测试：不同设备保留两资产和两观察，每设备重复采集仍去重，读取证据不串设备、跨租户拒绝。

空临时 SQLite 从基线迁移到 0020 成功；尚无有数据升级与 PostgreSQL 验收。全量首跑发现旧摘要漂移测试依赖跨设备合并，改为同设备复用凭据以保留原漂移验证；修正测试构造的 collector_id 后，相关 12 项定向回归通过。未更改生产数据库或已有数据，不宣称关系图完整交付；ENT-008 开始 doing。

最终 API 全量 **1253 passed、1 skipped、1 条既有警告，25.99 秒**；Ruff/diff 检查通过。历史资产关系的人工迁移与其他审计/分析消费者的设备关联审阅继续推进。

## 第三十六批：有数据迁移与威胁证据来源门禁

新增真实 Alembic 子进程测试：临时 SQLite 先升至 0019，填入历史 managed 资产、关联实例、不可变证据/签名，再升至 0020。逐项比对所有旧字段，确认 legacy 作用域、实例外键和 foreign_key_check 正常；新设备作用域并存、相同设备来源重复拒绝、不同采集者观察并存均验证。降级命令明确失败且版本/所有数据计数不变。仅操作测试临时库，未迁移生产；PostgreSQL 验收仍待完成。

审阅威胁扫描消费者发现内容摘要原本可匹配同租户其他设备同 evidence_id。抽出共享设备证据谓词，资产展示/确认与威胁扫描复用；非 legacy 资产先验证提交的 evidence_ids 确实关联本资产及本设备，替代 artifact 内容摘要也限定本设备观察。新增两个设备同外部证据 ID、不同内容的测试：借用另一设备内容拒绝、未关联 ID 拒绝且不改资产/不创建 Finding，正确内容允许扫描。未修改威胁规则、静态分析或自动隔离阈值，不扩大权限。

有数据迁移与新威胁门禁定向测试均通过，Ruff/diff 检查通过。legacy 历史合并归属仍不推测修复，完整关系图未完成，ENT-008 保持 doing。

最终 API 全量 **1255 passed、1 skipped、1 条既有警告，28.68 秒**。新增证据见 populated-migration-and-threat-binding-r1.json。

## 第三十七批：可查询的资产发现来源

新增只读 discovery-origin 合同与接口，先定位租户资产再检查 agent:read 和 env:read。环境/设备来自服务端 discovery_scope，经环境租户再次核对；legacy 来源不猜测，缺失或跨租户异常绑定返回 source_unavailable。仅返回关联本资产、本设备和本环境的观察 ID、外部证据 ID、摘要和时间，最多 200 项并明确截断，不返回原文、位置、签名或凭据。

设备吊销后仍可查询历史来源并标明 revoked，不暗示当前在线或保护生效。framework/role 字段明确只是已有标签，不包装成已证明的实例/Skill 关系。新增历史来源、伪造 attributes、跨租户绑定、权限拒绝、只读状态、吊销与 201 项截断测试；原双设备真实签名入库测试增加各自来源查询断言。

API 全量 **1259 passed、1 skipped、1 条既有警告，28.17 秒**；uv run ruff check app 与 git diff --check 通过。未接入前端、未部署、未修改生产库；完整关系模型和可视化仍待继续，ENT-008 保持 doing。证据见 discovery-origin-r1.json。

## 第三十八批：Hermes 同机多根同名角色的来源分离

新增 hermes-profile-origin.v2 合同：候选/位置按规范化绝对 profile 路径摘要生成稳定来源键；证据按路径及文件名生成有界 ID。显示名称仍保留，绝对路径不直接输出，摘要不声称匿名化。目录移动产生新来源，内容修改保留来源并更新摘要；旧 basename 资产不覆盖、不删除、不自动合并。

修正多 root 共用第一个 root 边界导致后续合法目录漏扫的问题：按各自非通配路径前缀验证匹配目录，解析失败或逃逸拒绝，然后规范化、去重和排序。新增双根同名 profile、候选/证据/declared 权限分别绑定、范围重叠和顺序变化稳定、内容变化可观察、第二根符号链接逃逸拒绝测试。未新增执行扫描文件的能力或 effective 权限，既有 .env 正文拒读、范围与恶意内容测试继续运行。

Hermes `go vet ./...` 与 `go test -race -count=1 ./...` 通过，diff 检查通过。重新构建原生 Hermes 后运行隔离 Gateway/API/Edge 链路，恢复注册、确认范围、首次扫描去重、原生签名上传等 **11 项通过**，所有临时进程已停止，见 profile-origin-native-r1.json。此集成使用合成配置与手动原生任务执行，不是正式签名安装包或生产部署。ENT-009 开始 doing；Skill 深度采集、完整关系模型及前端仍未完成。

## 第三十九批：企业资产详情可视化来源

企业资产详情接入 discovery-origin，只读呈现环境、采集设备、凭据吊销与关联观察；折叠展示观察 ID、证据 ID、摘要和时间，明确截断。历史未确认来源不猜测设备，读取失败和权限不足显示独立提示及重试，不作为空数据；发现来源不包装成运行时绑定或保护生效。

API 客户端校验 schema、资产 ID、来源状态一致性、最多 200 条、观察 ID 唯一、摘要与时间，拒绝错资产和异常响应。按 React 技能的 keyed reset 建议拆分详情及请求组件，切换资产卸载旧请求状态；请求完成回调检查存活状态。测试配置加入 TSX 收集与现有 React 转换插件，避免新增组件测试被静默漏跑。

前端全量 **60 个文件、350 项通过**；TypeScript/Vite 生产构建通过。浏览器模拟 API 验证 **5 项通过**，覆盖吊销来源、403 后重试、错误资产拒绝、390px 历史来源及无 JS 异常；临时 HTTP 服务停止。首轮截图捕获入场动画，第二轮禁用截图动画后人工检查桌面及移动端可读，无 HTML 注入；证据 discovery-origin-browser-r2/result.json 与截图。此为浏览器 UI fixture，不是生产或真实后端端到端验收。Ruff/diff 通过。未部署或修改防御规则，ENT-018 仅开始 doing，完整导航/关系树/批量操作待继续。

## 第四十批：技能清单静态解析基础

新增 enterprise-skill-manifest/v1 合同与 protocol 共用纯解析器，不将技能塞入 AgentCandidate 或伪造角色归属。输入上限 256 KiB，仅完整输入计算 SKILL.md 摘要，不冒充完整技能包摘要；输出 name、declared_tools 和明确解析状态，区分 allowed-tools 缺失与显式空列表。支持简单标量/数组/块列表；重复目标字段、复杂或不支持的语法、无效 UTF-8、未闭合头部等不返回部分声明。已知凭据形状复用既有脱敏规则并拒绝输出。

解析器没有文件/进程/网络操作；正文、description、未知元数据不输出、不用于权限推断，解析成功不是安全裁决或授权。采集器安全读取、独立技能记录、关系证据上传和前端消费仍未连接，本批仅完成共用解析基础，不能声称技能盘点已交付。

Edge `go vet ./...`、`go test -race -count=1 ./...` 通过。最终代码模糊测试 `go test ./protocol -run '^$' -fuzz FuzzSkillManifest -fuzztime=5s -parallel=2` 通过，69,595 次执行，保留有界声明/摘要一致性/异常时清空部分结果等不变量；此前无凭据门禁版本的 10 秒模糊检查不冒充最终代码结果。diff 检查通过，未部署、未修改既有反攻击规则。下一步仍需完成技能独立身份及采集/上报合同，而非把本解析器孤立视为完成 ENT-009。

## 第四十一批：独立技能身份及清单观察存储

新增 enterprise-skill-identity/v1、SkillInstallation/SkillManifestObservation 模型及迁移 0021。技能位置以 tenant/Edge/位置摘要唯一，不用名称或内容猜测归属；清单观察单独记录摘要、解析版本/状态、工具声明、时间和签名批次摘要。安装位置与观察间使用租户联合外键；同安装同批去重，不同批保留观察。没有引入 effective 权限、角色绑定，旧 Evidence 必须由本批候选引用的门禁未变。

真实 Alembic 子进程在隔离 SQLite 上从基线升级至 0021、空库退回 0020 再升级；验证同位置跨设备独立、同设备不同位置独立、重复位置拒绝、跨租户观察拒绝、重复批拒绝、too_large 不可伪装完整观察、不同批相同内容可保留。有数据降级拒绝且版本/三安装/两观察及签名均保留；不产生 AgentAsset。只验证 SQLite，PostgreSQL 与生产迁移未运行。

控制面全量 **1260 passed、1 skipped、1 条既有警告，30.92 秒**；Ruff/diff 通过。当前仅存储基础，没有公开技能写入或查询端点；签名上传、任务/范围/设备租户验证、事务审计、采集与前端仍待实现。不能把数据库表存在当成自动发现完成，ENT-008/009 保持 doing。

## 第四十二批：技能独立签名上传与可复核记录

新增 enterprise-skill-upload/v1 与 /edge/v1/skill-batches，只接受已签名 skill_scan 任务，拒绝旧 scan。在线校验设备凭据和吊销、任务真实环境、控制面任务签名、指定设备、明确技能类型、SKILL.md 范围摘要及有效租约。声明 schema 拒绝额外权限字段、部分解析结果、重复位置/工具、已知凭据形状与过期观察。租户只取真实设备环境，声明不进入 PermissionFact 或 AgentAsset。

原子预留任务结果摘要，位置、观察、审计和 outbox 同事务；同任务同内容重试幂等，冲突拒绝，审计异常回滚。新增迁移 0022 与每任务唯一 SkillUploadReceipt，保存经过 schema 校验的规范签名输入而非只有摘要；测试从保存输入重算摘要并重新验签。记录不包含技能正文或路径字段，不为每条技能重复保存整批。

18 项上传测试覆盖签名/任务/范围/租约/跨租户/吊销后重放/无授权字段/审计失败；全量 **1278 passed、1 skipped、1 条既有警告，32.48 秒**。随后扩展真实 Alembic 0022 空回退/重升与有数据回退拒绝测试，上传与迁移定向 **19 passed，6.15 秒**。Ruff/diff 通过。PostgreSQL 并发验证未执行，未生产迁移或部署。

没有公开 skill_scan 签发入口，现有 Edge/Connector 还未实现此类型，测试通过隔离库明确构造并签发 fixture 任务；不能将本 API 称作自动技能采集已完成。后续须完成任务签发和能力调度、Edge 范围确认与安全读取、上传和最终回执，再接前端展示与角色关系。

## 第四十三批：Linux 原生独立技能采集

Directory Connector 新增 collect_skills，输出 enterprise-skill-collection/v1，不伪造智能体候选或角色关系。显式绝对 root 与精确 SKILL.md include 门禁；Linux 逐级 openat/O_NOFOLLOW，从已打开目录描述符递归和读取，根/子目录不追随符号链接。只读取普通 SKILL.md，.env 及其他文件不读取；固定枚举批量、深度/条目/时间/文件/字节上限。大小超限或读取中大小/mtime 变化不产生完整摘要，固定状态及路径摘要报告不完整。描述符锚定测试验证原路径被重命名并换成外部符号链接后仍只读原目录对象。

复用清单静态解析器，名称相同位置不同分别观察，重叠 root 去重；失败解析保留完整清单摘要与失败状态，不输出部分工具声明。Linux describe 声明 skill_manifest/tool_names，其他 OS 返回 unsupported；同时修复旧 validate_scope 无论 errors 是否非空都返回 valid=true 的矛盾结果。

Directory `go vet ./...` 和 `go test -race -count=1 ./...` 通过，Edge 同项通过；Windows amd64/macOS arm64 交叉编译通过，不声称这些 OS 已支持技能采集。真实原生 NDJSON 子进程读取两份合成清单（parsed/unsupported），全部观察通过 Python SkillObservationIn 校验，输出无原始正文/路径，见 skill-collection-native-r1.json。Ruff/diff 通过。

未读取真实技能配置、未联网上传、未部署。Connector 操作已实现，但 Edge skill_scan 调度/确认范围/签名上传与回执尚未接通，公开任务签发和前端仍待完成。原有 collect 和 Evidence 门禁不改，既有防攻击规则不改。

## 第四十四批：Edge 技能签名上传客户端与明确回读

新增 prepareSkillUpload，将完整 SkillCollection 校验、规范化、签名并冻结 JSON，拒绝截断/issues、重复位置/工具、失败解析带声明、已知凭据形状、错误清单范围等。上传前重新核对规范输入摘要，本机批次内容改变即拒绝发送。UploadSkills 不隐式重试，不重新读取技能；返回固定未确认错误，避免暴露远端诊断。

控制面响应增加 enterprise-skill-upload-result/v1、task_id 和 batch_digest；客户端逐项核对 schema/任务/摘要/幂等标志/写入数量，不能把任意 200 响应当成上传成功。完整零发现允许空数组，仍持久化一次签名输入与审计；客户端不允许把截断或读取问题转换为零发现。

真实 httptest HTTP + Ed25519 测试覆盖正常、幂等、错误任务/摘要/数量、缺标志、503 不自动重试、本地篡改不发请求；准备阶段负向与空结果测试通过。Edge `go vet ./...`、`go test -race -count=1 ./...` 通过。API 全量 **1279 passed、1 skipped、1 条既有警告，34.59 秒**；Ruff/diff 通过。

客户端暂未由 task runner 调用，持久化签名批次日志、skill_scan 确认范围/调度、最终回执、公开签发和前端仍待继续。测试为原生客户端到测试 HTTP 服务，不是跨语言真实服务端端到端上传证据；未部署或读取真实技能。目标保持进行中。

## 第四十五批：技能签名批次持久日志

新增 edge-skill-upload-journal/v1。Linux 私有状态目录使用逐级 openat/O_NOFOLLOW、所有者/目录权限检查，skill_uploads 目录 0700、任务记录 0600；记录 O_EXCL 创建并同步文件/父目录，不覆盖已有文件。完整写入未确认落盘时重读仍尝试同步；损坏/半写/链接/硬链接/宽权限/超限文件均拒绝，只有确实不存在日志才返回 absent。

任务签名、规范任务摘要、设备上下文摘要、body 任务/范围摘要、设备签名和批次摘要每次复核。上下文绑定 origin、环境、设备、公钥、控制面公钥及确认计划摘要；日志不重复存储 secret/seed，凭据轮换不丢失原签名批次。合法但不同的新批次也不能替换同任务原记录；过期/吊销/当前范围仍须执行器与服务器检查，读取日志不是授权。

首轮测试被权限门禁拒绝，定位为 Go 临时子目录默认权限不等于私有状态目录；仅修正 fixture 为 0700，不放宽产品门禁。日志正常/相同重试/合法不同批次拒绝/本地篡改/部分文件/链接/硬链接/目录权限/设备与任务变更测试通过。Edge `go vet ./...`、`go test -race -count=1 ./...` 和 diff 通过；Windows amd64/macOS arm64 交叉编译通过，日志仅 Linux 实现。

尚未接入 skill_scan runner，没有触发真实采集或上传。后续必须在执行器中先检查当前确认范围，再读取/创建日志、上传、确认回执；不能把独立日志组件冒充已完成自动恢复流程。未部署，原有扫描日志与防御规则保持不变。

## 第四十六批：技能范围确认与原批次恢复执行流程

新增 edge-skill-execution/v1 与 executeSkillUpload，组合持久确认、采集、日志及上传。skill_scan 强制有确认计划并校验摘要/环境/origin，限定 directory + skills + 精确目标，roots 只能取已确认子集、include 只能为 SKILL.md；legacy 无计划不允许执行。任务签名和自身有效期独立验证，读取日志前先核对范围；采集后和上传前再次检查取消与确认。

有日志只重传原签名 body；无日志才采集，签名时仅用原设备身份，先 fsync 保存并重读验证再调用上传。网络响应丢失不返回完成结果、不保存成功台账。隔离测试中首调用上传失败，第二调用不提供采集器仍成功复用原始 body/digest；采集仅一次。后续取消确认不能用旧日志绕过。

新增无计划、计划摘要错、范围外、签名错、损坏日志、预取消等“不调用采集或网络”检查，另测截断、读取错误、采集中取消/移除确认不生成可上传日志。Edge `go vet ./...`、`go test -race -count=1 ./...` 和 diff 检查通过。

此流程用隔离日志和注入回调验证，尚未连接 Runner.Execute/serve、原生子进程与最终控制面回执；不能声称自动恢复全链路已交付。下一步必须把原生采集器/签名制品校验和任务回执接入，并维持未确认上传不得终结任务。未部署或读取真实配置，目标仍进行中。

## 第四十七批：技能任务最终回执门禁

新增 edge-skill-task-receipt/v1 和控制面独立技能回执处理。skill_scan 成功必须携带精确任务/设备、skill_batch_digest、skill_observation_count（含显式零）；只能把已上传任务终结为 delivered。回读验证任务结果摘要、上传记录租户/设备/摘要、保存输入的签名和摘要、输入观察数及数据库实际观察数。普通智能体 evidence 计数不能冒充技能观察，截断结果不能报成功。

任务控制面签名、期限、目标设备与在线吊销保留，首次终结要求有效本设备租约，条件更新/审计/outbox 同事务。终态一致重放不重复审计，但仍校验结果；失败只允许未上传任务，不能覆盖已经上传的观察。普通任务携带技能字段拒绝，不改变原 scan、publish_policy 强制防御逻辑。Edge Receipt 增加可选技能摘要及指针计数，以便明确表达零发现；现有回执不携带新字段。

新增 13 项回执用例，技能上传/回执定向共 **32 passed**；控制面全量 **1292 passed、1 skipped、1 条既有警告，35.08 秒**。Edge `go vet ./...`、`go test -race -count=1 ./...`、Ruff/diff 通过。验证了无上传、假数量/摘要、损坏签名输入、缺字段、过期租约、截断、失败覆盖、审计回滚、零发现与终态重放。

未部署；Edge 执行器仍未调用技能流程，任务签发/能力调度和真实端到端验收仍未完成。此次先封住服务端“收到 success 就完成技能盘点”的缺口，不把接口测试冒充完整自动盘点交付。

## 第四十八批：Edge 技能任务执行器接通

Runner.Execute 新增 skill_scan 分支，位于旧扫描确认/完成台账之前。无日志时验证安装计划、原发行公钥签名制品及实际采集能力，只启动固定安装目录的 directory-connector，不通过 PATH 寻找程序；再次检查 skill_manifest、无网络声明及原范围。collect_skills 固定最多 200 文件/16MiB，结果继续经过原批次签名与持久化门禁。

上传不确认返回基础设施错误，现有任务循环不会发送失败回执。成功回执携带批次摘要和显式观察计数（含零），不进入旧完成台账或绕过范围复核的 pending receipt 队列。任务最终回执未到达时，后续领取 uploaded 任务并重传原批次，再生成回执；不删除原签名日志。

新增 Runner 隔离 HTTP 恢复测试：一次 503 后原 body 完全相同重放、单技能/零技能均产生正确回执、未确认时无终结回执、无旧完成台账/回执日志、移除确认后禁止重传，以及安装制品未验证时不采集/不保存批次。`go vet ./...`、`go test -race -count=1 ./...` 和 diff 检查通过，四个 Go 包全绿。

未修改或削弱原防攻击规则、审批和运行时保护；未部署、未读取真实智能体配置、未签发发行包。本批测试使用预先持久化的合成观察和隔离 HTTP 服务，不声称真实签名安装包全流程通过。任务签发、技能能力调度、角色—技能关联和前端治理仍待完成，持续目标保持 active。

## 第四十九批：技能能力声明与安全领取

新增 enterprise-installed-capabilities/v2，明确 connector_task_types，要求键与实测采集器一致、任务类型有界且不重复。Edge 只有 Directory 实测声明 skill_manifest 且不要求网络时才报告 skill_scan；其他保留 scan。控制面继续接受 v1，序列化不额外写入空字段，既有心跳审计与回滚语义保留。

修复旧领取过滤仅约束 scan、skill_scan 可被无对应能力设备领取的问题。新技能任务要求新鲜有效 v2 技能能力、directory/skills 和精确设备目标；在候选 LIMIT 之前及条件租约更新时重复应用。legacy/v1、过期/未来/缺失心跳、错误能力映射不能领取。uploaded 只允许原租约设备恢复，即使能力撤回；另一设备在旧租约过期后仍不能接管技能上传记录。范围确认、签名、租户和在线吊销检查保持独立。

新增 18 个 API 用例验证能力、目标、前置过滤、恢复、租约与跨环境边界；Go 补充支持/网络声明/旧 Directory/其他 Connector 四种能力投影。控制面全量 **1310 passed、1 skipped、1 条既有警告，36.27 秒**；Ruff、Edge `go vet ./...`、`go test -race -count=1 ./...` 和 diff 检查通过。

本批是隔离数据库与合成设备报告验证，不构成硬件证明或实际部署验收。未执行真实设备上传、生产迁移或发行签名；下一步继续安装计划驱动的技能任务签发与自动初次盘点，随后补角色—技能关系和 UI 治理。全部 22 项持续目标保持 active，未缩小验收范围。

## 第五十批：确认计划驱动的首次技能盘点签发

新增 edge-initial-scan/v2，复用已有设备级幂等记录和原计划审计摘要。明确选择 Directory + SKILL.md 时，Edge 自动申请新版首扫；控制面要求新鲜对应能力及精确版本，签发绑定本设备的 skill_scan。范围只取原确认 roots，include 收窄为 SKILL.md，最多 16 个字面根；不推断或扩大目录。任务、签名、首扫记录、审计与 outbox 同事务。技能 pending 纳入初扫和手工扫描入口的现有租户配额。

Directory 普通扫描排除已交给独立技能任务的 SKILL.md；只选技能时不再生成普通智能体扫描任务，避免把技能当作角色候选。原 v1 普通首扫兼容保留。重放核对任务数量和类型；存量 v1 记录不会被覆盖或假称已补技能任务，升级补扫仍需后续实现。客户端验证 v2 回读和精确任务数，遗漏技能任务或返回旧版响应不能当成功。

新增 8 个 API 测试覆盖精确范围/控制面签名/幂等、能力缺失、配额、审计失败、范围篡改、混合与纯技能范围、存量版本冲突，断言任务/首扫记录/outbox 回滚和一次审计。初轮 fixture 错用版本被门禁拒绝，修正为计划版本；随后修正 outbox 测试读取信封层级，不放宽产品检查。最终控制面全量 **1318 passed、1 skipped、1 条既有警告，37.82 秒**。Edge 新增 v2/纯技能/缺任务/旧响应/glob 拒绝回读测试，`go vet ./...`、`go test -race -count=1 ./...`、Ruff 和 diff 通过。

未部署或运行真实盘点，原签名发行包全流程仍未验收。受控安装目录默认选择、存量设备升级补扫、角色—技能关系、前端批量权限和完整运行审计仍须继续开发；未修改原防攻击规则或授予业务权限，目标保持 active。

## 第五十一批：企业技能清单只读 API

新增 enterprise-skill-inventory/v1 和 /api/v1/skill-installations 清单/详情，连接已签名采集入库后的浏览查询。支持环境/设备精确过滤、最多 200 条游标分页；SQL 窗口选择每安装位置最新 observed_at 观察，同时间按 ID 稳定排序，不逐条加载全部历史。详情保持对象租户定位 404 先于权限 403，列表/详情均要求 agent:read 与 env:read；来源环境租户再次核对，异常跨租户设备绑定不会泄漏。

输出安装位置摘要、环境/设备、吊销状态、manifest 摘要、解析状态、声明工具及观察时间/批次摘要。没有原路径、正文、凭据或签名。presence 明确仅为历史观察，relationship_status=unresolved、effective_permissions=null；观察缺失为 null，不把未知角色归属、未解析技能或未观测权限伪装成已确认空值，不产生任何授权写入。

新增 7 项测试，经真实测试设备签名上传后查询，覆盖读写隔离、声明不冒充有效权限、租户/权限/匿名拒绝、筛选、最新观察、设备吊销历史保留、分页、损坏跨租户来源与请求上限。控制面全量 **1325 passed、1 skipped、1 条既有警告，37.80 秒**；Ruff 与 diff 检查通过。此次未改 Go，因此沿用第五十批 Edge 验证，不声称重新执行。

尚未接入前端技能视图，角色/技能证据关系、可视化批量治理、存量补扫和正式部署验收仍待继续；本轮没有读取真实配置、上传生产资产或变更既有防攻击能力。目标维持 active。

## 第五十二批：企业技能清单前端接通

智能体资产页增加技能清单入口，路由 /agents/skills，继续归属现有资产权限导航。新增响应边界校验：版本、位置/manifest/批次摘要、解析与声明状态、来源过滤、排序/重复游标均核对；非法 effective 声明不渲染。卡片展示技能名、环境/设备、历史吊销状态、声明工具、未核验有效权限及可展开来源摘要；缺观察、未解析、未声明和显式空声明分别表达，不推断角色归属。

支持分页加载、已加载记录搜索、刷新/重试和环境/设备 URL 范围。空态不冒充不存在技能，加载失败不伪装 0。按 React 技能规范使用 keyed request reset、原始值 effect 依赖及渲染期派生搜索，旧请求卸载后不回写，权限撤回时清除缓存记录。视觉核查修复页头默认“连接中”未随查询完成更新的问题。

前端全量 **62 files / 362 tests passed**，新增响应边界及 SSR 展示测试；`npm run build` 通过。隔离 Chromium 浏览器脚本验证分页/搜索、刷新清旧数据/重试、加载更多时权限撤回清除、非法有效权限响应拒绝、正确空态和 375px 窄屏，键盘 Enter 展开溯源；文档及 main/section/article 无横向溢出，浏览器无 pageerror。查看了桌面和窄屏截图。结果与截图在 `.tmp/enterprise-auto-onboarding-20260925/skill-inventory-browser-r3/`；服务已关闭。脚本为 `scripts/enterprise-experience/skill-inventory-browser-smoke.py`，模拟 API 的开发身份构建仅用于本机隔离验证，不冒充真实 IAM/后端 E2E。

未部署，未改生产身份或读取真实技能；原防攻击能力保持。此页当前只读，角色—技能关系树、批量权限变更与完整运行审计仍须继续，22 项目标保持 active。

## 第五十三批：候选批量确认事务基础

新增 enterprise-candidate-bulk-confirm/v1 与批量确认接口，最多 50 个显式候选及预览版本；全部对象先按认证租户定位，缺失/跨租户统一 404，再校验 agent:confirm。重复、超量和空批拒绝，状态或 updated_at 冲突返回 409。按 ID 排序执行条件更新，逐项审计/outbox、资产状态和默认 observed 实例同事务；保留原角色/负责人，不生成业务权限。

原逐项确认抽取事务内共享逻辑，并加入状态/版本原子条件更新，避免与批量确认重复确认同一旧快照。沿用旧接口创建默认 observed 实例的兼容行为；不把它称为已核验运行实例或绑定。批量成功按请求顺序回读，no-store；网络结果未知须读回状态，重复请求 409 不代表前次回滚。

新增 10 个用例，覆盖逐项审计/outbox、观察实例与无权限写入、请求顺序、重复执行拒绝、跨租户定位先于权限、缺对象/查看者/旧版本/重复/空/超量、第二次审计失败整批回滚、读取后版本漂移条件更新拒绝。初次测试使用不存在的 PermissionFact 字段，修正断言为既有 subject_id，未改产品模型。最终全量 **1335 passed、1 skipped、1 条既有警告，37.69 秒**，Ruff 和 diff 通过。版本漂移使用隔离数据库故障注入，不声称已验证真实 PostgreSQL 并发。

ENT-011 转 doing，前端批量选择/确认、批量驳回与持续漂移仍待完成；智能体/技能业务权限批量变更不由本接口替代。未部署、未确认真实候选、未授予业务权限，既有防攻击规则保持，完整目标继续 active。

## 第五十四批：前端候选批量选择与安全确认

候选列表接入逐项勾选、选择已加载前 50 个、清除选择与确认前预览。弹窗逐项显示名称/框架/状态/版本/ID，显式声明不授予业务权限、不启用拦截，保持已有用途/负责人；勾选核对后才可提交。共享桌面表格与移动卡片选择状态，查看者不展示批量入口，已有逐条处理保留。

新增客户端请求/回读边界：仅发送所选 ID/预览版本，拒绝空/重复/超量/非候选/无效时间；结果必须顺序、身份、状态和数量一致。提交用 ref 锁避免重复点击，进行中不能关闭弹窗；任何未知结果转为只读核对，不自动 POST 重试。每组最多 5 个并行 GET，全部待处理则重新预览并清除确认勾选；状态混合不处理剩余项，全部 confirmed 仅报告当前读回状态。React 技能用于渲染期派生选择状态、事件驱动提交和受限并行读取，敏感状态不入浏览器持久存储。

前端全量 **63 files / 369 tests passed**，构建通过。初次参数化测试将数组当成多个参数，修正 fixture 包装后全部通过，产品校验未放宽。隔离浏览器模拟服务器写入已成功但响应丢失，确认仅 1 次 POST，后续 GET 核对成功；版本冲突后重新预览要求再次勾选，未自动写入；查看者无批量操作入口。375px 弹窗截图已查看，浏览器无 pageerror，模拟服务已停止。脚本 `scripts/enterprise-experience/bulk-candidate-browser-smoke.py`，结果 `.tmp/enterprise-auto-onboarding-20260925/bulk-candidate-browser-r1/`；属于模拟 API UI 验证，不等同真实后端/IAM E2E。Ruff/diff 通过。

未部署、未处理真实候选或权限；此批只完成批量资产确认，不能替代智能体/技能业务权限治理。批量驳回、持续漂移、角色—技能关系与完整权限执行/审计仍须继续，目标 active。

## 第五十五批：候选批量驳回后端与审计收口

新增 enterprise-candidate-bulk-dismiss/v1，复用批量确认的显式对象/版本、1–50 上限、去重、租户定位先于权限、按 ID 写入顺序与整批事务。仅接受 duplicate/out_of_scope/not_agent 三种原因码，保存固定原因，不接收自由文本或批量到期覆盖；驳回保留资产记录，不删除配置、不停止进程、不创建观察实例或业务权限。

逐条驳回抽取事务内逻辑，补状态/更新时间条件更新，防止覆盖已确认/已处理对象；补逐项 agent.asset.dismissed.v1 outbox，与审计/状态同事务。审计原因改为 SHA-256，不再复制用户自由文本；原逐条 API 原因字段保持兼容。确认/驳回的批量查询和回读逻辑共享，响应顺序/no-store 保留。

新增 13 项测试，验证请求顺序、原因保存、无新增实例、逐项审计/outbox、重复驳回及后续确认拒绝、跨租户与权限、缺失/旧版本/重复/空/超量/无效原因/额外字段、第二条审计或 outbox 失败时全批回滚、逐项审计不带正文。定向 32 项通过；控制面全量 **1348 passed、1 skipped、1 条既有警告，38.47 秒**，Ruff/diff 通过。没有真实 PostgreSQL 并发或生产部署验收声明。

前端批量驳回入口尚待接通；持续漂移、角色—技能关系及业务权限批量管理不由候选驳回替代。未操作真实候选/配置/权限，原防攻击能力不变，完整 22 项目标保持 active。

## 第五十六批：前端批量驳回及双动作回归

候选列表增加“核对并批量驳回”。原 BulkCandidateConfirm 改为 BulkCandidateReview 共享组件，通过显式 action 分离确认/驳回请求、响应版本、成功状态和文案；没有使用任意成功状态代替指定动作终态。驳回原因限定三个选项，默认未选；必须选择原因并勾选核对，原因变更清除勾选。进行中和未知结果阶段禁止修改原因，恢复仍只读、无自动重试。

API 客户端增加 dismissCandidateBatch，验证选择、原因和精确 dismissed 响应；confirmed 响应不能用于宣称驳回成功。按 React 技能保持用户事件内发起写请求，用 action key 隔离弹窗状态，避免 effect 重跑或动作切换复用旧确认。完整保留确认流程，已读回提示不归因于本次写入、不暗示权限改变。

前端全量 **63 files / 373 tests passed**，TypeScript/Vite 隔离构建通过。同一浏览器脚本分别执行 confirm 与 dismiss：明确选择/核对、服务器已写入但响应丢失后只读恢复、版本冲突后重新核对、查看者无入口均通过；驳回额外验证无原因不可提交、修改原因清除勾选、请求 reason_code 精确。查看了 375px 驳回弹窗截图，无 pageerror；两套模拟服务已关闭。证据分别在 `.tmp/enterprise-auto-onboarding-20260925/bulk-dismiss-browser-r1/` 和 `bulk-confirm-browser-r2/`；Ruff/diff 通过。不将模拟 API 测试冒充真实后端/IAM 或生产验收。

本轮不改后端，不重复报告未重跑的后端/Go 测试。未部署、未执行真实批量操作，既有防攻击能力不变。下一阶段继续角色—技能证据关联、漂移及业务权限治理，完整目标 active。

## 第五十七批：OpenClaw 角色稳定身份与证据隔离

为推进角色—技能关系检查采集事实，发现 OpenClaw 旧候选以显示名称为身份，证据 ID 使用 agent.id 与配置摘要文本编码的前 16 位，存在同名、共同 ID 前缀及多配置根碰撞。新增 enterprise-openclaw-identity/v2：角色身份由规范绝对配置根与明确 agent.id 的 JSON 元组 SHA-256 构成；证据身份再绑定完整配置摘要。名称改变保留角色身份，配置变化新增证据；重复根去重。缺失/重复/超限/控制字符 ID 和无效 UTF-8 拒绝，不从显示名称猜测角色。

同时修复 auth-profiles 元数据证据固定 ID 和缺少候选引用：按配置根摘要隔离，仅被本根候选引用，本根无候选则不生成孤立证据。仍只记录名字/大小，绝不读取或哈希凭据内容；模型/文件权限仍为 declared。旧 v1 资产不按名称自动合并，迁移归属另行复核。

新增 5 个 Go 测试，覆盖多根同名/同前缀分离、重复根、名称变更稳定性、配置变化证据更新、无效/歧义身份、孤立元数据拒绝及 UTF-8 替换身份风险。首轮临时测试路径含 Secret 被既有范围规则拒绝，改测试名称，不放宽门禁。OpenClaw 与 Edge 均 `go vet ./...`、`go test -race -count=1 ./...` 通过；最终 OpenClaw Windows amd64/macOS arm64 交叉编译通过（未运行验收）；diff 通过。

本轮仅读取项目源码及隔离 fixture，未扫描真实用户配置、未部署或签发包。角色—技能显式关联、默认 OpenClaw 角色识别、历史迁移仍待继续，不能把身份基础修复称为关系图已完成。原防攻击能力保持，完整目标 active。

## 第五十八批：OpenClaw 角色技能范围声明与双布局兼容

新增 enterprise-openclaw-skill-selection/v1 合同，核对官方 skills-config 与旧 list 布局文档，采集显式角色 skills 或缺省继承的 agents.defaults.skills。显式空数组、缺省未配置与解析不支持分别表示；显式 null/错误类型不得回退到默认值。最多 64 个互异、限长且通过既有脱敏检查的机器标识，排序存储；异常整项不保留部分名称。不读取或执行技能正文，不按名称认定已安装，不生成 effective 或业务权限。

兼容 agents.list 与 agents.entries，entries 按键排序并使用键作为角色 ID；双布局同时存在、键与内嵌 ID 不一致、null entry 拒绝。稳定身份继续沿用 v2，同配置根同 ID 在布局切换后不变。声明作为候选 attributes.skill_selection 的有界 JSON 字符串，引用原配置摘要证据；已有候选属性上传类型无需变更。不可变关系历史、精确安装位置匹配、默认角色识别及前端关系图仍未完成。

新增 4 个 Go 测试函数，包含继承/覆盖/空列表/null/类型/重复/敏感形状、数量与长度界限、两布局身份稳定与无权限事实、歧义与空 entry 拒绝。OpenClaw 与 Edge 均执行 `go vet ./...`、`go test -race -count=1 ./...` 通过；OpenClaw Windows amd64/macOS arm64 交叉编译通过（非真机运行验证）。`git diff --check` 通过。本批未改前端或控制面实现，没有重跑并冒领其全量测试。

仅源码与隔离 fixture 验证，未扫描真实用户配置、上传资产、部署、签发或授予权限；既有防攻击规则未修改，完整目标保持 active。

## 第五十九批：角色技能范围追加历史与来源隔离查询

候选属性会随新扫描覆盖，不能用作历史关系事实。本批新增 enterprise-role-skill-observations/v1、RoleSkillSelectionObservation 及迁移 0023：按资产/任务唯一追加已验证设备批次中的 OpenClaw 范围声明、任务/批次摘要、观察/接收时间和本批证据快照，租户/资产复合外键避免跨租户引用。与既有批次状态、审计同事务，审计增加观察数；审计失败全部回滚，同任务重放不新增。历史只有应用追加路径，没有修改/删除 API；不宣称数据库管理员不可篡改或单凭摘要能离线重验整批签名。

入站校验要求 openclaw 任务/框架/source_type/v2 定位和身份一致，范围 JSON ≤10000 字节、1–64 个互异证据引用；拒绝状态/来源不一致、未排序或重复名称、敏感形状、额外字段、重复 JSON 键、重复资产定位与歧义证据。错误不回显输入。旧客户端缺字段继续兼容，不从旧属性伪造历史；名字不能推导安装或有效权限。

新增 GET /api/v1/agents/{asset_id}/skill-selections，租户定位先 404 后 agent:read/env:read，no-store；最多 100 条、显式截断，历史设备吊销仍可辨识，当前设备/环境来源不匹配不投影。空历史明确 no_recorded_declaration，始终 relationship_status=unresolved/effective_permissions=null；不输出配置路径、签名或秘密正文。前端尚未消费此接口，精确安装关联与漂移裁决仍待完成。

新增 21 项 API 用例及迁移扩展，覆盖实际测试签名上传、历史不被覆盖、原批次重放、跨租户/权限、非法与敏感声明、来源/证据歧义、旧属性不回填、审计失败回滚、100 条边界和异常外租户设备；隔离 SQLite 迁移验证清库升级、空回退、租户复合 FK/唯一约束、非空降级拒绝，非真实 PostgreSQL 验收。初次断言误用共享全表计数，补测历史任务又占用其他测试租户配额，已修正为专属租户、对象范围断言和已上传历史任务，没有放宽产品配额或安全门禁。

最终 `uv run ruff check app migrations/versions/0023_role_skill_observation.py`、`uv run pytest -o addopts='' -q -rs --tb=short` 通过：**1369 passed、1 skipped、1 条既有 Starlette/httpx 警告，40.98 秒**。唯一跳过为未提供隔离浏览器 Go grant-batch 样本的既有测试。日志 `/tmp/siq-role-skill-api-tests-r4.log`，diff 检查通过。未部署/迁移生产、未操作真实资产或权限，防攻击规则未修改，完整目标继续 active。

## 第六十批：角色技能声明历史前端与交互验证

智能体详情增加角色技能声明面板：用户可在最多 100 条历史中选择一条查看，明确默认继承/角色显式/未配置，以及显式空、未配置、解析不支持与无历史的区别。安装关联固定显示尚未解析，有效权限未由声明确认；凭据吊销与在线状态分别说明。只提供设备范围技能清单跳转，不按同名建立归属。默认展示范围与关联状态，观察/接收时间、任务/设备/批次摘要和证据收进可键盘展开的溯源详情，不渲染所有历史的完整证据树。

客户端对响应版本、资产身份、状态一致性、100 条上限/截断标志、观察/任务去重、声明名称及范围状态、证据界限/摘要/时间戳、接收时间降序做运行时验证。拒绝错误资产、伪 effective、坏摘要、部分/重复声明等响应；403 与其他错误均不伪装成空历史。按 React 最佳实践采用资产/刷新 key 隔离请求，清理后忽略旧响应，选中记录由渲染派生，来源面板与声明面板独立请求不互相阻塞。没有浏览器持久化敏感状态或权限写操作。

前端全量 `npm test` **65 files / 403 tests passed**，TypeScript 与隔离 Vite 构建通过。初次构建报闭包内 unknown 属性收窄丢失，提取已校验的局部数组后通过，未使用 any 绕过校验。新增浏览器脚本 `scripts/enterprise-experience/role-skill-browser-smoke.py` 验证历史选择、键盘溯源、375px 长标识/摘要无横向溢出、七类状态、手动刷新恢复、前次响应迟到不覆盖新数据、无 pageerror 和无写请求；模拟服务已停止。

查看了桌面及移动溯源视口截图，缩短默认字段后重跑浏览器全部通过。证据 `.tmp/enterprise-auto-onboarding-20260925/role-skill-browser-r2/`，日志 `/tmp/siq-role-skill-web-tests-final.log`、`/tmp/siq-role-skill-web-build-final.log`。浏览器使用显式模拟 API 和 VITE_DEV_MODE=true 隔离构建，不是可发布生产包或真实后端/IAM E2E。脚本 Ruff 与 diff 检查通过。本批未改控制面/防御判定，不冒领其未重跑测试；未部署或操作真实资产，精确安装关联、漂移与业务权限批量管理仍继续，完整目标 active。

## 第六十一批：企业 OpenShell 受控只读连接诊断

推进 ENT-012，ADR-052 采用既有控制面 CLI + 网关适配器，不新建未经联调的 HTTP 桥，也不把策略发布权限交给 Edge。新增 enterprise-openshell-connection/v1 和 GET /api/v1/environments/{environment_id}/openshell-connection；先环境租户定位、再 env:manage/policy:read，响应 no-store，scope 明示 control_plane_connection，不把共享控制面网关归属强加给环境。

只读包装器复用 gateway info/status/version 解析；显式绝对普通可执行文件、非 group/world writable、HTTPS，无环境脚本、userinfo/query/fragment、非根路径或 insecure（回环也拒绝）。固定命令白名单及整个诊断 10 秒预算，冻结 endpoint 和白名单子进程上下文，前后核验 CLI 文件元数据指纹。原执行器新增可选冻结环境参数，仍二次白名单过滤，旧调用路径保持行为。未执行或修改任何真实网关配置。

诊断分别返回缺配置、配置拒绝、调用失败、身份未确认、版本未知或握手成功；不输出路径、原始 endpoint、环境、网关名及 stderr。配置表达能力与执行证据分离，ready_for_deployment 固定 false、execution_evidence=none，最小凭据/版本兼容仍 unverified；未知版本不猜兼容、失败不复用旧成功。文件元数据指纹不等同已签名制品完整性，同路径证书替换检测仍未完成；此入口不替代部署审批、绑定和行为核验。

新增 22 项连接测试及 1 项真实隔离子进程冻结环境过滤测试；覆盖 HTTPS/脚本/insecure/相对路径/坏 URL、文件缺失/宽权限/符号链接、隐私、冻结目标、命令白名单、未知版本、错误 status、文件调用期间变更、预算耗尽以及跨租户/权限先于探测。所有 OpenShell 输出来自注入 fixture，未使用本机真实 CLI/网关或凭据。

`uv run ruff check app`、`uv run pytest -o addopts='' -q -rs --tb=short` 和 diff 检查通过；控制面全量 **1392 passed、1 skipped、1 条既有警告，41.75 秒**，日志 `/tmp/siq-enterprise-connection-api-tests-final.log`。唯一 skip 仍为缺少隔离浏览器 Go grant-batch 样本。本批没有前端实现或生产部署声明，ENT-012 为 doing，正式最小凭据/兼容矩阵/真实环境与前端接入仍待继续，目标 active。

## 第六十二批：OpenShell 高级诊断前端

环境页选择环境后提供默认折叠的“高级诊断：OpenShell 控制面连接”。加载页面或展开面板不触发命令，只有点击检查才发起只读 GET；请求等待为 15 秒，覆盖后端 10 秒总探测预算。按 React 技能使用事件触发而非 effect 自动执行、ref 防重复、环境 key 隔离及卸载后忽略结果；新检查清空旧结果，错误不保留成功外观，重试只由用户操作。

客户端严格校验响应版本、环境、控制面作用域、状态与版本/指纹/配置能力一致性，拒绝 ready_for_deployment=true 或伪执行证据。面板明确网关/沙箱归属未证明，版本兼容/最小凭据/实际效果未验收；错误、缺配置、拒绝不安全配置、未知版本和握手事实分别说明。原环境接入与权限审批路径保留。

`npm test` **67 files / 420 tests passed**，TypeScript/Vite 隔离构建通过。浏览器脚本 `scripts/enterprise-experience/connection-browser-smoke.py` 验证加载/展开零探测、挂起时按钮禁用且单请求、键盘展开、375px 摘要无横向溢出、403、错环境响应及手动恢复，未发送写请求、无 pageerror，服务已停止。初版 mock 错用 onboarding/access 路径，修正为真实 environments/access 后通过，未修改产品接口。移动截图已查看。

证据 `.tmp/enterprise-auto-onboarding-20260925/connection-browser-r2/`；日志 `/tmp/siq-connection-web-tests.log`、`/tmp/siq-connection-web-build.log`。构建使用 VITE_DEV_MODE=true，只供隔离模拟 API 验证，不是正式发行或真实网关验收。脚本 Ruff/diff 通过；本轮未变更后端、防攻击规则、真实网关或资产权限，未部署，完整目标保持 active。

## 第六十三批：运行时绑定环境一致性与部署前漂移守卫

推进 ENT-013，新增 enterprise-runtime-binding-identity/v1。检查发现登记接口先权限后对象定位，且实例环境与绑定请求环境可不一致。改为先同租户定位实例/资产/环境，再 policy:manage；环境未知和不一致分别拒绝，不通过绑定静默补全或搬迁实例。部署准备重新核对实例、资产、租户、环境引用，漂移在适配器调用前 409 binding_source_identity_changed；预览保留同一固定错误码。历史绑定不自动改写，模型说明 active/客户端 attestation 仍是声明而非后端证明。

新增登记定位/权限顺序、未知与异环境拒绝、部署前环境/资产/实例租户/资产租户漂移测试。首轮全量发现旧 E2E 将无环境证据的自动观察实例直接绑定，改为先验证拒绝，再走真实 API 显式登记环境内实例，保留原观察实例。该路径进一步暴露实例创建在生成 ID 前构造审计/outbox 的既有错误；补同事务 flush，并断言审计和事件引用实际实例 ID，没有削弱 outbox 非空引用守卫。

网关/设备/Skill 摘要/沙箱 revision 证据绑定、共享沙箱影响、撤销联动及外部写入并发仍待实现；此批只是来源引用一致性，不能冒称完整运行身份核验。未操作真实数据库/网关/权限或部署，完整目标继续 active。

最终 Ruff、diff 与控制面全量通过：`uv run pytest -o addopts='' -q -rs --tb=short` **1401 passed、1 skipped、1 条既有警告，42.02 秒**。新增 9 项用例，既有 E2E 经显式实例登记后完整通过；唯一 skip 仍为缺少隔离 Go grant-batch 样本。日志 `/tmp/siq-binding-identity-api-tests-r3.log`。不把 fake 后端治理 E2E 当作真实 OpenShell 行为或 PostgreSQL 并发验收。

## 第六十四批：独立运行目标授权清单基础

继续 ENT-013，记录 ADR-053 与 enterprise-runtime-target-authority/v1。租户自行填 target/attestation 不能证明对控制面共享网关目标的控制权，新增部署管理员独立维护的精确授权清单读取与匹配模块。条目绑定验证租户、环境、资产、实例、连接指纹、网关名称摘要和目标；禁止通配/部分匹配，相同连接+目标重复分配整份拒绝，包括跨租户、异网关名的重复。共享沙箱暂不通过放宽唯一性支持。

Linux 描述符逐级 nofollow 打开绝对路径，末级验证普通文件、root/服务 UID 所有、无 group/world 写权限、单硬链接及 256 KiB 上限；读前后元数据变化拒绝。JSON 重复键、UTF-8、额外字段、标识长度/形状、1024 项上限、UTC 签发/到期时间均校验，错误只含固定代码。每次重读、不缓存；删除/到期/连接漂移/资产实例变化不沿用旧授权，成功只返回条目引用、清单摘要和到期时间，不投影其他租户。

新增 29 项测试，覆盖成功精确匹配、五类身份字段错配、两类连接漂移、摘要变化/删除、时间与重复分配、通配/版本/额外字段、符号链接/祖先符号链接/硬链接/FIFO/宽权限/超限/重复 JSON/编码、文件所有权和读取中变化。所有内容为临时 fixture；没有读取真实授权文件或注册授权。配置模板仅增加注释示例，并明确尚未接入部署门禁。

`uv run ruff check app`、diff 与控制面全量通过：`uv run pytest -o addopts='' -q -rs --tb=short` **1430 passed、1 skipped、1 条既有警告，42.43 秒**，日志 `/tmp/siq-target-authority-api-tests.log`。唯一 skip 仍为既有隔离 Go grant-batch 样本缺失。此清单是管理员授权而非实际运行身份/发行签名证明；登记/预览/提交/执行接线和清单摘要重验尚未完成，不能声称旧部署路径已受该门禁保护。未改真实业务权限或部署，原安全门禁保持，完整目标 active。

## 第六十五批：运行目标授权接入部署与回滚门禁

继续 ENT-013。OpenShell CLI 部署准备在编译/读取目标策略前校验独立授权，预览摘要绑定授权条目、清单摘要和有效期；执行外部写入前重新探测连接、重新读取清单并比对准备阶段授权。缺连接身份、缺授权、过期、租户/连接错配或准备后变更均拒绝。不对开发模式 CLI 豁免，不让客户端 attestation 或模型输出代替管理员清单；fake 开发后端保持模拟语义。

部署成功回执记录授权摘要、连接指纹与网关名称摘要，部署审计包含授权摘要；回滚重新检查来源引用、当前授权及原回执连接，缺旧连接证据失败关闭。原审批、来源身份、隔离、选择器、版本冲突、读回校验与审计事务均保留。清单不证明沙箱内实际角色/Skill，不代表行为防御验收，最后检查与外部写入之间的全部竞态仍待专门处理。

为既有 CLI 成功路径补充独立管理员临时文件夹具，走真实安全读取与精确匹配，而非模拟授权通过。新增七项负向测试覆盖缺配置、删除、过期、异租户、预览后续期、准备后变更、回滚前删除授权，断言目标无写入；成功部署回执检查授权与连接证据。初轮全量发现规则展示测试缺少新授权夹具，已补齐。所有测试仅隔离 fixture，未读取或生成真实环境授权清单，未部署、提交或发布。

最终 Ruff、diff 检查通过；控制面全量 `uv run pytest -o addopts='' -q -rs --tb=short` **1437 passed、1 skipped、1 条既有警告，42.96 秒**，日志 `/tmp/siq-authority-gate-api-tests-r3.log`。唯一 skip 为缺少既有隔离 Go grant-batch 样本。ENT-013 与完整目标保持 doing/active，后续继续设备/角色/Skill 运行证据与安装自动接入，不把源码门禁当作已上线能力。

## 第六十六批：配置读取失败不再冒充空资产

继续 ENT-009，并支撑 ENT-006 的首扫结果真实性。检查 OpenClaw collector 发现读取配置失败时仅输出原路径错误并继续，全部失败可能返回成功空清单；多根扫描则可能把部分结果冒充完整。新增 enterprise-openclaw-collection-status/v1 行为合同，缺文件、权限不足与其他不可读取分别返回固定错误，停止整批且不返回部分证据。JSON 解析错误不再回传底层解析消息。既有预算 truncated 语义、只读范围及权限声明层级保留，不根据扫描失败推断卸载。

新测试覆盖错误分类脱敏，以及缺文件/目录冒充文件/损坏 JSON/错误类型在单根、先成功后失败和先失败后成功三种组合下均失败；同时验证 Connector 协议信封无成功结果或部分清单。源码核对 Edge runScan 在 Collect 错误后立即返回，任务写 failed 回执，不到签名与批次上传。没有扫描真实用户配置或上传设备数据。

OpenClaw 与 Edge 分别执行 `go vet ./...`、`go test -race -count=1 ./...` 全量通过；Edge 四个包通过，日志 `/tmp/siq-collection-status-edge-tests.log`。OpenClaw Windows/AMD64 与 macOS/ARM64 测试交叉编译通过，产物 `/tmp/siq-openclaw-status-y4Q0Dj`；不代表原生执行验收。`git diff --check` 通过。默认角色/JSON5 支持、最终安装入口和真实首扫验收仍未完成；本批不把修复错误展示等同于完成自动接入。完整目标继续 active，未部署、提交或发行。

## 第六十七批：默认单角色配置发现

继续 ENT-009。查验 OpenClaw 官方 https://docs.openclaw.ai/concepts/multi-agent 的单智能体模式说明，补 enterprise-openclaw-default-role/v1。已授权根的严格 JSON 配置成功读取、没有显式 list/entries 时生成 main 配置候选；新增 role_identity_basis=config_default，显式角色为 explicit_config。不将配置角色描述为正在运行，不从路径约定或当前进程环境编造权限。继承已声明 defaults.workspace/model/skills；技能仍为范围声明而非安装关系。

沿用根+角色 ID 的 v2 位置身份，默认 main 转显式 main 不重复建资产，不同根不混并。显式空 roster 仍为空；null 根/agents/defaults/roster、重复键、非对象根、超过 64 深度、任意层级 $include 均拒绝。这样未解析 include 或歧义 JSON 不会产生虚构默认角色。仅静态读取，未启用配置执行、额外目录扫描或真实设备上传。JSON5、受控 include、精确 Skill 安装关系和实际运行证据仍待完成。

新增 Go 测试覆盖三类默认布局、无凭空权限、显式默认值继承、技能 defaults 来源、默认转显式身份和证据、不同根隔离、十四种歧义输入及显式空 roster。新增 API 消费者用例验证默认候选及声明历史接收、转显式同资产、候选不自动确认、无有效权限。测试使用独立模拟配置与签名设备夹具，不冒充真实端到端验收。

OpenClaw/Edge 的 `go vet ./...` 与 `go test -race -count=1 ./...` 全量通过；Edge 日志 `/tmp/siq-openclaw-default-edge-tests.log`。OpenClaw Windows/AMD64、macOS/ARM64 测试交叉编译通过，临时产物 `/tmp/siq-openclaw-default-3KAriY`；不代表原生运行。完整目标 active，未提交、部署或发行。

API 首轮新增测试误用 relationship 字段，按既有合同修正为 relationship_status；实现未因该断言改动。最终 Ruff、diff 和控制面全量 `uv run pytest -o addopts='' -q -rs --tb=short` 通过：**1438 passed、1 skipped、1 条既有警告，43.25 秒**，日志 `/tmp/siq-openclaw-default-api-tests-r2.log`。唯一 skip 仍是缺少隔离 Go grant-batch 样本。仅此默认配置能力与现有安全门禁验证通过，不提前销项 ENT-009 或整体安装交付目标。

## 第六十八批：有界 JSON5 静态配置转换

继续 ENT-009，依据 OpenClaw 官方配置参考补 enterprise-openclaw-json5/v1。支持注释、尾随逗号、单引号、标识符及 Unicode escape 键、JSON5 空白、字符串换行续接/十六进制转义和有限数字写法；纯数据转换后仍走标准 JSON 语法、重复键/深度/include 守卫。输入 16 MiB、262144 token、输出 32 MiB 有界，非有限数与超过 uint64 的十六进制数拒绝，明确不是无约束完整 JSON5。摘要仍绑定原始配置字节，不把格式不同的新观察覆盖成相同证据。

曾只读评估数个外部库，因重复键保留、运行工具链或转换边界不合适未纳入；最终无新增依赖、无锁文件变动，无 JS 解释器或配置执行。新增格式等价与原始证据、七组数据写法、十八组非法/歧义输入及预算测试。OpenClaw 与 Edge 的 `go vet ./...`、`go test -race -count=1 ./...` 全量通过；日志 `/tmp/siq-openclaw-json5-tests.log`、`/tmp/siq-json5-edge-tests.log`。Windows/AMD64 与 macOS/ARM64 测试交叉编译通过，产物 `/tmp/siq-json5-cross-NJ2uGV`。仅静态模拟配置测试，未扫描或上传真实设备数据，未正式发行。

## 第六十九批：接入结果优先与自动刷新

推进 ENT-017。EnvironmentSetup 默认展示设备注册/心跳/近期发现结果及资产入口，将地址、终端、注册码、手动心跳/领取与补扫等收进原生 details 高级区。每 15 秒只读刷新，可暂停，隐藏页面不轮询；单次请求未结束不叠加轮询，卸载/换环境忽略旧响应。失败清除旧成功结果而非显示 0，未收到任务不等于没有智能体；历史完成不冒称当前全部在线或权限已生效。设备/任务截断范围明确。移动环境表格改卡片，避免名称文字被挤碎。

使用 vercel-react-best-practices 的副作用依赖、派生状态和清理原则，未添加业务自动写入。导航文件保留给用户安排的 Claude Code/Qwen 子任务，未触碰其责任范围。新 enterprise-onboarding-results/v1 与 SSR 测试、隔离浏览器脚本落盘。Web **68 文件、422 测试通过**，TypeScript/Vite 构建通过；模拟构建 `/tmp/siq-onboarding-results-web-r3` 使用开发身份，仅供夹具，不可部署。日志 `/tmp/siq-onboarding-results-web-tests-r3.log`、`/tmp/siq-onboarding-results-build-r3.log`。

浏览器八项检查通过：结果优先/高级折叠、自动完成状态读回、暂停、隐藏页面暂停、失败清除成功、待处理按钮禁用/键盘展开、切环境丢弃旧响应、375px 无横向溢出/无写请求/无异常。截图与结果 `/tmp/siq-onboarding-results-browser-r3`，已查看桌面及移动截图；初次移动截图处于模拟时钟冻结的布局过渡，修正等待/禁动画后重验，并修复实际表格挤压。Ruff 的 C408 夹具格式问题机械修正，脚本检查通过，测试服务已停止。

ENT-017 保持 doing。正式签名安装包、最终 Skill 安装引导、真实用户服务生命周期、真实首扫到结果页仍未验收；此批不能作为 M1 完成。整体目标继续 active，未提交、部署或发布。

## 第七十批：目标设备交互确认安装范围

推进 ENT-004。增加 Linux setup-enterprise --interactive，保留独立 tenant/environment/control-plane 上下文，直接展示组织、环境、控制面、平台、采集目录/文件及是否启动当前用户服务。仅完整 yes 确认，默认拒绝，无需人工抄写摘要。交互模式禁止与 review-only/摘要参数/stdin-code 参数混用，要求真实终端；自动化仍使用原显式摘要入口。确认后重读原计划，任何字节变化返回 enterprise_setup_plan_changed，重新检查有效期后才继续身份处理。

复用已有 prepare→注册/恢复/复用→范围保存→用户服务安装链路，没有绕过原发行公钥、制品摘要或范围门禁。新设备仅在验签/暂存/能力核验后提示注册码；Linux termios 关闭 ECHO/ECHONL，成功、取消、提示写失败均恢复终端属性，错误不回显敏感输入。确认输入逐字节有界读取，避免缓冲器提前吞掉下一行注册码。默认仅配置，--start 明示启动，不提权、不启用 linger、不批准业务权限。

新增交互合同、实现、测试并更新 Edge README/help。测试包括精确 yes/默认取消/超长与无换行输入、完整范围展示、后续输入保留、真实 Linux PTY 无回显/恢复、取消/输出失败、非终端拒绝与混合参数拒绝，以及实际 setup CLI 在临时 PTY 下确认后拒绝计划变化或未签名制品，未写设备状态且未询问注册码。所有组织、目录、代码均为隔离 fixture，未注册真实设备或安装系统服务。

Edge `go vet ./...`、`go test -race -count=1 ./...` 四包全量通过，最终日志 `/tmp/siq-interactive-install-tests-r4.log`；Linux/AMD64、macOS/ARM64、Windows/AMD64 测试交叉编译通过，产物 `/tmp/siq-interactive-cross-a1Z54X`（最后新增仅 Linux 测试的输出失败用例后以原生全量复核）。本机原生 PTY 测试不等于 systemd/重启或正式签名包验收。完整目标 active，未提交、部署、签发或发布；正式包下载与真实首扫到结果页仍待完成。

## 第七十一批：企业离线候选包构建入口

推进 ENT-004，新增 enterprise-release-candidate/v1 和独立 enterprise_candidate.py。
从完整 Git 提交导出 Edge、三个默认采集器及许可源码，强制与独立审阅的源文件清单比对；
不混入工作树改动。白名单构建环境，禁用 Go workspace、模块下载、工具链自动下载和 cgo，
Linux amd64/arm64 布局遵守正式 release 合同，核对 ELF 架构、字节数与摘要。
Edge/Hermes/OpenClaw/directory 的默认版本保持 0.1.0，改为可通过链接器注入的变量，
避免包版本更新但实际采集器 describe 仍返回旧版本。旧提交缺少注入支持则拒绝。

产物明确为 CANDIDATE.json，signed/installable/published 均 false，无 release.json、
签名或 READY；不能绕过正式安装器。输出新目录，构建失败不留下最终输出；输出转移失败
可能保留不完整候选供人工检查，不能当作安装包。未读取签名密钥、未签发、未注册设备。

发行工具 unittest 全量 **24 passed**（3.067 秒），日志
`/tmp/siq-enterprise-candidate-tests-r2.log`。包含隔离合成 Git 仓库的真实双架构构建、
重复构建一致性、源码清单不一致提前拒绝、工作树/未跟踪文件排除、编译失败不产出，
以及当前三个实际 Connector 的原生 describe 版本注入读回；只 describe，不扫描配置。
Edge 四包与 Hermes/OpenClaw/directory 分别 go vet 和全量 go test -race -count=1 通过。
本批两个 Python 文件 Ruff 与 git diff --check 通过；扩大到 scripts/release 全目录时
首次发现 17 项 Ruff 问题，其中本批新增测试的 SIM117 已修复；其他既有脚本仍有
16 项（如 EXE001、PLW1510），未跨范围修改或冒称全目录通过。

固定提交夹具验证不等于产品源码冻结或正式包验收。目前产品增量仍在工作树，不能使用
旧提交声称包含最新功能。正式签名/分发、目标设备完整安装生命周期和首扫仍待完成。
未修改外部分工的导航文件，未提交或部署；完整目标继续 active。

## 第七十二批：候选包可搬运归档与重复构建核验

继续 ENT-004。企业候选构建新增明确命名的 unsigned-candidate.zip，复用已验证的
ZIP 写入/回读逻辑，固定时间戳与可执行位。归档在源目录外生成，避免把自身打入包；
外层 SHA256SUMS 覆盖 ZIP 与散文件，ZIP 本身包含二进制、候选元数据、说明和许可，
不包含自身/外层 SHA256SUMS。源码和打包主脚本、共享 helper 摘要保留用于复核。
仍无 release.json 或签名，归档不提升信任等级，禁止复制历史签名使其看似可安装。

扩展测试逐文件比较 ZIP 与散文件、核对权限位/时间戳/外层摘要，重复构建含 ZIP 字节
一致；新增已审阅旧 const 版本提交在 Go 构建前拒绝，以及归档核验失败无最终输出。
发行工具全量 **26 passed**（2.841 秒），日志 `/tmp/siq-enterprise-portable-tests.log`；
本批两个 Python 文件 Ruff 与 git diff --check 通过。实际 Connector 原生 describe
版本注入仍在该测试集中验证，没有扫描用户目录。此次未改 Go 运行逻辑。

仅隔离合成提交测试与当前 Connector describe 检查，不是正式产品候选、签发、部署或
目标设备安装验收。导航文件与 PermissionsPage/permission-facts 已分别保留给外部分工，
本批未修改。完整目标继续 active，源码冻结、签发及真实安装闭环仍待推进。

## 第七十三批：发现配置字段大小写歧义拒绝

继续 ENT-009 的资产真实性检查。现有精确键存在性检查与 Go encoding/json 的
大小写折叠结构字段解码不一致：如 agents.List 可以被结构解码识别，但 list 缺省
检查又会生成默认 main，覆盖真实 roster。新增基于当前结构类型的字段拼写检查，
在结构解码前拒绝已识别字段的非规范大小写，包括 JSON5 转义键；错误统一为
openclaw_config_invalid，不返回部分候选、证据或声明权限。未知扩展字段保留兼容，
动态 entries 角色 ID 大小写不合并，不透明 model/skills 原始载荷不套用角色结构。
未增加配置执行、目录扫描或有效权限推导。

新增 11 组负向配置，覆盖根、roster、defaults、角色属性、大小写重复及转义键；
正向验证大小写不同角色 ID 独立、未知扩展保留、agentDir 合法混合大小写与不透明
model 不被误拒绝。OpenClaw go vet 与全量 go test -race -count=1 通过（2.530 秒）；
Edge 四包同样全量通过（主包 2.298 秒）。Windows/AMD64 和 macOS/ARM64 测试
交叉编译通过，产物 `/tmp/siq-openclaw-fieldcase-HqlyQ9`，不代表原生平台验收。
gofmt 与 git diff --check 通过。全部使用隔离配置夹具，未读取真实用户配置、上传、
提交、部署或发布；完整目标保持 active，ENT-009 未提前销项。

## 第七十四批：用户服务只读诊断入口

推进 ENT-005，增加 Linux user-service-status 与 enterprise-user-service-status/v1。
固定调用 /usr/bin/systemctl --user show，只读取既定 SIQ unit 的 LoadState、ActiveState、
UnitFileState，不接受任意单元/系统级/启动参数。20 秒超时、4096 字节输出上限，
stderr 不外传；缺失/重复/额外字段、管理器失败均返回固定错误，不伪造未运行状态。
未知属性值归一 unknown，避免诊断内容/路径外泄。不读取设备状态、私钥或真实配置。
JSON 明确心跳、发现及保护未由该命令核验，服务 active 不是业务闭环验收。

新增四组测试覆盖精确只读调用、多种状态、不存在的单元、未知值脱敏、非法/重复/
缺失/超限输出、管理器错误、取消、不允许参数和有界输出写入。Edge go vet 与全量
go test -race -count=1 四包通过（主包 2.092 秒），gofmt 与 git diff --check 通过。
测试注入服务管理器结果，未读取或操作本机实际 systemd 服务；不是原生登录/重启验收。
未修改外部分工的导航和权限页，未提交、部署或签发。完整生命周期升级恢复、真实首扫
和正式安装包仍待完成，目标继续 active。

## 第七十五批：真实子进程退出与崩溃恢复验证

继续 ENT-005。复核发现已有 TestServiceUnitSystemdSyntax 使用本机 systemd-analyze
离线解析生成单元，因此未重复添加同类检查。新增 Linux 进程级测试：测试可执行文件
的受控子进程调用实际 main→serve，临时私有身份只连接 httptest 回环控制面；验证
真实 HTTP 心跳与空任务领取、第二进程被内核锁拒绝、SIGTERM 优雅退出、再次启动、
SIGKILL 崩溃及第三次启动恢复。每次重启使用同一设备状态，前后字节不变；输出不含
模拟凭据或控制面地址。无已核验采集器时不广告能力，不发注册/首扫/上传请求。

测试无真实设备、无 systemd 启动、无用户目录扫描，不使用正式签名包。该证据证明
当前 Linux 原生进程/信号/文件锁层面的恢复，不证明 systemd 自动拉起、登录退出、
整机重启、离线回执或完整安装生命周期。每个子进程有 15 秒上限并清理自身进程。

Edge go vet 与全量 go test -race -count=1 四包通过，主包 4.396 秒，日志
`/tmp/siq-edge-process-lifecycle-tests.log`；gofmt 与 git diff --check 通过。
上批状态命令的 Windows/AMD64 与 macOS/ARM64 测试交叉编译也已通过，产物
`/tmp/siq-edge-status-cross-081hDv`，不当作原生平台执行证据。本批仅新增测试与记录，
未改变生产逻辑、未提交、未部署；ENT-005 和完整目标仍未完成。

## 第七十六批：安装确认展示目标设备来源证据

推进 ENT-004/006。查验主机探测仍仅为独立 inspect-host 命令，未与控制面设备字段
集成；本批先接入实际 Linux 交互安装确认流程，计划与终端校验后展示 OS、程序架构、
uname、发行版和固件/设备树型号来源。复用既有三个固定元数据路径及大小限制，
缺失/拒绝/异常与观察值分开，明确未认证硬件、未上传、名称不构成 DGX 证据，
不证明 GPU/OpenShell 或防护可用。不把报告放入注册、心跳或计划，未扩展上传授权。

摘要所有字段以转义文本输出，防止终端控制字符或伪造提示；输出失败停止确认。
非交互、review-only、帮助路径不新增探测。新增测试覆盖固定来源摘要、未选择字段
不泄露、权限不足、硬件证据边界、终端注入和输出失败。既有 PTY 安装测试继续通过。
Edge go vet 与全量 go test -race -count=1 四包通过，主包 4.346 秒，日志
`/tmp/siq-install-host-summary-tests.log`；gofmt 与 git diff --check 通过。

测试主要使用合成元数据，PTY 安装路径会读取固定本机公共 OS/硬件元数据；没有读取
用户配置或上传。此改动不代表企业控制面已展示硬件盘点，真实硬件/容器/OpenShell
拓扑关联仍待开发。未修改外部分工文件、未提交或部署，完整目标继续 active。

## 第七十七批：常驻启动身份读取保护

推进 ENT-005 的启动安全边界。原 LoadState 使用无界 os.ReadFile，未核对权限或链接；
Linux 新增逐级 descriptor-relative no-follow 打开，拒绝可被其他用户写入的祖先
（root-owned sticky 临时目录例外）、非私有最终目录、非当前用户文件、符号/硬链接、
FIFO/非普通文件和超限内容。读取前后核对修改元数据，拒绝深度超限、重复 JSON 键、
非 UTF-8 与尾随数据。安全检查在心跳/任务请求前完成；不自动修复、删除或替换身份。
LoadState 错误不打印路径/原始内容；缺失状态保留原未注册提示。非 Linux 文件读取
行为保留，未外推 Linux 权限保证。新增合同及 README 兼容性说明。

新增私有文件读回、缺失状态与相对目录拒绝，以及公开文件/目录、链接、FIFO、重复键、
超大文件八类负向测试。首轮暴露通用 canon.Decode 不拒绝重复键，改为专用有界 token
校验；后续发现两个旧成功夹具的父目录为 0775，改为显式私有目录以符合新不变量，
没有放宽生产门禁。注册恢复、范围确认和原生进程生命周期回归均通过。

Edge go vet 与全量 go test -race -count=1 四包通过，主包 4.351 秒，最终日志
`/tmp/siq-device-state-read-tests-r3.log`；gofmt、git diff --check 通过。全部操作在
测试临时目录，未读取真实设备身份、未修改生产目录权限、未提交或部署。完整目标
继续 active；此安全增量不等于安装/治理闭环交付完成。

## 第七十八批：发行签发输入与独立信封验签入口

推进 ENT-004 的受控发行交接。企业候选生成 publisher-signing-input.json，按正式
enterprise-release/v1 对除 signature 外的字段输出精确 sorted/compact ASCII JSON，
无尾随换行，固定历史发行公钥，绑定版本/提交/所有制品 pin。该文件纳入候选 ZIP 与
摘要，仍无 release.json、签名或安装授权。新增测试核对字节规范、字段集合、pin 和
源码身份，并锁定候选工具、Edge 与个人端使用同一原公钥。

Edge 新增 Linux verify-enterprise-release --release FILE，复用既有有界文件读取
和 production VerifyRelease，不要求设备状态、不支持公钥覆盖、不联网或执行制品。
成功报告明确只验证信封签名，磁盘制品和安装均 false；错误无部分成功输出。新增拒绝
未签名候选、伪造/畸形信封、超大文件、链接、公钥覆盖和额外参数测试，无设备状态写入。

发行工具全量 **27 passed**（2.381 秒），日志 `/tmp/siq-enterprise-signing-request-tests.log`；
本批 Python 文件 Ruff 通过。Edge go vet、全量 go test -race -count=1 四包通过，
主包 4.578 秒，日志 `/tmp/siq-enterprise-envelope-verifier-tests.log`；gofmt 与 diff 检查通过。
既有底层测试覆盖测试身份签名正向及生产根拒绝测试身份；本批没有官方签名成功样本，
不得声称正式签发验收通过。未生成/读取私钥、未签发、未签后组包、未提交或部署。
最终发行与真实安装闭环仍待完成，完整目标 active。

## 第七十九批：签后交付的全架构制品核验

推进 ENT-004。verify-enterprise-release 增加可选 --bundle，先固定原发行公钥验签，
再使用已有 descriptor/no-follow/大小/摘要/权限检查验证签名列表中的每个文件，
包括非本机架构与当前安装计划未选中的采集器。复用原文件验证逻辑，不构造虚拟安装
计划或绕过范围确认。全部通过才报告 artifact_bytes_verified=true，installed 仍 false；
没有 bundle 时保持原仅验签行为。无状态写入、制品执行或网络。

原十四类文件/路径安全用例扩展到全制品检查，并确认生产入口拒绝测试身份签名。
新增双架构、多采集器夹具，逐一破坏非选中架构 Edge、非选中架构 Connector 和同架构
未选中 Connector：计划选择检查可通过，但全发行检查必须拒绝。测试使用惰性文件及
隔离测试签名，不是官方发行正向验收。未给任何测试密钥提供生产 CLI 注入入口。

Edge go vet、全量 go test -race -count=1 四包通过，主包 4.484 秒，日志
`/tmp/siq-all-release-artifacts-tests.log`；gofmt、git diff --check 通过。报告只证明
签入文件的当时字节，不认证源码、未签说明/许可或未来执行；正式签发、签后组包及
实际安装仍待完成。未提交、部署或发布，完整目标 active。

## 第八十批：四入口导航交付独立复核与资产子页面修正

复核外部 Claude/Qwen 的 ENT-018 导航子任务。原 22 项模拟浏览器检查通过，
但独立复现发现技能清单及资产详情均没有资产入口高亮。修正 Layout 的资产链接匹配
与 enterpriseNav 纯函数，增加子页面唯一高亮、正确标题和相似前缀负向断言；
不修改路由、权限语义、后端接口或安全能力。遵循 React 技能直接派生路径归属。

全量 Web **71 文件 / 464 项通过**（导航 21 项），日志
`/tmp/siq-nav-review-web-tests.log`；独立目录构建通过，日志
`/tmp/siq-nav-codex-review-build-20260925.log`。隔离浏览器 **24/24 通过**，
最终报告及三张桌面/移动截图位于 `/tmp/siq-nav-codex-review-20260925-r3/`。
已实际检查截图，保留现有配色、字体、按钮、卡片及导航语言。截图仅禁用捕获时动画，
不改变产品样式或动画。git diff --check 通过。

浏览器使用模拟身份与 loopback mock，不是生产验收，不得发布其构建。
详细范围和限制见 `enterprise-navigation-four-entry-handoff.md` 第 8 节。
仅导航子任务已复核修正；关系树、批量权限及 ENT-018 其他事项仍待完成。
未提交、部署、签发或访问真实业务数据，完整目标 active。

## 第八十一批：企业签后组包工具与失败关闭验证

推进 ENT-004，完成 `scripts/release/enterprise_finalize.py` 与对应合同、测试和入口说明。
输入受控流程已签发的信封、候选目录、预期版本/完整源码提交，以及独立审阅的本机
Edge 验签器及其摘要；不从候选取验签器、不提供发行公钥替换或签发入口。
待签输入必须逐字节一致；先验证全部候选制品，复制时再检查大小/摘要，私有暂存
完成后二次验证，最后核对 ZIP 内容并写入全新外部目录。许可和说明不是签名认证事实，
输出明确 published=false、installed=false、installation_acceptance=not_run。

修复真实验签测试的夹具路径冲突：Go 明确拒绝把可执行文件覆盖到既有非目标文本文件；
改为独立新路径，不跳过真实验签。另补二次验证失败无输出、非零退出、报告重复键、
异常 JSON、身份/摘要不匹配、额外字段和布尔类型混淆负向用例。
组包机械流程正向使用 mock，不是官方签名成功；真实 native Edge 验证伪造信封被拒绝。

`python3 -m unittest discover -s scripts/release -p 'test_*.py' -v`：
**35 passed，2.571 秒**，日志 `/tmp/siq-enterprise-finalization-tests-r3.log`。
本批两个 Python 文件 Ruff 与 git diff --check 通过。输入父目录仍要求稳定可信，
不是防御同 UID/root 并发修改的沙箱；最终文件转移错误可留下不完整输出，合同已注明。

未读取私钥、未签发、未发布、未注册设备、未提交或部署。此工具不等于可下载 Skill
的一体化安装流程；官方签名正向、源码冻结、真实双架构安装和运行验收仍待完成。
完整 ENT-001–ENT-022 目标保持 active。

## 第八十二批：首扫失败与正常心跳退避解耦

推进 ENT-005/006。发现首扫申请错误原先直接返回心跳循环，导致已成功的心跳被一起
退避至最多 15 分钟，可超过前端 300 秒心跳过期阈值。现将首扫失败的重试时间保留在
单心跳协程内，30 秒起翻倍至 15 分钟，仅在已验证能力且心跳成功后到期重试；
正常心跳不因调度失败而退避，真实心跳错误仍使用原网络退避。首扫失败日志固定脱敏，
不置成功标记、不换原计划、不重新注册、不绕过服务端期限或设备级幂等。取消优先。

新增可控时钟测试覆盖 122 次正常心跳及首扫尝试 tick 0/1/3/7/15/31/61/91，验证
指数退避、15 分钟封顶和成功后的停止重复申请。既有心跳失败、能力失效、取消、
旧设备与首扫重试测试保留。此为隔离单元/HTTP 夹具证据，不是现场断网/systemd 验收；
首扫请求本身耗时仍受原 HTTP 超时约束，不宣称完全并行调度。

Edge `go vet ./...`、`go test -race -count=1 ./...` 四包通过，主包 4.155 秒，
日志 `/tmp/siq-initial-scan-heartbeat-isolation-tests.log`；gofmt 与 git diff --check 通过。
合同及 Edge README 已同步。未提交、部署、注册真实设备或扫描用户目录，整体目标 active。

## 第八十三批：用户服务安装的取消边界

推进 ENT-005 安装失败/中止恢复。install-user-service 原来在已经取消的上下文下仍可
创建任务锁等本地文件，activateUserUnit 也未显式防止取消后继续下一服务管理阶段。
现于锁操作前、单元写入前后、每次 manager 调用前后核对取消状态；退出不冒充配置或
启动成功。已写入单元、已发生的 enable/start 效果保留，不删除身份或自动回滚；
正在进行的文件写入仍可能完成，合同明确不是原子取消。

新增隔离测试证明：预先取消不创建状态目录或配置目录；在三个管理步骤任一步返回
成功的同时取消，后续调用均不发生且不报告成功。现有失败停止、独占写入、同内容
重试及不安全路径拒绝测试保留。没有调用本机 systemctl 或真实设备身份。

Edge go vet、全量 go test -race -count=1 四包通过，主包 4.108 秒，日志
`/tmp/siq-service-install-cancellation-tests.log`；gofmt、git diff --check 通过。
真实用户服务生命周期、升级替换、登录退出/重启仍待验收；未提交或部署，目标 active。

## 第八十四批：技能历史观察分页接口

推进 ENT-008/011 的历史版本可追溯。新增只读
GET /api/v1/skill-installations/{id}/observations，按时间与 ID 倒序分页，
复用既有观察字段投影；游标必须属于当前租户和当前安装记录。先定位后鉴权，
设备环境来源跨租户时拒绝，吊销设备历史仍可由有权用户读取。不回传路径、正文、
签名或凭据，不推断角色归属、当前安装或有效权限；不新增业务写操作。
合同见 enterprise-skill-history/v1；前端历史展开和精确角色关系尚未接通。

测试覆盖同时间分页、无重复/漏项、空历史、吊销保留、最小字段、权限拒绝、
跨安装游标与损坏跨租户来源拒绝、参数边界及读取不新增审计事件。
定向 9 项通过；后端全量 **1440 passed、1 skipped、1 warning，43.86 秒**，日志
`/tmp/siq-skill-history-api-full.log`。唯一跳过仍为缺少隔离 Go 批量线协议样本，
警告为既有 Starlette/httpx 弃用提示。全 app Ruff 与 git diff --check 通过。
验证使用测试数据库/合成上传，不是生产验收；未提交、部署或读取真实业务数据。
完整目标 active。

## 第八十五批：权限事实页面的实际容器响应式修正

独立复核 Kimi ENT-014-UI 后修正 768/1024px 内容区横向溢出：局部 CSS 容器查询
按实际可用宽度切换卡片，保留项目设计变量、文本语义和业务操作。无新增 React
状态、监听器或依赖。浏览器脚本同时检查 document 和内容滚动容器，防止页面级
宽度检查漏掉内部溢出；五个视口 375/768/1024/1280/1440px 均通过。

当前源码独立构建通过，Web **71 文件 / 464 项**；隔离浏览器 **16/16**，最终证据
`/tmp/siq-permission-responsive-evidence-20260925-r2/`，已实际查看列表位置截图。
构建 `/tmp/siq-permission-responsive-build-20260925`，日志
`/tmp/siq-permission-responsive-build.log`、`/tmp/siq-permission-responsive-tests.log`。
git diff --check 通过。详见权限 UI 交付记录第 12 节；共享 hook 重试错误残留仍待
独立修复，ENT-014 其他后端语义与批量治理未完成。未提交、部署或连接真实业务数据。

## 第八十六批：共享列表重试成功清除旧错误

独立处理 Kimi 第 9 节交接问题。useApiList 当前请求成功后清除 error，保留原序号
保护和失败路径；不新增状态或改变权限、样式、旧 rows 保留策略。浏览器新增成功
重试后 alert 为 0 的断言，在旧构建稳定失败（actual=1），新构建通过。

Web 全量 **71 文件 / 464 项**，独立构建通过；浏览器 **17/17**，五种视口及失败
保留数据检查继续通过，证据 `/tmp/siq-pagination-recovery-evidence-20260925/`。
旧失败日志 `/tmp/siq-pagination-error-before.log`，新测试与构建日志
`/tmp/siq-pagination-recovery-tests.log`、`/tmp/siq-pagination-recovery-build.log`。
git diff --check 通过。非生产 mock 验收；未提交、部署或触发真实业务写操作。
其他页面的 reload 期间旧数据展示仍需逐页复核，不宣称共享列表所有问题已解决。

## 第八十七批：技能历史观察前端接通

将第 84 批只读历史 API 接入企业 SkillsPage。新增 SkillHistory 与 skillHistory
客户端及测试，复用原技能观察校验；使用既有 card、btn 和原生 details，无新依赖或
全局样式变更。遵循 React 技能按需挂载稳定组件，关闭后忽略旧响应，再次展开重读。
分页错误保留历史并提示，401/403/404 清空历史；客户端校验安装身份、时间/ID 倒序、
游标边界、重复和异常字段。只读历史不证明当前安装、完整包、角色归属或有效权限。

Web **72 文件 / 477 项通过**，日志 `/tmp/siq-skill-history-web-tests.log`；独立构建
`/tmp/siq-skill-history-web-build-20260925` 通过，日志 `/tmp/siq-skill-history-web-build.log`。
技能清单浏览器脚本新增按需键盘展开、分页失败重试、权限拒绝清空检查，总 **9/9**，
证据 `/tmp/siq-skill-history-web-evidence-20260925/`。桌面与 375px 历史截图已实际查看，
继承现有设计语言，无内容区横向溢出。全 API mock，脚本拒绝非 GET，非生产验收。
git diff --check 通过。未修改分给 Qwen 的 OverviewPage，未提交或部署。
精确角色—技能归属及业务权限批量治理仍待完成，完整目标 active。

## 第八十八批：防攻击基线与真实批量线协议补验

对照本轮初始 source-baseline.json，限定防攻击核心目录 receipt/threat/rulepack/
grant/state/statefs/signing/intent/provenance/skillcontext/trustedcontext/runtimeauthz、
运行适配器和 API 规则数据。基线及当前源码集合均 **269 文件**，无新增、缺失或
摘要变化。此限定范围的一致性不是全部产品代码未变或真实防御效果已验收。

自建当前本机程序 `/tmp/siq-ent-wire-verifier-LIU3GP/agentshield`，运行已有
personal-console-smoke.py，使用一次性私有状态、回环服务及合成角色/授权，
原生浏览器 **6 项通过**；报告和三份实际请求/响应位于
`/tmp/siq-ent-isolated-wire-20260925/`，日志 `/tmp/siq-ent-isolated-wire-20260925.log`。
进程已停止，临时状态已清理；只分析仓库良性测试夹具，不操作用户真实授权。

以该目录 batch-contract-output.json 设置 SIQ_BATCH_WIRE_SAMPLE 后，后端全量
**1441 passed、0 skipped、1 warning，71.37 秒**，日志
`/tmp/siq-ent-full-api-with-wire-20260925.log`。此前跳过的实际 Go 线协议 schema
检查本批真正通过；警告仍为既有 Starlette/httpx 弃用提示。不把个人协议补验冒充
企业批量治理、原生宿主执行或正式签名发行验收。

`apps/agentshield` go vet 与 `go test -race -count=1 ./...` 已全部通过，
终端 session 26523 最终退出码 0，日志 `/tmp/siq-ent-security-regression-20260925.log`。
此前观察到长时测试仍运行，保持同一进程等待完成，没有因暂时无输出而重启测试。
未提交、部署、签发或变更真实业务权限，完整目标 active。

## 第八十九批：已批准变更的多目标只读预览

推进 ENT-015 预览基础。新增 POST /api/v1/deployment-previews/batch，限制 1–20 项，
拒绝重复变更/绑定和额外字段。每项复用原 _prepare/_snapshot，保留租户定位、权限、
独立审批、绑定来源、隔离和后端预检。任一失败整批拒绝，不返回部分成功；稳定排序
结果并绑定租户、操作者及类型计算快照摘要。不同投影指向同 backend/target 时拒绝。

明确 batch_submission_supported=false。本批不持久化批次、不部署、不批准或产生
权限变化；没有权限收窄/撤权转换、完整共享影响、期限、CAS/幂等提交或部分失败
恢复，不把该预览基础替代完整 ENT-015。合同见 enterprise-deployment-batch-preview/v1。

新增 3 项组合测试覆盖顺序稳定、操作者绑定、无部署/任务/审计写入、跨租户/权限
拒绝、未批准整批拒绝、数量/重复限制及投影目标冲突。测试发现数据库已有目标唯一
约束，保留该约束，用受控投影夹具测试批量附加防御，不构造违反约束的数据库记录。
首轮失败包括共享测试目标命名冲突，已改独立随机标识，不改变业务唯一性规则。

后端全量 **1444 passed、0 skipped、1 warning，58.64 秒**，日志
`/tmp/siq-batch-preview-api-full.log`，继续使用第 88 批隔离 Go 样本补验线协议。
全 app Ruff、git diff --check 通过。新批量测试使用 fake 开发后端，原单项 OpenShell
夹具回归保留；未连接真实 OpenShell、部署或变更业务权限，未提交，完整目标 active。

## 第九十批：批量预检整批租户定位前置

继续推进 ENT-015。原实现逐项定位与准备，可能在发现后续越租户/不存在引用前
就进入前项后端预检。新增整批前置定位：查询全部变更及其策略、环境和绑定，
按验证身份限定 tenant_id，缺失/越租户统一 404；全部定位成功才检查
policy:manage、policy:read、env:read。单项 _prepare 的原有复验与审批、隔离、
目标归属检查不变。本批没有新增提交入口，不把批次前置读取称为事务快照。

修改 deployment_preview.py、test_deployment_batch_preview.py 及批量预览合同。
新增 11 项参数化负向测试，覆盖缺失对象、越租户策略与三类直接引用、管理员/
viewer、输入反序；断言失败前没有调用任何 _prepare，且部署/任务/审计数不变。
原实现红灯已复现。测试中创建租户 B 绑定最初被正确拒绝，随后只为隔离夹具的
创建者提供所需角色，实际测试调用仍来自租户 A；未修改业务权限规则。

批量专项 14 项通过；单项预览/持久提交及当时批量测试共 38 项通过。
首次全量使用修正前夹具出现 3 failed、1452 passed；修正后全量 **1455 passed、
0 skipped、1 既有弃用 warning，57.27 秒**（终端 session 9028，退出码 0）。
命令：`SIQ_BATCH_WIRE_SAMPLE=/tmp/siq-ent-isolated-wire-20260925/batch-contract-output.json uv run pytest -o addopts='' -q -rs --tb=short`，
在 apps/control-api 执行，继续使用第 88 批隔离 Go 样本验证线协议。
全 app Ruff 与 git diff --check 通过。所有数据均为隔离测试；没有真实设备上传、
OpenShell 操作、生产部署、签发或提交。批量收窄/撤权、持久批次、期限、CAS、
幂等及部分失败恢复仍待实现，完整目标保持 active。

## 第九十一批：网络允许集合变化分类基础

推进 ENT-015 收窄/扩大分流前置语义。新增 network_change.py，对当前 L3/L4
写入器可表达的 endpoint × binary_path 允许集合区分 unchanged/narrowed/expanded/
mixed/unknown。忽略规则名称、重复和顺序，不猜测路径/域名别名；L7、IP、协议、
凭据改写或其他不支持的限制保持 unknown，不先丢字段再比较。输入条数、每规则
路径数与展开对数分别限制 256/128/4096；不能代表完整策略或独立 Skill 隔离。

OpenShell plan_change 从既有同一次 read_effective_policy 取得比较基线，新增内部
ChangePlan.network_change 并绑定到部署预览摘要；不增加后端读写次数，不改变已有
HTTP v1 响应结构。静态重建或缺少明确网络写入段时 unknown。未添加基于分类的审批
豁免、提交或生效状态。合同 enterprise-network-change-assessment.v1.md 明确边界。

新增 test_network_change.py。初次相关回归 56 项通过；加入实际解析 L7 限制的测试后
后端全量 **1482 passed、0 skipped、1 既有 warning，56.73 秒**（session 49054，
退出码 0）。命令沿用第 90 批含 SIQ_BATCH_WIRE_SAMPLE 的完整 pytest 命令。
全量运行期间补入非 ASCII 数字端口的 ValueError→unknown 处理和一个负向用例，
最终分类专项 **28 passed，0.04 秒**；最后这一增量未再次运行全量，不冒充全量已覆盖。
全 app Ruff、git diff --check 通过。单次读回、无写、输入不变、未知限制不降级、
空集合、路径子集、新增/移除混合和规模超限均有测试。

本批只是内部分类基础，尚无面向用户的批量收窄/撤权流程；持久批次、共享影响、
期限、CAS/幂等及逐项失败恢复仍需完成。未触碰外部分工的前端文件，未提交、
部署、签发或连接真实 OpenShell。完整目标保持 active。

## 第九十二批：持久批次预览草稿与到期读取

推进 ENT-015 刷新恢复及幂等基础。新增 POST /api/v1/deployment-batch-drafts 和
GET /api/v1/deployment-batch-drafts/{id}，合同 enterprise-batch-draft/v1。
首次生成沿用整批租户定位、权限、审批、绑定及目标预检；保存脱敏预览投影。
草稿记录及 deployment.batch_preview.create 审计同事务，不创建部署或 Edge 任务。
同租户/同请求键唯一；请求摘要绑定操作者、类型和按绑定排序的目标，反序重试复用。
同键冲突拒绝。GET 限定租户及原操作者，仍要求 policy:read 和 env:read。

期限从预检开始计算五分钟，读取即时判定 previewed/expired；重试不重跑后端、
不续期、不自动重新执行。submission_supported=false，未过期也不等于后端未漂移。
新增模型 DeploymentBatchDraft 与迁移 0024；空表可降级，有草稿时拒绝删除历史。
既有个人端和外部分工前端文件未修改。main.py 仅注册路由，models.py 增加独立表。

新增 test_deployment_batch_draft.py 四项 API 测试及 test_batch_draft_migration.py。
覆盖刷新/重复读取、到期边界、请求/操作者冲突、越租户、低权限、未知字段、
未审批整批拒绝、审计异常回滚、无部署/任务写入、唯一键/外键与历史降级保护。
隔离 SQLite 迁移夹具最初遗漏 tenant 必填字段而失败，补齐实际模型要求后专项
**5 passed，6.67 秒**。未弱化数据库约束。生产 PostgreSQL 并发竞争/进程中断
验收尚未进行；不能把唯一约束测试冒充真实多进程并发验收。

首次全量 1 failed、1487 passed（修正前迁移夹具）；修正后全量 **1488 passed、
0 skipped、1 既有 warning，62.05 秒**（session 66628，退出码 0）。命令为
`SIQ_BATCH_WIRE_SAMPLE=/tmp/siq-ent-isolated-wire-20260925/batch-contract-output.json uv run pytest -o addopts='' -q -rs --tb=short`，
工作目录 apps/control-api；同时覆盖上一批最后补入的异常端口处理。
全 app 及本迁移 Ruff、git diff --check 通过。所有迁移只在临时测试数据库执行，
未应用到真实服务。未提交、部署、上传、签发或更改真实业务权限。
批次预览草稿不是执行保留记录；权限收窄/撤权转换、共享影响、CAS 提交、执行
幂等与部分失败恢复仍待完成，完整目标保持 active。

## 第九十三批：持久草稿期限与后端快照复验

新增 POST /api/v1/deployment-batch-drafts/{id}/revalidate。复用草稿的租户/原操作者
定位与读取权限，另检查 policy:manage；客户端摘要必须匹配持久快照。目标仅从
存储的预览投影恢复，不接受客户端替换列表，再执行既有整批预检并比较摘要。
期限在后端预检前后都核对，避免慢请求跨过截止点仍报告成功。审批、隔离、绑定、
来源、后端身份及版本检查继续走原流程，没有新增审批豁免。

成功只返回原草稿，不覆盖内容、不续期、不写审计/部署/任务；过期、摘要改变、
绑定撤销或审批失效均拒绝。接口是当前状态核对，不是执行令牌，不宣称复验后的
竞态已经消除。后续提交必须在受控执行流程内再次复验，不能依赖客户端曾获成功。
修改 deployment_batch_draft.py 和草稿合同，新增 test_batch_draft_revalidate.py。

新专项 **7 passed，3.04 秒**，包含 unchanged、多项中的单项变化、期限前后检查、
操作者/租户/权限/请求字段拒绝、无后端调用的早期拒绝，以及 OpenShell StatefulRunner
模拟 revision 漂移导致整批拒绝且 set_calls=0。模拟读回不等于真实 OpenShell 验收。
新增 CLI 用例之前与原草稿相关回归共 10 项通过。全 app Ruff、git diff --check 通过。
后端全量 **1495 passed、0 skipped、1 既有 warning，64.84 秒**，session 19309
退出码 0；在 apps/control-api 使用第 92 批含 SIQ_BATCH_WIRE_SAMPLE 的完整命令。
未提交、部署、签发或修改真实业务权限；外部分工前端未动。
本批仍没有执行入口，批量收窄/撤权、共享影响、CAS 提交与部分失败恢复待完成。

## 第九十四批：复用新提交占位后的执行阶段

为 ENT-015 批量编排复用现有安全路径，提取 deployment_submission.py 内部
_execute_new_reservation。单项入口仅在本次新建占位及 deployment.reserve 审计
提交成功后调用；已存在请求仍直接返回持久结果，绝不进入该阶段。审批/绑定/目标
复验、摘要比较、失败同事务审计及未知结果保留行为不变。没有新增 HTTP 执行接口。
比较仍使用占位前已经与实际快照核对的请求摘要，不因提取依赖可重载的草稿状态。

该内部函数不是恢复/重试 API，后续批量编排不得从历史 pending 行重建调用。
持久唯一约束和既有公共入口幂等机制仍是防重复边界，不以进程内标志替代。
新增 test_submission_execution_stage.py 两项测试，分别覆盖正常执行及阶段入口
模拟进程丢失。另一事务在入口处验证占位和审计已提交；之后重复 POST、GET 及
新键重试均不重新进入执行阶段。测试故障为隔离异常注入，不声称真实服务崩溃验收。

新增与原持久提交相关测试 **12 passed，3.14 秒**；全 app Ruff、git diff --check
通过。后端全量 **1497 passed、0 skipped、1 既有 warning，67.43 秒**，session
9851 退出码 0；在 apps/control-api 使用第 92 批含 SIQ_BATCH_WIRE_SAMPLE 的完整
pytest 命令。未触碰外部分工前端、未提交、部署或变更真实业务权限。
本批是执行阶段复用准备，不代表批量执行、撤权转换或部分失败恢复已交付。

## 第九十五批：整批执行占位的原子事务层

新增内部 batch_reservation.reserve_batch，使用持久草稿归属、操作者及权限，
先复验全部目标与整批摘要，再同事务保存批次、各项 Deployment/DeploymentSubmission、
逐项 deployment.reserve 和批次 deployment.batch_reserve 审计。任一异常全部回滚。
期限在预检前、预检后、提交前检查。单项摘要计算提取为共用函数，不改变线协议。
首次成功才返回本进程新建项；已有批次只返回批次记录和空的新建列表，不能重建执行。

新增 DeploymentBatchReservation、迁移 0025 和内部合同 enterprise-batch-reservation/v1。
草稿至批次唯一；批次与草稿通过 tenant_id/draft_id 复合外键约束。已有变更至提交
唯一约束保留。迁移为草稿补 tenant_id/id 唯一约束；有执行占位时拒绝降级，既有
草稿保留。未修改已存在的 0024 迁移，不在真实数据库运行迁移。

新增 test_batch_reservation.py 六项服务测试，扩展 test_batch_draft_migration.py：
新建两项的增量为批次 1、提交 2、部署 2、Edge 任务 0、审计 3；全部为 pending，
没有调用后端 apply。三处审计分别注入失败均全回滚，到期回滚，越租户/操作者/
权限拒绝、单项未审批整批拒绝及过期后重试无新建执行项通过。迁移覆盖升级、空表
降级再升级、复合外键拒绝跨租户、草稿唯一及有历史拒绝降级。

服务与原单项提交相关回归 **16 passed，5.06 秒**；最终服务与迁移专项
**7 passed，6.84 秒**。全 app 与新迁移 Ruff、git diff --check 通过。后端全量
**1503 passed、0 skipped、1 既有 warning，69.45 秒**（session 51406）；使用第 92 批
含 SIQ_BATCH_WIRE_SAMPLE 的完整 pytest 命令。SQLite 隔离事务测试不替代生产
PostgreSQL 并发竞争和进程崩溃验收。
本层未注册 HTTP 执行入口，草稿 submission_supported=false 保持真实。用户可用
批量执行、逐项停止/查询/恢复、收窄/撤权转换与共享影响仍待实现。
未提交、部署、签发、上传或改变真实业务权限，完整目标保持 active。

## 第九十六批：批次逐项持久结果只读查询

新增 GET /api/v1/deployment-batch-drafts/{id}/reservation，由独立
deployment_batch_result.py 路由提供。复用原草稿租户定位、原操作者和读取权限，
不存在占位返回明确 404。读取不调用后端、不执行或重试，也不补写审计。

先核对批次 ID 列表的类型、数量、唯一性，再逐项校验提交/部署租户、变更、环境、
绑定、目标、预览摘要及操作者请求摘要，任何不一致拒绝整批，不返回部分成功。
存储投影或请求结构不符合模型时返回固定 409，不把解析详情输出给用户。
结果保留逐项 deployment_status，聚合优先级为 unconfirmed > needs_attention >
recorded；sent 不等于 effective，pending 不证明进程仍运行，也不是安全重试依据。
execution_supported=false，仍未开放执行入口；过期草稿可以查询历史占位。

新增 test_batch_result.py **13 项专项通过，4.57 秒**。覆盖状态组合、未知优先、
过期读取、重复读取无写、无预检、跨租户/操作者/权限拒绝、无占位、重复/错序/
缺失/跨租户引用、目标/预览摘要/操作者摘要不一致。状态组合使用隔离数据库模拟，
不是后端执行或真实防护效果验收。main.py 仅注册新路由，更新内部合同中的只读 API。

全 app Ruff、git diff --check 通过，后端全量 **1516 passed、0 skipped、1 既有
warning，71.25 秒**（session 53017，退出码 0），命令为第 92 批含
SIQ_BATCH_WIRE_SAMPLE 的完整 pytest 命令。未修改外部分工前端、
未提交、部署、签发或更改真实业务权限。批量执行编排、权限收窄/撤权、共享影响
和部分失败恢复仍待实现，完整目标保持 active。

## 第九十七批：内部逐项执行与停止边界

新增 batch_execution.execute_batch，衔接整批原子占位、既有单项执行阶段和逐项
结果查询。只执行本次 reserve_batch 新建项；已有占位没有 fresh 项，直接读取。
每项开始前检查草稿期限，并为单项阶段增加可选 deadline，在重新预检后再次检查。
普通单项 API 不传 deadline，原行为不变；审批、绑定、目标和摘要复验继续复用。

失败/结果不明/到期即停止后续项。只有本进程确定尚未进入执行的项能写入
failed/backend_mutated=false，状态及 deployment.fail 审计同事务；当前项若结果
不明，保留其持久未知状态。停止审计失败回滚标记并返回 batch_stop_unconfirmed，
后续读取仍显示 pending，绝不通过重试重新执行。此前已成功记录的项不自动回滚。

新增 test_batch_execution.py **6 项专项通过，3.15 秒**，包括两项执行仅一次、
首项结果不明停止后项、首项 sent 后第二项未知、开始前/预检后到期、停止审计失败。
使用 fake 后端创建任务与异常注入，不是生产 OpenShell 多目标验收。初次相关回归
出现 1 failed/14 passed：测试错误地把未知 verification=None 当作字典；改为明确
断言仍为 None，并增加后项未知用例，未修改业务状态来满足测试。

本层仍未注册 HTTP 执行入口，execution_supported/submission_supported=false 保持
真实；需要后续受控交互接入，不能把内部函数视为用户已经可批量操作。没有跨目标
外部原子性，不支持未知结果自动恢复；共享同一策略的多项批次与生产 PostgreSQL
并发/真实崩溃仍需专项验收，收窄/撤权转换、共享影响和可视化入口仍待完成。
全 app Ruff、git diff --check 通过，后端全量 **1522 passed、0 skipped、1 既有
warning，75.83 秒**（session 4573，退出码 0），使用第 92 批含 SIQ_BATCH_WIRE_SAMPLE
的完整 pytest 命令。未提交、部署、签发、
上传或改变真实业务权限，完整目标保持 active。

## 第九十八批：共享策略逐目标审批与漂移回归

新增 `test_batch_shared_policy.py` 三种隔离用例：两项共享同一 DesiredPolicy、各自独立审批时可依次提交；第一项之后策略内容变更或下一项审批被撤回，下一项必须拒绝。重复执行只读既有结果，不增加任务。均使用 fake 执行后端，不证明真实 OpenShell 多目标效果。

第一次后端全量为 1524 passed / 1 failed：新用例把模拟发布任务留在共享环境队列，影响既有注册测试的十项领取窗口。将新测试改为每用例自建独立环境，不修改生产领取限制、不删除队列或弱化原断言。共享策略与注册回归 10 项通过；后续全量 session 85031 退出 0：1525 passed、0 skipped、1 既有 warning，68.41 秒。命令沿用含 `SIQ_BATCH_WIRE_SAMPLE=/tmp/siq-ent-isolated-wire-20260925/batch-contract-output.json` 的完整 pytest；Ruff 与 diff 检查通过。

## 第九十九批：风险中心主线验收修复

外部交付 ENT-018-FINDINGS-UI 经独立复核，修复未知枚举原型属性导致 React 渲染异常，以及长标识/展开详情在 375px 内容区溢出。未修改风险处置 handler、后端、安全判断或共享样式。

全量前端 78 文件 / 524 项通过、标准构建通过；隔离浏览器 16/16（含权限拒绝、身份失败重试、五视口、三次拦截模拟处置请求）通过，四张截图实际查看。详见 `enterprise-finding-explorer-handoff.md` 第 10 节。未提交、未部署，不代表 ENT-018 整体或生产防御验收完成。

## 第一百批：企业总览主线复核

复核外部 ENT-018-OVERVIEW 交付并修复非对象成功响应处理：false/0/空字符串/数组返回错误及重试，不冒充成功统计；null 原由共享请求层拒绝，继续保留。追加 5 项负向组件测试及 5 项浏览器断言，未改变权限、路由、业务接口或前端风格。

全量 78 文件 / 529 项、总览专项 34 项、标准构建及 diff 检查通过。隔离浏览器最终 24/24（首次 null 文案断言不匹配，核对共享协议后修正测试预期）；四张截图实际查看。证据和限制见 `enterprise-overview-four-entry-handoff.md` 第 9 节。未提交、未部署；批量执行公开接口尚未新增，完整目标继续 active。

## 第一百零一批：批次显式执行 HTTP 接口

新增 POST `/api/v1/deployment-batch-drafts/{id}/execute` 及独立 `enterprise-batch-execution.v1.md` 合同。严格布尔确认、既有草稿摘要、验证身份构成入口；不接受客户端目标/租户覆盖，不创建或通过审批。整批预留及逐项执行沿用原安全检查；重复请求只读既有结果，未知项不恢复重放。响应保留逐项状态及 retry_executes=false，recorded/sent 不解释为 effective。旧 v1 草稿投影保持兼容，新客户端须显式集成执行协议。

新增 10 项 HTTP 回归全部通过：首次及过期重读、布尔确认、跨租户/操作者/权限、摘要与额外字段、未审批/到期、未知结果不重放、预留审计失败回滚及错误脱敏。后端全量 session 99265 退出 0：1535 passed、0 skipped、1 既有 warning，59.92 秒；沿用含 SIQ_BATCH_WIRE_SAMPLE 的完整命令。Ruff、git diff --check 通过。测试使用隔离数据库与 fake 执行后端，不是生产并发或真实 OpenShell 验收。

尚缺前端选择—影响预览—确认—逐项结果闭环、收窄/撤权转换与真实部署验收；未提交、未部署、未修改真实业务权限。Claude Code 的运行时绑定 UI 与 Kimi 审计 UI 保留独立修改边界。

## 第一百零二批：批次前端 API 与响应边界

新增 `apps/web/src/api/deploymentBatch.ts` 及 14 项专项测试：草稿创建/恢复/复验、显式执行、只读结果查询。校验 schema、字段集合、数量/唯一性、选择与预览对应、逐项摘要、结果顺序、批次身份以及聚合优先级。sent 保留为 sent，不升格 effective；超时不自动再发执行 POST，只有精确的 batch_reservation_not_found 返回空查询结果，其他 404/403/502 原样失败。

专项 14 项通过；后续 Kimi 线验收时全量 79 文件 / 543 项通过，标准构建 `/tmp/siq-kimi-review-standard-20260925` 通过。当前仅为 API 接入模块，未接通用户可操作的批量界面，不声明 ENT-015 完成。未提交或部署。

## 第一百零三批：权限事实未知枚举修复

修复已复现的原型属性名称计数错误与 React 渲染异常，新增 6 项负向测试先失败后
通过；全量 79 文件 / 549 项通过。权限页模拟浏览器 18/18 通过，零业务写，保持
原权限语义及样式。详见权限事实交付记录第 14 节。

本轮标准构建被并行策略组件未使用导入阻断，未修改其他开发者文件；浏览器使用
明确跳过 tsc 的临时模拟夹具，不能作为标准构建或发布通过证据。标准集成复跑待
策略组件收口，整体目标 active。未提交、未部署、未变更真实权限。

## 第一百零四批：变更中心批次选择、预览与结果恢复

新增 `components/batch-deployment/` 及 `batch-draft-browser-smoke.py`，在 ChangesPage
复用已有明确环境/绑定选择，给每条已批准变更加入独立目标，拒绝重复变更/绑定及
超过 20 项。用户触发草稿创建，响应丢失时相同选择保留幂等键；没有 effect 自动写入。
URL 仅保留 batch 标识，刷新重新检查验证身份并读取草稿和逐项结果，不缓存令牌。
按租户/操作者 key 重建组件，异步请求序号保护卸载及切换后的状态更新。

这是预览/查询切片：尚未展示完整共享影响及权限内容，因此没有执行按钮、不导入
executeBatchDraft。不得宣称批量权限治理完成。未知结果明确提示禁止盲目重试，
sent/pending 原样保留，结果链接进入原部署与审计页面。原单项部署/审批入口保留。
未来需补齐完整影响审阅、最终确认、执行与失败恢复交互，以及收窄/撤权转换。

新增选择/UUID 单测 4 项，与批次 API 共 18 项通过；全量 83 文件 / 568 项通过。
类型/标准构建仍只有并行 PolicyExplorerItem.tsx 未使用 modeLabel 的 TS6133 阻塞，
未修改其代码。浏览器以显式跳过 tsc 的 Vite 模拟构建运行，不是标准构建通过证据。
脚本只允许合成草稿 POST，验证两项明确选择、刷新恢复、未知结果、五视口、零执行
请求及无未捕获异常。禁用浏览器 randomUUID 仍通过，使用 getRandomValues 生成 v4
UUID，不使用 Math.random。该模拟不替代真实 Mac→Linux/IAM 联验。

最终结果及桌面/手机截图：`/tmp/siq-batch-panel-lan-evidence-20260925/`，两张已实际
查看；首次手机截图捕获侧栏断点动画中间态，脚本加入过渡等待并关闭截图动画后重拍。
临时服务已停止，模拟业务写仅草稿创建 1 次、执行 0 次。React 技能用于确保用户
操作写入留在 handler、派生选择不增设同步 effect。未改共享 CSS、未提交或部署。

## 第一百零五批：批次逐项已批准权限内容审阅

上一轮 Kimi 验收产生了可复现构建阻断与策略页错误缓存缺陷，属于有证据的进展；
本轮不覆盖其并行策略页，继续 ENT-015 的批量治理主线。新增
`batch-deployment/review.ts`、`review.test.ts`、`BatchItemReview.tsx`，接入批次面板。
按用户点击只读现有 change-review/v1，不调用审批或部署。核对变更 ID、策略名称、
版本、档位及 approved/emergency_applied 状态；拒绝隐藏或截断内容，重新读取先
清除旧内容。组件以变更和预览摘要隔离，卸载后拒绝异步结果写入。

所有 15 个已有审阅章节按纯文本及原生 details 展示，复用既有样式，仅增加局部
长文本换行。明确区分申请人的影响说明、策略 selector 与真实共享沙箱影响；本轮
没有后端完整共享对象快照或与执行摘要绑定的影响证明，因此仍无最终执行按钮。
不把版本字段相同解释为内容在执行时不变，不把审阅成功解释为独立 Skill 隔离。
后续必须补后端共享影响快照、摘要绑定/复验、最终执行确认及批量收窄/撤销链路。

验证：`npm test` 全量 84 文件 / 579 项通过，新增 11 项（含读取拒绝、版本/状态
变化、内容截断/隐藏）。初次测试有 1 项因 beforeEach 返回 mock 函数被当作 cleanup
执行而失败，改为无返回回调后通过，未放宽断言。标准
`npm run build -- --outDir /tmp/siq-batch-review-standard-20260925` 仍在并行
PolicyExplorerItem.tsx:7 的未使用 modeLabel 导入处 TS6133 失败，没有绕过后宣称成功。

浏览器专用构建显式跳过 tsc，VITE_DEV_MODE=true，不可发布：
`/tmp/siq-batch-review-mock-only-20260925`。用 batch-draft-browser-smoke.py 全合成
API 验证内容读取成功、版本变化、隐藏内容、403、XSS 纯文本、展开长内容的五视口
无溢出、查询恢复及未知结果。唯一模拟写仍是草稿创建 1 次，执行请求 0、页面异常 0。
结果与截图 `/tmp/siq-batch-review-evidence-20260925-r2/`，手机及桌面展开内容截图
已实际查看；临时服务已停止。git diff --check 通过。未提交、未部署、不涉及真实
业务权限或设备；ENT-015/M3 仍未完成。

## 第一百零六批：部署影响身份核对合同与 API

新增 `enterprise-deployment-impact.v1.md`、`routers/deployment_impact.py`、
`tests/test_deployment_impact.py`，main.py 仅增注册。前一批已落盘源码与验证证据，
属于实际进展；本批继续补 ENT-015 的影响审阅后端基础，未改并行前端文件。

检查模型后否定“查询同目标的多个绑定即可枚举共享关系”的初始假设：
RuntimeBinding 已有 tenant/backend/target 唯一约束，不能由一条绑定推断单对象独占。
新只读 POST /api/v1/deployment-preview/impact 复用完整部署预检及预览摘要，
先同租户定位与权限、再外部预检；额外要求现有 agent:read，输出已登记的绑定、
环境、资产及实例标识。结果明确 registered_binding_only、共享运行对象 unknown、
Skill 隔离 not_established、execution_confirmation_supported=false，不伪造全量影响。
impact_digest 绑定投影与验证身份，但不是执行授权，不更改旧执行合同。

新增 7 项真实 HTTP + 隔离 SQLite 测试，执行后端 fake。覆盖身份投影、稳定摘要、
重复查询无写、跨租户 404、权限不足且不探测后端、错误摘要/不同操作者 409、
客户端租户注入 422。初次使用了不存在的 asset:read 导致 3 项失败，按 security.py
现有 agent:read 修正后通过，未扩大角色权限。Ruff 两处行宽已修正。

验证命令（apps/control-api）：

```bash
uv run pytest app/tests/test_deployment_impact.py -q
uv run pytest app/tests/test_deployment_impact.py app/tests/test_deployment_preview.py app/tests/test_batch_execute_api.py -q
uv run ruff check app/routers/deployment_impact.py app/tests/test_deployment_impact.py
uv run pytest -q
SIQ_BATCH_WIRE_SAMPLE=/tmp/siq-ent-isolated-wire-20260925/batch-contract-output.json uv run pytest -o addopts='' -q app/tests/test_grant_batch_contract.py::test_batch_real_wire_outputs
```

专项 7 项通过，关联回归 34 项通过。后端全量 session 36626 退出 0，显示 1 项
wire 样本条件跳过；随后提供既有隔离 wire 样本单独补跑该项，1 passed。全量命令
双 quiet 未打印总数量，不沿用历史数字冒充本次计数。既有 httpx TestClient
弃用警告仍在。最终增强身份等值/重复读取断言后专项再次通过；git diff --check 通过。

没有前端接入、真实运行时占用采集、完整共享影响确认或新执行按钮，均仍需后续
完成；不证明生产 PostgreSQL 并发或真实 OpenShell 效果。未提交、未部署、未发布。

## 第一百零七批：批次影响身份前端接入

前一批已实现合同/API并验证，属于实际进展。本批新增
`apps/web/src/api/deploymentImpact.ts` 及 17 项测试，接入 BatchItemReview。
用户点击时并行读取已批准配置和只读影响 POST，任一失败不显示成功审阅；重新
读取先清空旧内容。原 effect 不发起影响请求，刷新批次不自动探测运行时。
严格校验响应字段、覆盖字面量、禁止执行标记、登记对象及完整预览字段一致性；
拒绝对象替换、摘要/版本/目标变化、异常隔离能力声明和未知字段，不自动重试。

界面展示登记资产/实例，明确“仅已登记绑定”“共享运行对象未知”“单个 Skill
独立隔离尚未建立证明，不能确认执行”。没有增加执行按钮或业务授权；当前读取
成功不是可执行确认。React 技能用于点击 handler 内 Promise.all 并行读，保留
按身份/预览隔离与卸载结果守卫；未改共享样式、策略页和运行时绑定页。

`npm test`：85 文件 / 596 项通过；新增模块专项 17 项通过，git diff --check
通过。标准 `npm run build -- --outDir /tmp/siq-batch-impact-standard-20260925`
仍因并行 PolicyExplorerItem.tsx:7 未使用 modeLabel 的 TS6133 失败，不伪称集成
构建完成。浏览器专用 Vite 构建跳过 tsc、启用模拟身份，仅用于隔离验收：
`/tmp/siq-batch-impact-mock-only-20260925`，不可发布。

`batch-draft-browser-smoke.py --web /tmp/siq-batch-impact-mock-only-20260925 --out /tmp/siq-batch-impact-evidence-20260925-r2`
通过，验证影响 403 拒绝、成功后再失败清除旧内容、无自动影响请求、已知身份与
未知覆盖文案、XSS纯文本、五视口展开无溢出及零页面异常。请求明确分类：草稿
模拟写 1 次、只读影响 POST 7 次、执行 0 次（不能把 POST 总数写为零）。
结果及桌面/手机影响区截图在 out 目录，两张已实际查看，保持当前配色及字体。
临时服务已停止；未提交、未部署，无真实设备或业务数据变更。

后续关键缺口仍为可信运行时占用/共享影响证据与执行时复验，以及完整批量收窄、
撤权、确认和执行恢复路径。此批不代表 ENT-015 或 M3 完成。

## 第一百零八批：网络允许项精确撤除规划

前一批影响身份前端已落盘并验证，属于实际进展。本轮核对适配器及目标归属模型：
现有 CLI 读回/归属校验不提供全量共享运行对象证明，不能通过 UI 推导或人工登记
上调为可确认执行。保持该门禁，同时实现任务书 ENT-015 优先要求的收窄/撤销规划。

新增内部合同 `enterprise-network-revoke-plan.v1.md`、纯函数
`app/network_revoke_plan.py` 和 `test_network_revoke_plan.py`。按精确 endpoint/
binary_path 选择删除允许对，保留其他权限字段和未选路径，跨重复规则彻底移除
同一允许对；最后一项撤除为显式 network=[]，不改为 None。函数不改原对象或状态、
版本、审批，不写库、不执行；异常使用固定错误码，不回显配置。

只接受现有验证器支持的 allow 词汇及既有规则预算，拒绝未知条件、deny、非法
端点/路径、超过 256 个选择、重复选择及不在基线的旧选择。复用已有变化判定再次
确认 narrowed；测试使用独立集合减法 oracle，穷举四个授权对的 15 个非空子集，
不是以实现的分类结果自证正确。深拷贝测试覆盖输出修改不污染原策略。

在 apps/control-api 执行：

```bash
uv run pytest -o addopts='' -q app/tests/test_network_revoke_plan.py app/tests/test_network_change.py app/tests/test_openshell_policy_operations.py
uv run ruff check app/network_revoke_plan.py app/tests/test_network_revoke_plan.py
```

59 passed，1 个既有 httpx 弃用 warning；新增模块 18 项。额外适配器测试使用
StatefulRunner 合成读回，确认空网络规则保留到编译制品、计划为 dynamic/narrowed、
revision=4、set_calls=0 且模拟后端状态不变，不等同真实网络阻断证据。
Ruff 和 git diff --check 通过；本轮为纯规划模块，未重跑后端全量或浏览器。

仍需接入新策略版本/变更申请、操作者及摘要绑定、共享影响确认、批量 UI 和原
审批/执行/读回链路；本函数尚未接入生产调用路径，不代表用户已可批量撤权。
未知共享影响仍不能跳过。未修改并行开发文件、未提交、未部署、未操作真实设备。

## 第一百零九批：撤除规划接入事务化新版本申请

前一批纯规划已验证，本轮将其接入实际 HTTP 申请流程，而非继续停留于只读展示。
新增合同 `enterprise-network-revoke-proposal.v1.md`、路由
`network_revoke_proposals.py` 和 11 项 HTTP 测试；main.py 仅新增该路由注册，保留
其他开发者的全部改动。GET 基线返回标识/版本/摘要，不输出原策略；POST 接受精确
允许项选择、基线摘要和 UUID 请求键，新建同名独立策略版本及 proposed/standard
变更，原策略、原档位、其他权限内容不改，不批准、不部署。

先同租户定位，后 policy:read/manage 与 change:propose；完整基线摘要绑定验证
操作者及类型。服务器派生租户作用域内部幂等键，请求摘要绑定操作者、来源、基线
和排序选择；同键同内容返回原申请，不同内容/身份 409。基线变化 409，非法选择
422。源行使用 FOR UPDATE，版本及请求键依赖数据库唯一约束，冲突回滚后仅匹配
原请求才复用；不能把 SQLite 成功宣称为 PostgreSQL 并发锁已验收。

策略、变更、两条审计与 outbox 同事务。测试在第二条审计故障时确认原策略保持、
新策略/变更/首条审计/outbox 全部回滚，返回固定 503 而非内部错误。申请成功只增
1 策略、1 变更、2 审计、1 outbox，Deployment/EdgeTask 均不增加；重复不新增，
提出者自批继续被原职责分离规则拒绝。跨租户同 UUID 不互相碰撞或泄漏对象。

验证（apps/control-api）：

```bash
uv run pytest -o addopts='' -q app/tests/test_network_revoke_proposals.py app/tests/test_network_revoke_plan.py
uv run ruff check app/routers/network_revoke_proposals.py app/tests/test_network_revoke_proposals.py
SIQ_BATCH_WIRE_SAMPLE=/tmp/siq-ent-isolated-wire-20260925/batch-contract-output.json uv run pytest -o addopts='' -q --tb=short
```

专项 29 passed（新申请 11 + 规划 18）。全量 session 55173 退出 0，1571 passed、
0 skipped、1 既有 httpx 弃用 warning，79.98 秒。Ruff 首次发现 zip 未声明 strict，
补 strict=True 后通过；git diff --check 通过。使用隔离 SQLite、合成身份/样本，
不涉及真实业务数据、审批人、网关或设备。

后续仍需前端选择与申请确认、完整共享影响及执行时复验、批次逐项状态联动和真实
生产形状验收。该接口尚未部署，源码就绪不代表用户当前页面已经可批量撤权。
未提交、未部署、未发布；保留既有防御与审批链，ENT-015/M3/整体目标仍未完成。

## 第一百一十批：可选权限快照与前端撤除申请

前一批已打通事务化申请，本轮增加同快照 network-revoke-options 只读端点与合同
补充，从受支持网络词汇生成去重排序选项和同一源策略的基线摘要。未知语义拒绝，
超过选项/字段预算、脱敏或截断时整份拒绝，不提供不完整成功列表。coverage 仅
代表此期望策略网络段，不代表运行时全部授权。新增后端 4 项测试，连同申请 11 项
共 15 passed；Ruff 初次导入顺序错误修正后通过，本轮未重跑后端全量。

新增 `api/networkRevoke.ts`、10 项客户端测试及 NetworkRevokePanel，接入已批准
批次审阅区。使用真实 ConsoleContext 的 manage_policy、propose_change、policies
访问能力逐项限制展示；后端权限仍是最终门禁。前端可筛选、多选当前结果、清空，
显示总选择和筛选外数量，提交前必须明确确认所有选中项。只创建新版本及待审批
申请，结果文字和链接不宣称已撤权。异常响应和越出快照的选择拒绝，不自动重试。

响应丢失后当前组件锁定选择，显式重试沿用同一 UUID、基线和选择。UUID 仅存组件
内存，不保存身份/令牌。限制：整页刷新/离开或父审阅重读会丢失本地未决请求状态，
尚需服务端请求恢复查询/页面恢复联动；不能声称完成跨刷新故障恢复。入口目前在
批次审阅内部，权限主入口的直接选择流程与跨策略批量申请仍待整合。

`npm test` 最终 86 文件 / 606 项通过。标准 build 仍受并行策略组件 modeLabel
未使用导入 TS6133 阻断，未修改其文件；不可把 Vite-only 模拟构建描述为标准构建。
浏览器专用构建 `/tmp/siq-revoke-ui-styled-mock-only-20260925`，VITE_DEV_MODE=true、
显式跳过 tsc，不可发布。batch-draft-browser-smoke.py 全合成响应验收通过：无确认
禁提交、筛选外选择保留、键盘 Space/Enter、丢响应锁定并同请求重试、无提出权限
不显示入口、五视口无溢出。仅模拟草稿写 1 次、申请尝试 2 次，另有只读影响 POST；
执行请求为 0，无页面未捕获异常，临时服务已停止。

截图初查发现搜索框使用浏览器默认样式，已补专用局部类复用现有颜色、边框、圆角
和焦点样式，未修改共享 CSS。最终结果/截图
`/tmp/siq-revoke-ui-styled-evidence-20260925/`；375/1280 选中确认界面截图已实际
查看。React 技能用于点击 handler 内请求、原生表单和卸载结果守卫，无 effect 写。
git diff --check 通过。未提交、未部署，不改变真实业务权限，整体目标继续进行。

## 第一百一十一批：撤除申请跨刷新只读恢复

前一批申请 UI 已完成专项验证，本批补其明确记录的响应丢失/刷新缺口。新 GET
network-revoke-proposals/{request_key} 按租户内部键、原提出者 ID/类型、来源策略
和新策略同租户关系定位；不存在、跨租户、非原身份及缺少身份类型的历史记录统一
404，定位后复验 policy:read/manage、change:propose。新申请 impact 存服务端派生
proposal_actor_type；不从请求键推导权限、不回填猜测历史类型。

恢复响应独立使用 enterprise-network-revoke-recovery/v1，返回当前 change_status
和 lookup_executed=false。后者只说明查询没有执行行为，不能表示历史申请从未执行。
原申请界面的“尚未执行”也改为“本次未执行，请核对当前审批与部署状态”，避免
幂等重读一个已推进的申请时错误展示历史状态。接口及合同不改变原独立审批链。

前端提交前将非秘密 revoke_policy/revoke_request 标识放入地址栏；ChangesPage
独立恢复区以验证租户/操作者和参数为 key，刷新与点击重查只 GET。正文、令牌、
身份和选择不落浏览器存储。请求未核对时其他面板不能覆盖原恢复标识另建申请。
404/断网/权限失败统一提示结果待核对，不按“没查到”自动重建或重放 POST。
当前组件内仍可原键同输入重试；整页丢失请求正文后只恢复已经持久化的记录，不能
自动补交尚未到达的申请。多标签跨请求协调、显式结束未决恢复仍需后续完善。

验证：后端新增恢复 9 项，与申请/选项共 24 passed；覆盖重复查询无状态/审计/
outbox/部署写、当前 failed 状态、租户/身份/类型/失权、错误键/来源、旧记录缺字段、
新策略引用越租户。Ruff 通过，本轮未重跑后端全量。Web 新增 5 项恢复客户端测试，
全量 86 文件 / 611 项通过。标准构建仍因并行策略组件未使用 modeLabel 导入
TS6133 失败，不声明集成构建成功。

浏览器专用 Vite-only 开发身份构建 `/tmp/siq-revoke-recovery-final-mock-20260925`，
不可发布；batch-draft-browser-smoke.py 全 fixture 通过。刷新/重查显示当前 failed
记录，无重放 POST，恢复期间另建入口禁用，无提出权限隐藏；原选择、键盘、未知
结果和五视口回归仍通过。唯一模拟写为 1 草稿、2 同申请提交尝试（首次丢响应），
执行 0、页面异常 0；影响 POST 为只读预检另计。临时服务已停止。

最终证据 `/tmp/siq-revoke-recovery-evidence-20260925/`，375/1280 恢复区截图已实际
查看，沿用既有 card/按钮/配色。React 技能用于恢复 effect 仅只读、身份 key 隔离
及过期响应清理，申请写仍由点击 handler 发起。git diff --check 通过，未提交、
未部署，无真实业务权限变化；全量共享影响及完整批量治理仍待完成。

## 第一百一十二批：权限主入口撤除申请与选择歧义防护

补齐此前已写入工作树但尚未记账的权限主入口：PermissionsPage 接入
NetworkPolicyGovernance，用户明确展开后才 GET 策略列表，默认不选策略；搜索
保留筛选外的已选版本，列表加载失败与空列表分开。真实 ConsoleContext 的权限页、
策略页访问及 manage_policy/propose_change 四项能力全部满足才显示；身份切换以
租户/操作者类型/ID 重置。原同步、漂移、Diff 操作不变，未修改 Kimi 策略页文件。

复用 NetworkRevokePanel 的多选、确认、同键重试与 URL 只读恢复；只提出期望策略
的新版本申请，不执行撤权。策略清单明确为组织范围，不随上方环境选择自动缩小。
新增 policyChoices 纯函数与局部样式，沿用现有设计变量、不改共享 CSS 或依赖。
本轮发现去重保留首条会让重复 ID 的版本标签产生歧义，新增反例先得到 3 failed /
2 passed，再改为计数后排除该 ID 的全部记录；即使另一条格式错误也不信任首条。
最终选择函数 5 项通过。React 技能指导保持筛选与校验为纯派生，不新增同步 effect。

验证：Web `npm test` 87 文件 / 616 项通过。后端全量使用既有合成 wire 样本：

```bash
# apps/control-api
SIQ_BATCH_WIRE_SAMPLE=/tmp/siq-ent-isolated-wire-20260925/batch-contract-output.json uv run pytest -o addopts='' -q --tb=short
```

实际 1584 passed，1 条既有 Starlette/httpx 弃用提示，80.41 秒；隔离数据库/合成
身份，无真实业务操作。标准 Web 构建再次实跑仍被 PolicyExplorerItem.tsx:7 的
modeLabel 未使用导入 TS6133 阻断，不记为通过，不覆盖并行开发文件。

浏览器采用独立 Vite-only 开发身份构建（跳过 tsc，仅模拟、不可发布）：

```bash
# apps/web
env -u VITE_APP -u SIQ_AS_WEB_BASE VITE_DEV_MODE=true VITE_DEMO_PLACEHOLDERS=false ./node_modules/.bin/vite build --outDir /tmp/siq-governance-duplicate-mock-only-20260925
# 仓库根目录
python3 scripts/enterprise-experience/batch-draft-browser-smoke.py --web /tmp/siq-governance-duplicate-mock-only-20260925 --out /tmp/siq-governance-duplicate-final-evidence-20260925
```

通过：无权限隐藏且不读取策略、展开后失败重试、默认无选择、重复 ID 全部不可选、
筛选外选择保留、多选确认、直接权限页申请、刷新只读恢复，以及原批次/丢响应重试
回归。五视口同时检查文档与内容区无溢出。模拟写共 4 次（草稿 1、同申请尝试 2、
权限页申请 1）；另有只读影响 POST 9 次，执行请求 0、未捕获异常 0，临时服务停止。
截图检查曾发现空权限列表夹具缺少 JSON 响应头，修正夹具并重跑通过，未放宽客户端
协议校验。最终目录内 permissions-governance-375/1280.png 均实际查看，沿用米白、
墨蓝、金色样式；report.json 为此次模拟证据。

未提交、未部署、未发布。跨策略批量申请、完整共享运行影响、真实执行及生产形状
验收仍未完成；ENT-015/M3 及整体持续目标保持进行中。

## 第一百一十三批：撤除申请到独立审批及部署记录的跨接口回归

上轮为实现与验证进展。本轮检查权限页的申请结果链接：ChangesPage 已读取 change
查询参数并打开对应 ChangeReviewDialog，无需新增替代路由。补充之前各端点单独
测试未直接覆盖的组合链路，新文件 `app/tests/test_network_revoke_lifecycle.py`。

测试以隔离 SQLite、开发身份与 fake 后端为边界，真实调用本应用的 TestClient
HTTP 路由/权限判断/事务，不 mock 审批、摘要校验或数据库写入。先经 API 创建
绑定和源策略，再通过 network-revoke-options 获取选项、创建撤除新版本；提出者
自批 409、未审批预览 409、跨租户读取审批 404。独立 reviewer 经 review-decision
审批后，预览保持零写；deployment-submissions 创建一个部署和一个 EdgeTask，
同键重复返回原结果且不重复写。execution 与原请求恢复查询关联同一变更/部署；
源策略网络段不变、新版本为显式空允许列表；审批审计保留 review_digest。

第二条测试覆盖独立审批和预览完成后，新策略网络内容被改动：持久化部署提交 409，
部署/任务/审计数量不增加。没有放宽职责分离、摘要复验或审计门禁。首次测试因
错误假设策略创建响应含 network 正文而失败；修正为读取数据库的原策略快照后
比较，不修改 API 投影，也不删掉源策略不可变断言。

验证（apps/control-api）：

```bash
uv run pytest -o addopts='' -q app/tests/test_network_revoke_lifecycle.py app/tests/test_network_revoke_proposals.py app/tests/test_network_revoke_recovery.py app/tests/test_network_revoke_options.py app/tests/test_change_review.py app/tests/test_deployment_preview.py app/tests/test_deployment_submission.py --tb=short
uv run ruff check app/tests/test_network_revoke_lifecycle.py
```

68 passed（含本轮新增 2 项），1 条既有 Starlette/httpx 弃用 warning，8.98 秒；
Ruff 与 git diff --check 通过。本轮只新增测试和本记录，未修改前后端实现或并行
开发文件；未重跑全量，前一批全量结果保留其原范围。

证据限制：fake 后端只得到 sent，不是 effective；未注册真实设备、未执行真实
OpenShell 策略、未证明生产 IAM/PostgreSQL 或行为阻断效果。测试锁定不会从申请
和发送成功推导撤权生效；完整共享影响与真实部署仍待后续。未提交、未部署、未
签发发布，ENT-015/M3 和完整目标仍未完成。

## 第一百一十四批：跨策略原子撤除申请后端

新增合同 `enterprise-network-revoke-batch.v1.md` 与路由
`app/routers/network_revoke_batches.py`，main.py 仅增其导入/注册，保留此前未提交
路由改动。POST /api/v1/network-revoke-batches 接受 1–20 个唯一源策略与各自基线
及选择，全批最多 512 对；同名策略多个版本拒绝，防止一次生成互相冲突的继承版本。
全部对象先按验证租户定位，再检查 read/manage/propose；按源 ID 排序行锁。每项
仍为独立 proposed/standard 变更，绝不代批或执行。

从原单策略路由提取 stage_proposal：保留基线复验、纯撤除规划、静态验证、新版本、
两条审计和 outbox，但由调用方持有提交边界。单策略请求仍自行提交，批量把全部
条目放在一个事务，任意中途验证或审计失败整批回滚。原单策略失败/重试/恢复及
审批部署回归全部保留并运行。

批次内部键用 nrb 独立命名空间、验证租户、UUID 与规范排序序号生成；摘要绑定
整批源策略/基线/选择和原身份类型。序号键确保同 UUID 即使替换全部策略仍冲突，
而不是误建新批次。完整重排重试只返回原记录，无新写；缺少部分原子记录拒绝而
不自动补写。不同租户同 UUID 独立。唯一约束冲突回滚后只接受完整匹配幂等结果。

新增 `test_network_revoke_batches.py` 18 项：正常两策略精确计数增量
2 策略/2 变更/4 审计/2 outbox/0 部署/0 任务；源策略不变、最后允许项删除为 []、
每项自批拒绝；后项基线/选择失败整批回滚；跨租户、失权、重复、额外字段、空批、
条数/总选择预算；同键换身份/子集/全部策略/选择冲突；第二项审计异常全回滚并
原键重试成功；同名不同版本拒绝；测试库故障注入缺少原变更后拒绝补写。

验证（apps/control-api）：

```bash
uv run pytest -o addopts='' -q app/tests/test_network_revoke_batches.py --tb=short
uv run ruff check app/routers/network_revoke_batches.py app/routers/network_revoke_proposals.py app/tests/test_network_revoke_batches.py
SIQ_BATCH_WIRE_SAMPLE=/tmp/siq-ent-isolated-wire-20260925/batch-contract-output.json uv run pytest -o addopts='' -q --tb=short
```

专项 18 passed；Ruff 通过；最终全量 1604 passed，1 条既有 httpx 弃用 warning，
76.20 秒；git diff --check 通过。隔离 SQLite、合成身份，无真实业务调用或设备。
未修改 Web，本轮不新增其构建结论；前一批 Kimi 策略页构建阻断仍需其收口。

限制：尚无批量请求的无正文恢复 GET 和多策略前端入口，保留完整请求才可用原键
幂等重试；不得超时自动生成新请求。未验证生产 PostgreSQL 并发锁或真实 OpenShell
效果。后续补恢复与前端后，仍需完整共享影响和部署验证。未提交、未部署、未发布，
ENT-015/M3 与整个目标保持进行中。

## 第一百一十五批：跨刷新批次只读恢复

在前批原子申请合同补充 GET /api/v1/network-revoke-batches/{request_key}，并实现
新申请在各子变更 impact 同事务保存 batch_manifest（版本、规范排序源策略 ID、
整批摘要）。不保存选择正文，不增加浏览器存储或独立状态表；原申请事务与审计/
outbox 同成同败。历史无 manifest 不猜测、回填或自动迁移，返回 404。

恢复以租户和原操作者定位首项，严格验证 manifest 数量/排序/唯一/字段，再按各
序号内部键检查全部子变更的租户、操作者 ID/类型、来源、manifest 和绑定摘要。
源/新策略均须仍在同租户且不是同一对象。任何缺失或不一致统一 404，不泄漏部分
记录；完整对象定位后核对 read/manage/propose 权限，失权 403。响应 no-store、
逐项当前 change_status 与 lookup_executed=false，不表示历史未执行或已经撤权。
查询不补写、不重放、不批准；404 不能作为另建请求的依据。

新增 test_network_revoke_batch_recovery.py 16 项：重复查询无全部六类计数变化，
不同子项状态、无原选择正文；跨租户/操作者/身份类型、权限、错误键、缺历史清单、
子项身份不匹配、子项缺失、新策略越租户、来源/manifest/摘要异常、超量清单拒绝。
通过真实本应用 review-decision 审批其中一项后，恢复得到 approved/proposed，
另一项不会因同属批次被批准。仅 fixture 数据库注入异常，不操作真实业务数据。

验证（apps/control-api）：

```bash
uv run pytest -o addopts='' -q app/tests/test_network_revoke_batch_recovery.py app/tests/test_network_revoke_batches.py app/tests/test_network_revoke_lifecycle.py app/tests/test_network_revoke_proposals.py app/tests/test_network_revoke_recovery.py app/tests/test_change_review.py --tb=short
uv run ruff check app/routers/network_revoke_batches.py app/tests/test_network_revoke_batch_recovery.py
```

71 passed，1 条既有 Starlette/httpx 弃用 warning，6.56 秒；Ruff 首次发现测试长行，
拆分后通过，git diff --check 通过。本轮未重跑后端全量，也未修改 Web；前一批
1604 项全量结果不冒充新增恢复接口的全量验收。

后续仍需跨策略前端多选、确认、逐项状态和 URL 恢复接入，真实共享影响/部署验证
未完成。无生产身份、PostgreSQL 或 OpenShell 效果证明。未提交、未部署、未发布，
持续目标保持进行中。

## 第一百一十六批：批量申请与恢复的严格前端客户端

新增 `apps/web/src/api/networkRevokeBatch.ts` 与对应测试，为后续多策略 UI 提供
申请构造、完整结果核对及只读恢复。提交前验证 UUID 精确长度/格式、1–20 个唯一
源策略、各自快照摘要/格式、选择属于对应快照、每项 1–256/全批最多 512 对，重用
既有网络选项严格解析。构造新对象且只投影合同字段，不携带身份或修改原选择。

申请只显式 POST 一次，超时不自动重试、不降级为逐项写。响应逐项核对源策略集合
完整且无重复，新策略/变更 ID 唯一、新策略不等于任何源策略；整批和每项均须
requires_independent_approval=true、executed=false，缺项、外来项、额外字段均
视为结果待核对。恢复仅 GET，验证 1–20 项唯一身份、完整严格字段及非空限长状态，
不从 approved 或其它状态推导真实撤权效果。没有 localStorage/sessionStorage。

客户端新增 30 项测试：精确载荷、不修改输入、无效 UUID（含尾随换行）、各类预算/
选择/快照错误在网络调用前拒绝，20 策略与 512 选择边界可接受，完整映射、重复/
缺项/外来/复用 ID/执行标记异常拒绝，丢响应仅一次写，GET 独立状态与异常拒绝。
本轮只新增 API 客户端及测试，尚未接入多策略 UI，不声称页面功能交付。

验证（apps/web）：

```bash
npm test -- src/api/networkRevokeBatch.test.ts src/api/networkRevoke.test.ts
npm test
env -u VITE_APP -u SIQ_AS_WEB_BASE VITE_DEV_MODE=false VITE_DEMO_PLACEHOLDERS=false npm run build -- --outDir /tmp/siq-batch-client-standard-20260925
```

专项 2 文件/45 项通过。全量实际为 89 文件通过、1 文件失败；670 项通过、3 项
失败，失败均在并行新增 RuntimeBindingItem.test.tsx：attestation 字样、已验证/
已保护字样、非 active 操作断言。前两项当前组件含否定说明文字，不能只据子串命中
判为数据泄露或错误安全声明；第三项仍需该开发线核对组件与页面回调职责和按钮
断言，未擅自删测或改其实现。

标准构建失败：PolicyExplorerItem.tsx:7 的 modeLabel 与新并行
RuntimeBindingsPage.tsx:29 的 hasActiveBindingFilters 均为未使用导入 TS6133。
本轮未修改这些文件，未以专项通过替代集成通过。git diff --check 通过；无 UI 改动，
未运行浏览器。本测试使用 mock 客户端，仅证明前端合同处理，不证明生产后端权限。
未提交、未部署，批量 UI、生产形状与完整目标继续推进。

## 第一百一十七批：权限页跨策略多选与恢复 UI

新增 NetworkBatchRevoke.tsx（含独立只读恢复区）与 4 项 SSR 测试；在原
NetworkPolicyGovernance 的显式展开区增加单策略/跨策略切换，保留原流程。跨策略
可筛选和勾选已加载策略，筛选外数量可见；明确 20 策略/512 允许项上限，不允许
同名多版本。用户点击后并行读取全部快照、核对版本，任一失败不保留部分成功。
每份策略可逐项/全选/清空允许项；确认覆盖所有已选策略与筛选外选择，不立即撤权。

提出前把非秘密 revoke_batch UUID 留在 URL，不保存身份、正文或令牌。响应丢失
锁定全部选择，只能原键同正文手动重试；刷新只 GET 完整批次，显示各项当前状态
及独立变更链接。单申请/批次恢复标识互斥阻止另建；模式切换与分页也在未决时禁用。
顶部现有 ConsoleContext 四项真实能力门禁及租户/身份 key 不变。未改业务审批、
权限判断、后端或任何并行绑定/策略文件。

React 技能用于明确点击 handler 写请求、最多 20 项独立只读 Promise.all、卸载结果
守卫和只读恢复 effect；不以 effect 提交申请。局部 CSS 复用现有颜色、按钮、焦点
和输入框，fieldset 最小宽度/长 ID 换行，不改共享 CSS 或依赖。

验证：新客户端+组件专项 `npm test -- src/api/networkRevokeBatch.test.ts
src/components/batch-deployment/NetworkBatchRevoke.test.tsx` 为 34 passed。组件测试
首次误断言加载前尚未渲染的确认文案，改为验证初始可见的“不立即撤权”声明后通过；
保留初始零选择、文本转义、恢复锁定及不写请求断言。

全量测试本轮实跑 91 文件中 89 passed/2 failed、672 passed/15 failed（运行于并行
绑定页面继续写入期间，且早于新增 4 项组件测试），失败位于 RuntimeBindingsPage
和 RuntimeBindingItem，不冒充最终集成通过。标准 build 本轮不再出现策略组件
modeLabel 错误，但绑定页面未使用导入、绑定测试参数/未使用变量共 7 个 TS 错误，
尚未通过；没有覆盖其他开发者文件。

浏览器模拟专用构建 `/tmp/siq-network-batch-ui-mock-only-20260925` 使用
VITE_DEV_MODE=true 的 Vite-only（跳过 tsc，不可发布）。命令：

```bash
python3 scripts/enterprise-experience/batch-draft-browser-smoke.py --web /tmp/siq-network-batch-ui-mock-only-20260925 --out /tmp/siq-network-batch-ui-evidence-final-20260925
```

原批次/单策略回归及新增跨策略链路通过：键盘切换、筛选外保留、一项读取失败全
快照清空、重试读取、确认前禁提交、三项汇总、丢响应锁定、同键同正文重试、刷新
只读恢复 approved/proposed 独立状态、未决切换禁用。五视口文档/内容区均无溢出。
第一次浏览器断言错误地把 fieldset 当可操作元素检查禁用，尽管已有 disabled
属性仍被 Playwright 判 enabled；改为检查其实际复选框禁用后通过，未改产品保护。

共 6 次模拟写（原草稿 1、原同申请 2、权限页单申请 1、新同批申请 2），另有
9 次只读影响 POST；真实业务写/执行请求 0、页面异常 0，临时服务停止。最终
report.json 与 network-batch-375/1280.png 在上述目录；两张截图实际查看，保持
米白/墨蓝/金色风格，移动长内容正常纵向滚动。git diff --check 通过。

仅证明隔离 mock UI 与客户端，不证明真实 IAM、OpenShell 或撤权生效。多策略 UI
源码已接通，仍需集成构建收口、真实共享影响及实际审批部署回读。未提交、未部署、
未签发发布，ENT-015/M3 与整体目标未完成。

## 第一百一十八批：后端原始响应与前端解析器联测

新增 test_network_revoke_wire.py，经隔离 TestClient 的实际路由创建批次、独立审批
其中一项、只读恢复；原样导出申请与恢复 JSON、合成源 ID 和请求 UUID。不导出
身份头、选择正文或任何真实配置，查询前后六类计数不变。默认输出在测试 tmp_path，
显式 SIQ_REVOKE_BATCH_WIRE_OUTPUT 可指定合成证据位置，以独占创建拒绝覆盖旧文件。

新增 apps/web/dev/revoke-batch-wire.config.ts 与 revoke-batch-wire.check.ts，独立
配置运行，不改变普通单测 glob、依赖或锁文件。读取上述原始 JSON 交给正式客户端
解析器，核对两个源/新策略/变更 ID 一致，以及 approved/proposed 独立状态；只 mock
GET 传输以承载实际生产者响应，不另手写响应夹具，不发任何 POST。未指定证据路径
时明确失败而非跳过。证明跨语言合同兼容，不证明生产网络、身份或运行时效果。

本次实际命令（分别在 apps/control-api 与 apps/web）：

```bash
SIQ_REVOKE_BATCH_WIRE_OUTPUT=/tmp/siq-revoke-batch-wire-20260925-2120.json uv run pytest -o addopts='' -q app/tests/test_network_revoke_wire.py --tb=short
SIQ_REVOKE_BATCH_WIRE_OUTPUT=/tmp/siq-revoke-batch-wire-20260925-2120.json ./node_modules/.bin/vitest run --config dev/revoke-batch-wire.config.ts
```

生产者 1 passed、消费者 1 passed。复跑应换新的临时文件路径（文件独占创建）；
本次证据 SHA256 为 22e61e0bacb551fef8683fbecf5c2331a39823977e24a3d32c06e2f2549a5a45。
只包含合成数据，/tmp 可能被系统清理。

后端全量再次执行：

```bash
SIQ_BATCH_WIRE_SAMPLE=/tmp/siq-ent-isolated-wire-20260925/batch-contract-output.json uv run pytest -o addopts='' -q --tb=short
uv run ruff check app/tests/test_network_revoke_wire.py
```

1621 passed，1 条既有 Starlette/httpx 弃用 warning，79.11 秒；覆盖新增批量恢复与
原有安全/事务测试。Ruff、git diff --check 通过。未改 Web 产品实现，本轮未重跑
前端全量或标准构建，不覆盖前批并行绑定开发的集成阻断结论。无真实设备/业务数据
调用，未提交、未部署、未签发发布；完整目标继续进行。

## Batch 119 — 策略中心复核与批量选择恢复操作

上一轮为有效进展：策略中心新增“分页失败后创建成功刷新”的负向回归，修复重复缓存错误状态；详细证据见 `enterprise-policy-explorer-handoff.md` 第 13 节。

本轮推进 ENT-018 批量交互：`NetworkBatchRevoke.tsx` 增加原生“清空全部策略选择（含筛选外）”按钮，同时清除已读选项、确认勾选与当前错误，不清除搜索文本、不修改请求身份、不发业务请求。提交中、结果不确定、已有结果或正在恢复其他请求时禁用，handler 另检查 pending，避免清除原批次上下文。复用现有 btn-sm 风格，无新增依赖或共享样式修改。

`batch-draft-browser-smoke.py` 增加键盘清空两份策略（含筛选外一份）、清空选项及计数、重新选择必须重新确认、未知结果与成功后禁止清空断言。实际执行：

```bash
# apps/web
npm test -- src/components/batch-deployment/NetworkBatchRevoke.test.tsx src/api/networkRevokeBatch.test.ts
env -u VITE_APP -u SIQ_AS_WEB_BASE VITE_DEV_MODE=false VITE_DEMO_PLACEHOLDERS=false npm run build -- --outDir /tmp/siq-batch-clear-standard-20260925
env -u VITE_APP -u SIQ_AS_WEB_BASE VITE_DEV_MODE=true VITE_DEMO_PLACEHOLDERS=false ./node_modules/.bin/vite build --outDir /tmp/siq-batch-clear-mock-20260925
# 仓库根目录
python3 scripts/enterprise-experience/batch-draft-browser-smoke.py --web /tmp/siq-batch-clear-mock-20260925 --out /tmp/siq-batch-clear-evidence-20260925
git diff --check
```

专项 2 文件、34 项通过。标准构建仍因并行 RuntimeBindingsPage 及其测试的 7 处 TS 错误失败，未修改该线文件；Vite-only 模拟身份构建成功，不作为发布产物或标准类型检查通过。浏览器通过，原有 6 次模拟写请求均被拦截，执行请求 0、未捕获异常 0，测试服务器已停止；五视口无横向溢出。已实际查看上述证据目录的 `network-batch-375.png` 和 `network-batch-1280.png`，按钮与当前米白/深蓝/金色风格一致。本轮未复跑全量测试，不以专项结果替代整合门禁。

未提交、未部署、未操作真实设备或业务权限。批量业务审批、真实执行与完整 M0–M4 交付仍须按原任务书继续验证，不声明整体完成。

## Batch 120 — 企业设备凭据吊销管理（ENT-021）

前一轮提供 Kimi 独立审计精确查询任务提示词，未据此宣称开发完成。本轮继续原设备生命周期检查并落地管理 API，不触碰 Kimi 的 audit.py 或并行运行时绑定开发文件。

新增合同 `packages/contracts/enterprise-device-revocation.v1.md`、路由 `apps/control-api/app/routers/device_lifecycle.py`、测试 `app/tests/test_device_lifecycle.py`；在既有脏工作树的 `main.py` 只追加该模块导入与 router 注册，保留其他注册改动。未修改数据库模型、认证函数、限流、安全规则或前端。

- 新增 GET `/api/v1/environments/{environment_id}/devices/{device_id}/credential-status`（env:read）与 POST 同前缀 `/revoke`（edge:manage）。通过租户环境联结定位设备，先 404 后 403；请求确认设备 ID 必须一致，拒绝额外字段。
- 首次通过条件更新吊销时间，与 audit/outbox 同事务；重复请求保留原时间且不重复事件。只返回白名单状态，Cache-Control: no-store，不泄漏哈希、公钥或秘密。
- 经现有在线认证的后续心跳、任务领取、证据/Skill 上传、回执均拒绝旧凭据；持钥注册恢复也不能复活已吊销记录。吊销不停止已在途或离线进程，不撤销或放宽业务权限、不删除原策略、任务、历史审计。
- 专项覆盖审计/outbox/提交失败回滚、响应恢复、对象隔离、只读权限不能吊销、其他设备不受影响、策略与任务逐字段保持、接入页状态读回。独立 15 项，连同既有凭据/恢复/任务租约共 33 项通过。

实际命令（apps/control-api）：

```bash
uv run pytest -o addopts='' -q app/tests/test_device_lifecycle.py app/tests/test_edge_secret.py app/tests/test_registration_recovery.py app/tests/test_edge_task_lease.py --tb=short
uv run ruff check app/routers/device_lifecycle.py app/tests/test_device_lifecycle.py
SIQ_BATCH_WIRE_SAMPLE=/tmp/siq-ent-isolated-wire-20260925/batch-contract-output.json uv run pytest -o addopts='' -q --tb=short
```

失败历史：首次保留策略测试误写创建返回码 200，按既有接口修正为 201。首次全量 1623 通过、13 失败，定位为新增注册夹具耗尽共享环境注册配额（429）；改为本测试模块每用例独立合成环境，未重置/绕过/放宽限流或修改其他测试。修正后全量结果见下方追加记录。

Ruff 和 git diff --check 通过，新文件额外检查无尾随空白。只使用临时 SQLite 与测试身份，不是生产 IAM/原生设备或 PostgreSQL 并发验收。前端吊销确认、凭据轮换、运行绑定失效联动、原生安装升级与整体 ENT-021 仍待完成；未提交、未部署、未吊销任何真实设备。

修正夹具后，以同一全量命令重跑：**1636 passed，1 条既有 Starlette/httpx 弃用 warning，85.70 秒**。未跳过或削弱注册限流测试。本轮未改 Web、未重跑前端门禁，不覆盖此前运行时绑定开发线的整合状态。

## Batch 121 — 设备吊销前端严格调用合同与实际响应消费

上一轮为有效进展：设备吊销 API、事务负向和后端全量完成验证。本轮新增 `apps/web/src/api/deviceLifecycle.ts` 与 28 项单测，作为接入可视化吊销确认的调用基础，不宣称用户已可从页面吊销。

客户端校验路径标识、精确确认设备 ID、响应字段白名单、schema、环境/设备对应关系、active/null 与 revoked/时间组合，以及 runtime_permissions_changed 必须为 false。GET 不推导在线/保护状态，POST 只有明确 revoked 才返回成功；网络或协议失败不自动重试、不自动另建请求、不持久化身份或凭据。调用方仍须处理不确定结果并显式读回，不得把 GET 的 active 当成没有在途请求的证明。

新增 `dev/device-lifecycle-wire.config.ts`、`dev/device-lifecycle-wire.check.ts`；后端 `test_device_lifecycle.py` 增加实际 TestClient JSON 导出。仅导出隔离合成设备的 active、revoked、recovered 投影，不导出头部/秘密，独占创建文件避免覆盖旧证据。消费者实际调用产品解析函数，HTTP transport 替身只转交生产者原始响应，不手写替代 payload。

实际命令：

```bash
# apps/control-api
SIQ_DEVICE_WIRE_OUTPUT=/tmp/siq-device-wire-20260925-2138.json uv run pytest -o addopts='' -q app/tests/test_device_lifecycle.py --tb=short
uv run ruff check app/tests/test_device_lifecycle.py
# apps/web
npm test -- src/api/deviceLifecycle.test.ts
SIQ_DEVICE_WIRE_OUTPUT=/tmp/siq-device-wire-20260925-2138.json ./node_modules/.bin/vitest run --config dev/device-lifecycle-wire.config.ts
npm test
env -u VITE_APP -u SIQ_AS_WEB_BASE VITE_DEV_MODE=false VITE_DEMO_PLACEHOLDERS=false npm run build -- --outDir /tmp/siq-device-api-standard-20260925
```

结果：后端专项 16 passed（1 条既有弃用 warning）；前端新单测 28 passed；实际响应消费 1 passed。证据 SHA256：`26e727a50ccbde394f30895b873d42c080d4af63d86a042731b619548f5af460`，临时文件可能被清理，复跑使用新文件名。

前端全量 93 文件中 91 通过、2 失败；719 项中 706 通过、13 失败，仍为并行 RuntimeBindingsPage 与 RuntimeBindingItem 测试。标准构建仍被该线 7 处 TS 错误阻断；本轮未修改这些文件，不将专项通过当成标准构建成功。Ruff、git diff --check 通过。没有 UI 变更，未做浏览器验收，也未重跑后端全量（上批 1636 的结果不自动更新为本轮全量）。

下一步接入设备列表上的显式确认、待核对与只读恢复交互，继续凭据轮换及真实生命周期验收。未提交、未部署、未触碰真实设备或业务权限，完整目标保持进行中。

## Batch 122 — 设备凭据管理页面与 Kimi 审计查询复核

新增 `components/device-lifecycle/DeviceLifecyclePanel.tsx`、专用 CSS 和组件测试；`EnvironmentsPage.tsx` 仅增加导入与组件挂载，保留现有接入引导/安装/诊断代码。默认折叠，显式打开读取设备清单；ConsoleContext ready、环境访问及 enroll_devices 操作权限均满足才显示。身份/环境 keyed 重建，异步请求用清理与代次检查拒绝旧响应更新，按 React 技能将吊销写请求放在事件 handler 中，不由 effect 触发。

选择后固定设备 ID，输入精确 ID 才能提交；同步 pending 防重复提交。提交前把非敏感目标与待核对标记保留在 URL，失败不显示成功也不自动重试，刷新只 GET 核对原设备。明确不撤销智能体业务权限、不终止离线进程、不删除历史；管理另一设备从环境列表重新进入。结果核对失败不显示陈旧成功。

专项：`npm test -- src/components/device-lifecycle src/api/deviceLifecycle.test.ts`，2 文件 33 passed。标准构建命令使用 `/tmp/siq-device-ui-standard-20260925` 独立目录，仍被 RuntimeBindingsPage 及其测试的 7 处 TS 错误阻断。Vite-only 模拟身份构建 `/tmp/siq-device-ui-final-mock-20260925` 成功，仅模拟用不可发布。

浏览器：`python3 scripts/enterprise-experience/device-lifecycle-browser-smoke.py --web /tmp/siq-device-ui-final-mock-20260925 --out /tmp/siq-device-ui-final-evidence-20260925`，4 组检查通过：显式选择/错误确认禁止提交；375/768/1280 无横向溢出；提交已持久化但响应丢失→读回失败→刷新成功恢复，全程仅 1 次被拦截的模拟 POST；权限取消后深链接不显示管理区且无状态读取。无未捕获异常，服务已停止。已实际查看 device-375.png、device-1280.png，复用 field/btn/card 及米白深蓝金色样式，焦点可见。没有真实业务请求。

前端全量实际重跑：94 文件中 93 通过、1 失败；724 项中 717 通过、7 失败，另 1 个未处理错误，均在并行 RuntimeBindingsPage 测试；该线持续变化，不能沿用前批数字，不覆盖修改其文件。git diff --check 通过。

Kimi ENT-019-AUDIT-QUERY 已查代码、合同与 19 项测试；专项加既有审计/权限/分页回归共 54 passed，Ruff 通过。消息中的“165 项”与交付文档“1655 passed、1 skipped”不一致，主开发者重跑明确统计的全量命令，最终结果追加至其交付记录。未发现当前过滤实现需要修复的逻辑问题，不为制造改动而重构。

以上均未提交、未部署，不代表 ENT-019、ENT-021 或 M0–M4 整体完成。原生生命周期、凭据轮换与真实端到端验收继续待办。

Batch 122 全量追加：提供既有隔离线格式样本后，后端 **1656 passed、0 skipped、0 failed，1 条既有弃用 warning，85.85 秒**；Kimi 审计精确查询子任务复核通过，详细命令及统计口径已补入 `enterprise-audit-query-handoff.md` 第 9 节。不是生产验收。

## Batch 123 — 设备吊销到审计精确查询的实际关联

上一轮为有效进展：设备页面隔离验收与 Kimi 审计查询复核通过。本轮不新增假关联图，而是贯通真实产品写路径到新查询能力：`device_lifecycle.py` 在首次吊销转换时，从既有请求中间件 `request.state.request_id` 取规范化值，传入同事务 audit 与 outbox。不读取原始请求头作为可信身份，不修改审计主键、权限或响应 schema。

`enterprise-device-revocation.v1.md` 补关联语义：首次响应编号可与设备对象/动作组合查询；幂等重试的新编号不覆盖首次事件、不追加虚假转换，重试编号查不到事件不代表未吊销，仍可按设备查原始事件。关联编号不是幂等键或运行保护效果证据。

在 `test_device_lifecycle.py` 新增 3 个参数化集成用例，分别覆盖未提供编号、安全编号、换行注入编号。先在未修复实现上实跑，3 项均因审计查询返回空列表失败；修复后与设备生命周期、审计精确过滤及原请求编号测试合计 **42 passed，1 条既有弃用 warning，3.85 秒**。断言响应/审计/outbox 编号一致、原操作者保留、审计主键独立、跨租户查询为空、GET 无写入，以及重试不改原时间或新增事件。

命令（apps/control-api）：

```bash
uv run pytest -o addopts='' -q app/tests/test_device_lifecycle.py -k trace_query --tb=short
uv run pytest -o addopts='' -q app/tests/test_device_lifecycle.py app/tests/test_audit_exact_filters.py app/tests/test_request_id.py --tb=short
uv run ruff check app/routers/device_lifecycle.py app/tests/test_device_lifecycle.py
SIQ_BATCH_WIRE_SAMPLE=/tmp/siq-ent-isolated-wire-20260925/batch-contract-output.json uv run pytest -o addopts='' -q --tb=short
```

Ruff、git diff --check 通过。没有前端改动，未复跑 Web 门禁或浏览器；仅隔离 SQLite/TestClient，未触碰真实设备、业务权限或线上审计。未提交、未部署，完整设备→角色/Skill→审批/策略→执行效果链仍须继续实现和验收。

本批后端全量完成：**1659 passed、0 skipped、0 failed，1 条既有 Starlette/httpx 弃用 warning，86.16 秒**。

## Batch 124 — 签名设备凭据轮换服务端与历史迁移（ENT-021）

前一轮为有效进展：追溯缺口完成负向复现、修复及全量验证；随后按用户请求给 Kimi 分配了独立审计查询前端任务，没有将提示词当成已完成开发。本批续做轮换服务端，不修改 Kimi 的审计页面或并行运行时绑定文件。

新增 `enterprise-edge-credential-rotation.v1.md`；新增 `credential_rotation.py` 路由，在 main.py 追加注册；models.py 仅插入 EdgeCredentialRotation 模型并保留所有既有改动；新增迁移 0026，以及轮换专项/迁移测试。签名生产者—消费者清单明确当前无原生 Go 生产者/独立固定向量，不虚称对等已通过。

`POST /edge/v1/credential-rotation` 要求当前 Edge Bearer 与设备 Ed25519 签名，绑定设备、环境、轮换 UUID、旧/新 hash；服务端从设备环境派生租户。加锁后重验认证 hash 与吊销状态，CAS 修改凭据，与不可删轮换历史、审计和 outbox 同事务。当前及轮换历史已出现的 hash 不可复用；只返回白名单结果，不回传秘密或 verifier hashes，不改变签名公钥或业务权限。

响应丢失时允许用预先保存的新凭据及同一签名请求核对原轮换；旧凭据后续认证拒绝。重复请求必须匹配历史摘要且仍是当前版本，不重写审计；后续轮换取代的旧请求拒绝。首次注册恢复增加已轮换历史检查，避免未心跳且尚在恢复窗口的设备绕过轮换基线及历史复用限制。

测试覆盖错误密钥、设备/环境不符、无 Bearer、吊销、错误基线、同 hash/历史 hash 复用、后续版本与同 key 异载荷冲突、额外字段拒绝、审计/outbox/commit 异常回滚、响应丢失重试、旧凭据认证拒绝、管理身份头不能改写设备租户、秘密不进入响应/审计/outbox。注册恢复不能把旧凭据恢复回来。

迁移测试在专属临时 SQLite 中通过 Alembic 全链 upgrade head、空表 downgrade 0025、再次 upgrade，以及有记录时 downgrade 拒绝且 verifier 历史不变；没有连接现有部署数据库。初轮测试 25 passed，Ruff 发现 3 处新测试长行，已仅修正格式；随后相关回归 **46 passed，1 条既有弃用 warning，8.45 秒**。

实际命令（apps/control-api）：

```bash
uv run pytest -o addopts='' -q app/tests/test_credential_rotation.py app/tests/test_credential_rotation_migration.py app/tests/test_registration_recovery.py app/tests/test_device_lifecycle.py --tb=short
uv run ruff check app/routers/credential_rotation.py app/routers/registration_recovery.py app/tests/test_credential_rotation.py app/tests/test_credential_rotation_migration.py migrations/versions/0026_edge_credential_rotation.py
SIQ_BATCH_WIRE_SAMPLE=/tmp/siq-ent-isolated-wire-20260925/batch-contract-output.json uv run pytest -o addopts='' -q --tb=short
```

Ruff、git diff --check 通过。当前仅服务端协议及隔离验证；新 secret 的熵只能由可信原生客户端安全随机生成保证，服务端只见 hash 不能证明原像强度。原生私密 journal/响应恢复/CLI、独立向量与 Go 对等、真实 TLS 与 PostgreSQL 并发仍待完成。未提交、未部署、未轮换真实设备；不将这一批称作完整 ENT-021 或正式安装包交付。

本批后端全量：**1678 passed、0 skipped、0 failed，1 条既有 Starlette/httpx 弃用 warning，89.57 秒**。

## Batch 125 — 原生 Edge 轮换协议准备/消费与独立签名向量

上一轮为有效进展：签名轮换服务端、迁移与全量通过。本批新增 `edge/agent/credential_rotation.go`、对应 Go 测试、独立 Python 向量生成器、公开测试向量及 Python 消费测试；更新签名清单与轮换合同。不改既有 client.go、状态存储或 CLI，避免在私密日志未就绪前暴露不安全的轮换入口。

内存准备函数用 crypto/rand 产生独立新凭据和 UUID，复用已有设备 signer，校验 seed 与公钥一致，并对绑定设备/环境/旧新 hash 的完整合同签名。单次 HTTP 方法仅接受与客户端身份/旧或新凭据匹配的请求；HTTPS/本地回环校验复用现有客户端；禁自动重试与重定向；响应有界、字段精确、拒绝重复键/大小写替代键/未知或缺失字段/尾随 JSON/不匹配目标/业务权限变化声明。固定错误不携带服务器错误正文或凭据。调用不修改 State，不自动激活新 secret。

独立生成器 `scripts/enterprise-experience/generate-credential-rotation-vector.py` 不导入产品代码，使用公开 bytes(range(32)) 测试 seed，产出 `packages/contracts/fixtures/credential_rotation_vector_v1.json`。Go 与 Python 分别核对产品 canonical 与固定签名；Python 测试还运行独立生成器核对固定文件没有漂移。不得把此公开测试 key 用于部署。

实际验证：

```bash
# edge/agent
gofmt -w credential_rotation.go credential_rotation_test.go
go test ./...
go vet ./...
# apps/control-api
uv run pytest -o addopts='' -q app/tests/test_credential_rotation_vector.py app/tests/test_credential_rotation.py --tb=short
uv run ruff check app/tests/test_credential_rotation_vector.py
# 根目录
git diff --check
```

Edge 全部 4 个 package 通过，go vet 无错误；轮换 Go 测试覆盖生成/签名不改状态、旧新凭据同请求、12 类异常响应、重定向不转发、本地身份拒绝及独立向量。Python **19 passed，1 条既有弃用 warning，2.78 秒**；Ruff、diff 检查通过。本批未改后端产品代码、未复跑后端全量或前端门禁。

仅临时本地 HTTP fixtures 与合成密钥，没有读取实际 state.json 或设备秘密，未发真实轮换请求。原生私密 journal、掉电恢复/排他锁、CLI 与实际安装生命周期仍待完成，不能称作完整 ENT-021。未提交、未部署、未发布新安装包。

## Batch126：Linux 轮换待恢复日志基础

新增 `edge/agent/credential_rotation_journal_linux.go` 及独立测试。独占创建 0600 待恢复日志，fsync 文件与目录后才返回成功；保留原凭据，不发网络请求。日志保存新凭据与同一签名请求，以除 secret 外的状态摘要绑定设备、环境、控制面与发现计划；读取验证签名、旧/新凭据一致性，复用安全状态读取的路径、权限、链接与重复键检查。已有或损坏日志不自动覆盖，失败保留供恢复。任务排他锁目前为调用前置条件，尚未接通 CLI/网络核对/激活与清理流程。

验证：`go test ./... && go vet ./...` 最终全部 4 个 package 通过（agent 0.933 秒），vet 与 `git diff --check` 无错误；覆盖独占创建、持久读取、准备不激活、激活后可读取、8 类状态/请求漂移及 6 类不安全文件。前两轮测试因测试临时目录权限不满足私密状态及祖先路径要求失败；显式将测试 parent 设为 0700，并在其下创建 private 子目录，未放宽生产检查。仅使用临时合成状态，未读取真实设备凭据。未提交、未部署，ENT-021 尚未完成。

## Batch127：Linux 轮换 CLI 与显式恢复

新增 `rotate_credential_linux.go`、非 Linux 失败关闭 stub 和测试，在 main.go 添加命令分派与帮助，README/合同同步。命令要求确认设备 ID、取得任务锁；严格读取状态，拒绝未知字段。先持久日志后发送；显式 resume 优先新凭据核对，仅 401 且本地仍为旧凭据时对同一请求尝试旧凭据，其他错误不回退。核对后重读状态/日志拒绝漂移，原子保存新凭据并同步目录后清理已验证日志。没有停止服务、注册、扫描或权限授予副作用。

隔离测试覆盖正常成功、服务端提交后响应失败、未提交恢复（新凭据 401 后旧凭据成功）、激活后清理前恢复、未知结果不重试或覆盖日志、确认/参数/任务锁拒绝、未知状态字段拒绝及请求期间状态漂移不覆盖。模拟服务检查发送前 journal 已存在且请求始终一致；不将模拟 commit 断言描述成真实服务端事务证明。

实际执行 `go test ./... && go vet ./...` 全部 4 个 package 通过；新增平台 stub 的 Darwin arm64、Windows amd64 `go build` 输出到独立 `/tmp/siq-rotation-build-*` 目录且退出 0（仅交叉编译，不是原生平台验收）。`git diff --check` 通过。没有复跑后端/前端全量，没有修改 Kimi 开发线。真实 TLS 端到端、PostgreSQL 并发、文件系统故障注入及正式安装包生命周期仍待验证；ENT-021 和总目标未完成。未提交、未部署、未操作真实设备。

## Batch128：轮换状态与日志的精确 JSON 字段校验

审阅发现 Go `DisallowUnknownFields` 仍接受大小写别名；先增加 6 个反例，实际运行全部失败，确认 SECRET/CONTROL_PLANE_URL/NEW_SECRET/REQUEST/SIGNATURE/DEVICE_IDENTITY 被旧读取器接受。新增 `rotation_json_linux.go` 精确字段集合检查，接入状态、日志及嵌套请求读取；日志准备也改用严格状态读取。拒绝 null、未知字段及缺失必填字段，不修复或删除异常文件；原有可选状态字段不变。另补字段形状与大小写别名和规范键并存的冲突测试。

修复后实际执行 `go test ./... && go vet ./...`，4 个 package 全部通过，vet 无错误；`git diff --check` 通过。只涉及轮换局部实现，未扩大修改其他命令或防御规则。所有状态为临时合成夹具，未读取实际秘密、未联网操作真实设备。文件系统故障注入与真实端到端验证仍待继续，未完成 ENT-021；未提交、未部署。

## Batch129：轮换激活故障注入与清理语义

提取仅内部按调用传入的文件操作接口（没有环境变量/CLI 测试后门），新增 `rotation_activation_linux_test.go`。7 个场景：保存前失败、保存后报错、保存虚假成功未写入、状态目录同步失败、日志删除失败、删除后目录同步失败、正常成功；逐步断言操作顺序、状态与原日志保留、错误不泄露注入的秘密，以及再次确认后可以完成激活。清理前新增严格状态读回；未实际写入新状态时不删除恢复依据。

修正最后目录同步失败的提示：此前笼统要求保留日志，但日志可能已被删除；现明确激活已确认、清理持久性待核对，保留当前状态。合同同步说明此边界。实际 `go test ./... && go vet ./...` 4 个 package 通过，`git diff --check` 通过。验证是进程内文件操作故障注入，不是物理断电、真实磁盘故障或控制面端到端证明；发送前日志写入故障与真实集成仍待继续。未读取实际凭据、未操作真实设备，未提交、未部署，ENT-021 与总目标保持未完成。

## Batch130：原生 CLI → 实际控制面路由隔离集成

新增 `apps/control-api/app/tests/test_credential_rotation_native.py`：实际构建 Go CLI，生成独立测试设备身份与 0600 临时状态，通过仅回环 HTTP 桥接调用真实 FastAPI TestClient 路由及隔离 SQLite。没有伪造成功响应；响应丢失场景在后端返回真实 200、提交事务后由桥接丢弃响应。CLI 首次失败保留原状态与日志，显式 resume 请求逐字相同，使用新凭据读回完成，真实历史/审计/outbox 计数不再增加。核对旧凭据心跳 401、新凭据 200、其他状态字段不变、日志完成后清理及进程输出不含合成秘密。测试桥接线程最终关闭。

实际验证：新增集成 **2 passed，1 warning，3.67 秒**；Ruff 通过。组合执行 native、rotation、vector、registration_recovery、device_lifecycle、rotation_migration 六个文件 **49 passed，1 条既有弃用 warning，10.45 秒**。`git diff --check` 通过。本轮新增隔离测试与文档，未改后端业务代码；没有运行生产服务、使用真实设备或读取实际凭据。未跑后端全量/前端门禁。证据范围是 Go 与真实路由的开发环境协议集成，不是生产 TLS/IAM/PostgreSQL、真实安装服务或物理掉电验收。ENT-021 与整体目标仍未完成，未提交、未部署。

## Batch131：跨模块集成门禁与资产关系缺口复核

重新核对任务书与当前实现，没有以轮换子任务替代 M0–M4 全部目标。实际执行后端 `uv run pytest -o addopts='' -q --tb=short`：**1682 passed、1 skipped、1 条既有 warning，96.28 秒**。未提供 SIQ_BATCH_WIRE_SAMPLE 时既有 grant-batch 线协议样本测试跳过；随后显式提供已有隔离样本 `/tmp/siq-ent-isolated-wire-20260925/batch-contract-output.json` 单独运行 `app/tests/test_grant_batch_contract.py`，**6 passed、1 warning，0.05 秒**。后者是既有样本消费验证，不是本轮重新生成的 Go 响应，也不把两次执行合并描述为一次全量零跳过。

前端 `npm test`：**720 passed、4 failed，共 724 项/94 文件**。失败集中于 RuntimeBindingsPage.test.tsx：筛选无匹配、选择不匹配禁止创建、登记成功、登记失败交互。标准生产形状命令 `env -u VITE_APP -u SIQ_AS_WEB_BASE VITE_DEV_MODE=false VITE_DEMO_PLACEHOLDERS=false npm run build -- --outDir /tmp/siq-enterprise-integration-20260925-b131` 在 tsc 阶段退出 1：RuntimeBindingsPage.test.tsx 的未使用 click（366）及 5 个传参数量错误（447/448/479/480/504），RuntimeBindingsPage.tsx 未使用 hasActiveBindingFilters（29）。该次实际输出为测试文件 6 条加页面 1 条，共 7 条 TypeScript 错误；没有通过临时配置绕过并宣称标准构建成功。运行时绑定仍属并行开发线，本批不覆盖其文件。

ENT-008/009/018 的下一关键功能缺口：`RoleSkillSelectionObservation` 保存已签名来源的声明名称历史，`SkillInstallation` 按设备+locator 摘要区分安装位置；`discovery_origin.py` 和 skill inventory 合同仍明确 relationship_status=unresolved。当前没有把角色选择精确绑定到安装位置/manifest 版本的证据，不能按同名、目录名或同设备直接拼成已验证归属。后续需补版本化关系证据生产、入站校验和可视化投影，保持声明、安装、运行绑定和 effective 权限的语义分离。

本批是集成门禁及缺口核验，没有修改产品代码、部署或业务数据。标准前端门禁尚未通过，角色—Skill 精确关系及生产验收未完成，目标继续进行。

## Batch132：OpenClaw 配置实例来源与入库校验

新增 `enterprise-framework-source/v1` 合同及 OpenClaw 生产者：从已获准扫描的规范配置根生成域分离 SHA256 实例标识，绑定配置内容摘要与本角色引用的配置证据 ID；既有角色 v2 身份不变。同设备同配置根多个角色共享实例标识，不同根区分，改名/配置格式变化不改变实例身份。新属性不输出原始路径，路径摘要不声称匿名化或防猜测。

新增 `app/framework_source.py` 并在 inventory 既有签名验证后、证据/资产写入前调用。检查精确字段、大小写/重复键/大小/格式、任务 Connector、候选 v2 身份、唯一配置证据及其 subject_ref 和内容摘要一致性；不携带新声明的旧生产者兼容。沿用认证租户/设备作用域保存候选属性，不授予权限、不自动确认资产、不按技能名称建立安装归属。没有新增数据库表或宣称已具备不可变框架实例历史。

验证：OpenClaw `go test ./...`、`go vet ./...` 通过；`go test -race -count=1 ./...` 通过（2.552 秒）。首次采集器回归暴露旧 JSON5 测试把全部属性当作格式无关语义；新来源中的原始配置摘要/证据 ID 必然随格式变化。增加对稳定实例身份和两侧原始证据的分别断言后，仍比较其他全部属性，没有删掉原语义检查。后端新增 11 类实际签名批次入库测试，包含合法/旧生产者、来源篡改及原子拒绝；与角色声明、inventory hardening/review、租户隔离组合 **63 passed，1 条既有 warning，8.44 秒**。Ruff、`git diff --check` 通过。

当前仅打通配置实例来源生产与校验保存；来源查询、框架树聚合、精确角色—Skill 安装/版本证据和可视化仍待接线，不能宣称 ENT-008/009/018 已完成。所有测试使用临时合成配置与隔离设备，未读取真实用户配置、未扫描或上传真实设备，未提交、未部署。保留并行开发改动。

## Batch133：框架配置实例来源只读投影

新增 GET `/api/v1/agents/{asset_id}/framework-source`（enterprise-framework-source-view/v1），先租户定位 404，再 agent:read/env:read 403，no-store。复用严格来源解析，重新关联设备环境租户与配置证据的 collector、subject、摘要和本资产证据引用。无声明为 no_recorded_source；缺失/畸形/跨租户/不一致为 source_unavailable，不回显无效属性；成功仅为 historical_reported_source，保留观察时间、设备吊销标识，runtime_status=unverified、skill_relationship_status=unresolved、effective_permissions=null。输出没有路径、签名或配置正文，也不发业务写请求。

补实际签名上传→只读投影断言及 12 项只读来源测试，覆盖旧记录、权限不足/跨租户、篡改证据摘要/subject/collector/环境/租户、损坏设备关联、吊销仍保留历史、忽略 tenant/device 查询覆盖以及读取前后行数不变。初次重复证据夹具被数据库唯一约束拒绝，改为明确断言 IntegrityError 并核对原证据仍正常投影，没有放宽数据库约束或删除负向覆盖。

最终组合 framework_source、framework_source_view、discovery_origin、role_skill_selection、tenant_isolation：**59 passed、1 条既有 warning，6.72 秒**；随后修复测试一处行长格式，Ruff 与 diff 检查通过。未运行本批后端全量或前端门禁。框架树前端和精确角色—Skill 安装关系仍待实现，不能以此来源接口宣称整个关系治理完成。没有改业务权限、生产部署或真实设备数据；未提交、未部署。

## Batch134：资产详情接入框架配置来源

新增 `apps/web/src/api/frameworkSource.ts` 严格 GET 客户端与测试，核对资产、精确字段、摘要、设备/环境标识、时间及未验证/未关联/null 权限语义；异常响应拒绝，不显示安全结论。新增 `inventory/FrameworkSourcePanel.tsx` 与 SSR 测试，挂载至 AgentDetailPage。复用 card/btn/kv-list/mono 与原生 details，没有改全局 CSS、引入依赖或改个人端。按 ConsoleContext 的 agents/environment 权限过滤；身份/资产组合 key 隔离旧请求，卸载回调失效，重新核对只发 GET。展示历史来源及吊销标识，保留未知/不可确认/加载/失败区分，不把来源标识当运行保护证明。

使用 React 最佳实践技能，落实 primitive effect dependency 与身份切换重建请求区域，避免引入请求状态共享或存储。新增 API/展示测试 **30 passed（2 文件）**；全量 `npm test` **750 passed、4 failed（754 项/96 文件）**，失败仍在并行 RuntimeBindingsPage 交互测试。标准 `npm run build -- --outDir /tmp/siq-framework-source-b134` 被该开发线 **6 条 TypeScript 错误** 阻断：测试 238/239/270/271/295 参数数量错误与页面 29 未使用导入。没有本次新增文件的类型错误输出；这不等同标准构建通过。diff 检查通过。

本批尚未完成新卡片的浏览器截图、375px/键盘/身份切换交互验收，需下一批补齐；SSR 不冒充浏览器验收。关系树聚合与角色—Skill 安装证据仍未完成。未提交、未部署、未操作真实业务；保留全部并行改动。

## Batch135：框架来源卡片隔离浏览器验收

新增 `scripts/enterprise-experience/framework-source-browser-smoke.py`，仅监听回环临时端口并拦截所有 API；6 组检查通过：历史/吊销/未知技能语义与 XSS 纯文本；键盘展开 details 与可见焦点；375/768/1280 文档及 content 无横向溢出；读取失败与两种未知状态、刷新不留旧成功值；延迟旧请求 503 不覆盖新结果；无环境权限时不渲染也不发送来源请求；全过程无业务写/外部请求/未捕获异常。最后一项作为无副作用组，报告按 6 组聚合，不按文字子断言虚增数量。

使用独立模拟构建 `/tmp/siq-framework-source-browser-mock-b135`：显式 VITE_DEV_MODE=true、VITE_DEMO_PLACEHOLDERS=false，直接 Vite 构建用于隔离浏览器检查，不包含 tsc 门禁，绝不可发布或部署。标准构建仍以 Batch134 的未通过结果为准。最终脚本 exit 0，报告 `/tmp/siq-framework-source-browser-evidence-b135-final/report.json`，source_reads=6、violations=[]、errors=[]。同目录 `framework-source-375.png` 与 `framework-source-1280.png` 已实际查看，保持现有米白卡片/深蓝文字/金色焦点，长摘要换行且无溢出。截图中其他面板的失败提示来自未覆盖的模拟接口，不是生产故障证据。

Ruff（修复脚本一处行长后）、diff 检查通过。脚本退出前关闭临时 HTTP 服务和浏览器。本批未改产品 UI 或防御逻辑；没有真实身份切换端到端证据，已验证的是重试竞态与无权限重新加载。框架树聚合和角色—Skill 精确关系仍待推进；未提交、未部署、未操作真实数据。

## Batch136：框架—角色清单分页后端与共享来源投影

新增合同 `enterprise-framework-role-inventory/v1` 与 GET `/api/v1/framework-role-inventory`：认证租户范围，agent:read/env:read 双权限，环境/设备精确过滤，资产 ID 游标，limit 1–100，limit+1 判定下一页；coverage=page_of_tenant_assets，不推断组织全量。保留旧/来源未知资产，来源沿用 historical/no_recorded/unavailable 语义；没有技能安装归属或运行权限推导。

新增 `framework_source_view.py` 共享投影，详情接口与清单共用同一实现。资产页查询之外，批量一次读取本租户设备/环境、一次按精确复合证据键读取证据；不逐角色请求，不跨设备/租户用同名匹配。测试已使用 **100 个不同角色与各自证据** 断言投影只发 2 次 SELECT，并拒绝超过上限和传入外租户资产。分页测试核对三页完整有序无重复、详情逐项一致、旧来源保留、越权403/外租户空清单、环境/设备 AND、不接纳 tenant 覆盖和参数边界。

实际验证：前一轮 25 项通过但 Ruff 报一处测试行长，已修复。共用投影后的 framework source/view、discovery origin、role selection、tenant isolation 组合 **61 passed、1 条既有 warning，6.82 秒**。加强为 100 个真实不同角色后 source view 文件 **14 passed、1 warning，2.65 秒**；Ruff 与 diff 检查通过。未把局部门禁描述为本批后端全量通过。

Kimi 已分配 ENT-018-FRAMEWORK-TREE-UI，负责独立前端客户端/分组/分页展示及 AgentsPage 最小接入；本批未触碰其前端文件。角色—Skill 精确安装证据仍未完成，树状显示不能提前宣称该关联已解决。未提交、未部署、未扫描真实设备或修改业务权限。

## Batch137：配置来源摘要完整性修复

推进 ENT-008/009 的角色—技能来源核对时，发现 OpenClaw 超预算读取仍可能接受合法 JSON 前缀，并为不完整内容产生候选、证据和声明权限。新增 `config_integrity_test.go` 先复现：尾部空白、JSON5 注释、使完整文件非法的尾部内容三种情况下，旧实现均错误产生 1 候选、1 证据、1 声明事实，测试失败。

新增 `enterprise-openclaw-config-integrity/v1` 合同；修改已有安全打开后的 `readFileLimited`，在同一文件描述符上检查读取前大小、读取长度和读取后大小/修改时间。文件超过剩余预算即不返回部分字节，沿用截断批次语义；移除读取后重新按路径 stat 并继续解析截断前缀的逻辑及其路径日志。保持现有权限、证据身份和安全打开机制。元数据检查不是原子快照证明，不声称抵御可恢复元数据的本机攻击者。

新增 3 个顶层测试（含 3 个负向子场景）：超预算合法前缀拒绝；精确预算完整文件摘要含注释；多根预算耗尽只保留前一个完整根。实际执行 OpenClaw `go test ./...` 通过（0.118 秒）、`go vet ./...` 通过、`go test -race ./...` 通过（2.381 秒），`git diff --check` 通过。没有针对文件并发修改做确定性故障注入，本批不以 race 检查代替该证据。

关联研究另已核对 OpenClaw 官方技能文档（https://docs.openclaw.ai/tools/skills ，2026-09-25）：工作区、共享目录及其他来源存在加载优先级，不能用技能名称拼接一个安装路径冒充精确关联。当前 Directory 采集只有安装位置摘要，仍需有证据的角色来源到安装位置关联合同及生产者/消费者；本批没有完成该关系。Kimi 新分配框架清单 wire 验收，本批未触碰其文件。未提交、未部署、未扫描真实目录、未变更业务权限。

## Batch138：角色声明的技能来源目录摘要与签名入库门禁

新增 `enterprise-role-skill-roots/v1`，OpenClaw 在已签名候选上输出 `skill_source_roots`，配合必需的有效 `framework_source` 绑定该角色的完整配置证据。对于明确 POSIX 绝对 workspace，仅计算 workspace/skills 与 workspace/.agents/skills 的规范位置 SHA256，不读取这些目录、不扩大扫描授权、不从技能名称拼路径。默认角色继承的 workspace 显式标记 default_workspace；缺失/相对/波浪号/变量/控制字符/通配/过长路径标记 unresolved，尚未实现这些路径及其他加载来源的解析。

新 `role_skill_roots.py` 在 inventory 现有签名/设备/配置来源校验之后、首次写入之前检查严格字段、2048 字节上限、重复 JSON 键、状态/basis、固定两类目录顺序及不同的小写摘要。旧生产者无此属性兼容；非法载荷统一 422、无资产/证据/权限落库、任务仍 pending。复用资产属性保存最新声明，未新增历史关系表；现有来源 API 的 skill_relationship_status 继续 unresolved、effective_permissions=null，避免声明来源误升级为安装/运行事实。

实际验证：新增 Go 3 个测试验证共享工作区跨不同技能名称相等、不同目录同名技能不合并、规范路径摘要、路径不回显、未解析路径不借用本机上下文及默认来源。OpenClaw 全包 test（0.126 秒）、vet、race（2.501 秒）通过。新增后端 13 个签名上传场景，包含正向/兼容/负向/幂等和权限零新增；与 source/source view/tenant isolation 组合 **48 passed、1 条既有 warning，5.87 秒**。首次 Ruff 发现新增 import 顺序问题，修正后通过。

下一段仍必需：技能采集端输出可信范围内的位置包含关系，经签名上传、租户/设备/配置观察约束与完整 manifest 关联，再提供明确的历史安装来源读模型。当前只有目录声明，不能按目录名或摘要单独认定角色已安装/已加载某技能；其他加载层、共享来源、相对路径与真实运行时关系仍未完成。未修改 Kimi 前端/wire 文件、未提交、未部署、未读取真实用户配置。

## Batch139：技能目录包含链 v2、签名上传及原字节恢复

新增 `enterprise-skill-ancestry.v2.md`。保留 Directory `collect_skills` 的 v1 输出；新增 `collect_skills_v2` 和显式能力 `skill_manifest_ancestry_v2`。Linux 安全递归中为每个完整清单附加 `ancestor_sha256`，从安装目录自身到本次授权根，最多 33 项，不输出授权根以上目录。重叠根继续去重；显式窄根只输出其范围内链。仅摘要，无原始路径、额外文件读取或执行。

Edge 依据采集器能力选择操作；v2 验证链非空/上限/首项=安装位置/格式/去重后生成 enterprise-skill-upload/v2，v1 行为不变。控制面 schema 同时验证两版本，v1 禁止新字段、v2 要求合法链。链进入原有同事务 SkillUploadReceipt.signed_payload，与安装观察 batch_digest/manifest_sha256 关联，不新增迁移、不修改旧安装身份。上传日志允许两版本并保留原签名字节，变更链不能覆盖待处理日志。部署顺序需控制面先支持 v2；旧控制面拒绝时不静默降级重签或重扫。

验证：Directory 新协议测试比较 v1/v2、三层实际合成目录、重叠根与窄范围链；全包 test/vet 通过，race **1.077 秒**。Edge 新增 8 个签名/非法链子场景与 v2 持久化原字节恢复/覆盖拒绝测试；全模块 test/vet 通过，race 主包 **5.917 秒**，其他三包通过。后端新增 9 个实际签名上传场景：严格 schema、回执中原链、观察摘要关联、同批幂等和改链重放冲突；与既有技能上传/清单/迁移/首扫/能力领取组合 **77 passed、1 条既有 warning，19.09 秒**。Ruff、git diff --check 通过。

本批验证是合成目录 Go 测试与 Python TestClient 上传，尚未完成 Go 真实 v2 输出到控制面的跨进程端到端验证，也未验证真实设备/生产 PostgreSQL。角色到安装位置的读模型和前端仍未接通，不把链视为运行加载/有效权限。未提交、未部署，未修改 Kimi 文件。

## Batch140：角色与技能安装位置历史来源对照 API

新增 `enterprise-role-skill-sources-view/v1` 与 GET `/api/v1/agents/{asset_id}/skill-installation-sources`。先在认证租户定位资产，再 agent:read/env:read，no-store。共用框架来源投影与新提取的目录声明解析函数，缺失/损坏/未解析来源返回 source_unavailable，不能解释成零安装。按同租户、同设备安装位置 ID 分页（1–100），返回本页所有位置而非只筛匹配项，保留下一页和未确认记录。

基于每个安装位置最新观察，从同租户/设备回执重建签名输入，检查批摘要、设备签名、task 环境/目标/范围摘要、严格上传 schema，以及观察的 manifest/解析字段/时间/签名与原文一致。每批只验签一次，有界读取；缺证据/歧义/篡改不回退旧观察。v2 链包含声明根时 historical_source_match，否则 outside_declared_sources；v1 或证据不足 unresolved。只比较历史目录报告，不证明允许列表、加载优先级、当前存在或执行。配置与清单观察时间各自保留，历史吊销标记可见；effective_permissions 始终 null。

新增 14 项专门测试：同名不同目录独立、两个来源类别、分页、权限/跨租户、参数覆盖不能改变范围、吊销历史、缺失/损坏回执、签名/任务范围/设备/租户/manifest 错配、配置损坏、最新观察缺证据不回退，以及同批仅一次验证、GET 前后行数和业务字段不变。测试均为合成数据；配置来源夹具直建数据库，技能 v2 通过真实签名上传路由入库，不宣称原生 Connector 到 API 全链路已验收。

实际验证：首轮 25 项通过但测试 import 排序/未使用导入未过，已修复。相关组合 **68 passed，8.25 秒**；最后新增批验签计数/字段快照后专门文件 **14 passed，3.64 秒**，Ruff/diff 检查通过。后端全量（启动时尚未收集最后新增的计数测试）**1742 passed、1 skipped、1 warning，86.92 秒**；最后新增项已由上述专门文件实际执行。既有 skip 为缺少 SIQ_BATCH_WIRE_SAMPLE 的独立 Go 回灌检查，不称为全量零跳过。

仅修改主开发线 API/共享解析、新增合同及测试；未改 Kimi 文件或前端。尚需前端展示、完整原生 v2 签名端到端、更多加载来源及角色配置不可变历史；本 API 没有创建持久角色绑定、业务授权或扫描任务。未提交、未部署，未操作真实设备。

## Batch141：企业资产详情中的角色—技能来源只读展示

新增 `api/roleSkillSources.ts` 严格解析 scoped GET 响应，复用框架来源与 Skill 观察校验，检查根声明、匹配状态、证据一致性结构、排序/游标、不接受权限升级字段。新增 `RoleSkillSourcesPanel` 并仅在 AgentDetailPage 增加 import/挂载；复用 card/btn/kv-list 和米白/深蓝/金色焦点，不改共享 CSS、个人端或 Kimi 框架树。原生 details 展示位置/清单/观察/签名批次摘要和声明工具，三个关系标签都不冒充加载/当前存在/有效授权；来源不可用与空页区分。

按设备安装页展示，不累加跨页结果；下一页、上一页、失败重试本页保留游标，重新核对回到首页。遵循本轮已读取的 React 技能规则：effect 使用 assetId/cursor 原始依赖，交互更新留在 handler；身份/资产/页面/重试实例切换时清理旧请求响应，避免迟到覆盖。ConsoleContext 未就绪或缺 agent/env 读取权限不挂载、不发请求。

验证：新增 26 项 API/SSR 单测通过（最后一次 205ms）；最终标准 `npm run build -- --outDir /tmp/siq-role-sources-b141-final-build --logLevel error` exit 0。前端全量本次 **832 passed、7 failed（839 项/101 文件）**，失败均位于并行框架树 `FrameworkTreeView.test.tsx`，未修改/放宽其测试，不宣称全量通过。

新增隔离浏览器脚本 `role-skill-sources-browser-smoke.py`。最终 mock-only 构建 `/tmp/siq-role-sources-b141-final-mock-only`（VITE_DEV_MODE=true，不可发布），浏览器 **7 个检查组通过**：历史/吊销语义、XSS 纯文本、键盘展开/焦点、375/768/1280 无横向溢出、下一页失败后保留同一 cursor 重试、返回上一页、不混页、错误/不可用状态、旧失败不覆盖新刷新、无权限不请求、零业务写/外部请求/未捕获异常。报告 `/tmp/siq-role-sources-b141-final-evidence/report.json`，read_cursors 明确记录连续两次 ski_one。桌面与 375px 最终截图均已实际查看；其他面板错误来自未覆盖的 mock 接口，不是生产故障证据。

Ruff 和 diff 检查通过。浏览器是全隔离模拟，不证明真实 IAM、后端关系读回或设备采集链；原生 v2 端到端和不可变角色配置历史仍待完成。本批未提交、未部署、未扩大任何业务权限。

## Batch142：原生采集、Edge 技能签名与 API 来源匹配集成验证

新增 Go `skill_ancestry_native_linux_test.go` 与后端 `test_skill_ancestry_native.py`。后端测试构建真实 Directory/OpenClaw 二进制，在 pytest 临时合成目录创建两个同名不同位置技能和 OpenClaw 显式 workspace 配置。Go 使用真实 NDJSON 子进程传输、v2 能力检查和 collect_skills_v2，再调用真实 prepareSkillUpload，使用与注册测试夹具一致的合成身份密钥签名；只导出签名批次、摘要和公钥，不导出私钥或真实身份。输出独占创建；二次导出非零退出且原文件字节保持不变。

实际后端 API 原样接收 Go 签名批次：篡改位置链先得到 401，原批成功且同批重试幂等，签名回执保存完整链。Python 从临时文件路径独立计算逐级摘要和完整 SKILL.md 摘要作期望，检查链止于授权根、原始路径和合成 .env 内容未出现在技能输出。OpenClaw 原生输出经测试签名辅助函数进入实际候选批路由，不再直建角色来源表；配置摘要与原始配置文件一致。最终来源 GET 返回两个独立安装身份、historical_source_match 和同一签名批次；查询前后审计/outbox/权限/观察计数不变，采集产生的唯一工作区事实保持 declared，effective_permissions=null。

范围说明：技能批签名来自真实 Go Edge 产品函数；OpenClaw 配置批签名仍由 Python 测试辅助函数生成。HTTP 通过隔离 TestClient，不经过生产网关/TLS，也不覆盖 installed-capability 测量、常驻服务调度或真实 IAM/PostgreSQL。测试密钥为已知测试派生方式，仅用于合成注册夹具；没有读取用户配置或设备状态。

验证：扩展 OpenClaw 原生来源后单项集成 **1 passed，2.63 秒**；最终与 ancestry/role sources/roots/upload 组合 **69 passed、1 条既有 warning，11.09 秒**，Ruff/diff 通过。Edge 全模块 go test/vet 通过；普通 Go test 中导出桥无显式输入会 skip，但本批已由 Python 提供合成输入并实际执行，不能把普通 Go test 独自当作跨进程证明。未重跑本批全量后端或前端。

最终临时证据 `/tmp/siq-ancestry-b142-FSBLrv/test_native_skill_ancestry_sig0/signed.json`，文件 SHA256 `9878e6e557b552a6bc5ec3df9cb0b452adce2da5695f109109c1305a705a4fd1`。该文件只有合成签名批次及公钥，可供复核，不是生产上传凭据或发布制品。未提交、未部署、未修改 Kimi 文件。不可变角色配置历史、其他加载来源与真实运行时授权链仍待推进。

## Batch143：角色配置来源追加式历史与迁移门禁

新增 `enterprise-role-configuration-history/v1`、RoleConfigurationObservation 模型及 0027 迁移（父版本 0026）。在 inventory 既有验签、任务/设备、配置来源与目录声明验证后，同资产/证据/审计事务追加快照：认证租户/资产/设备/任务、批摘要、严格配置来源、可空目录声明、配置证据观察时间和接收时间。未带本批配置声明的旧生产者不补造历史；根声明缺失记录 null，不从旧资产属性继承。旧观察没有产品更新/删除入口，不声称能抵御数据库管理员修改，也不把只有 batch_digest 的本表说成可独立重建完整原批验签。

同批重放沿用既有幂等，不新增历史；不同配置批改变最新资产属性时旧快照不变。新增框架来源批的重复资产位置检查，避免混合旧/新候选覆盖同一资产。最初重复 ID 测试期望了新错误码，实际被既有 duplicate_candidate_id 更早拒绝；已分别验证既有重复 ID 与不同 ID 同位置两种门禁，没有放宽拒绝。审计抛错时历史、资产及任务状态一起回滚。

迁移只创建新表/索引，不回填旧记录；认证租户+资产联合外键、设备/任务外键、asset+task 唯一约束。隔离 SQLite 从空库升级到 0027、空表降级/重升通过；跨租户测试使用另一个资产避免被唯一约束误挡，并断言实际 FOREIGN KEY 错误；重复任务观察断言 UNIQUE 错误；有数据降级拒绝且表仍存在。没有执行生产迁移。

实际验证：历史/迁移加 roots/framework source/原生 ancestry 组合 **30 passed，7.31 秒**；两处测试行长修正后 Ruff 通过。后端全量 **1749 passed、1 skipped、1 条既有 warning，101.26 秒**；skip 仍为缺少 SIQ_BATCH_WIRE_SAMPLE 的独立回灌项，不称全量零跳过。git diff --check 及新增文件空白检查通过。

本批完成的是追加式存储与迁移，不是历史查询界面或按旧快照的技能对照；现有最新来源 API 不变。下一步仍需带权限和设备范围的历史读取、旧快照对照及展示；完整原批签名回放能力另行设计。未提交、未部署、未变更运行时权限，未修改 Kimi 文件。

## Batch144：角色配置历史只读 API 与权限/分页验证

新增 GET `/api/v1/agents/{asset_id}/configuration-observations` 与合同读模型部分。认证租户先定位 404，再 agent:read/env:read 双权限；以快照关联设备、环境、任务核对同租户作用域，不从最新资产属性重建旧值。received_at/id 双降序、limit 1–100、资产内 cursor 锚定；跨资产/未知/不可读锚点 404。no-store，无 GET 写操作。

返回 recorded_snapshot 或 snapshot_unavailable；严格重读配置来源/目录声明结构并核对任务类型/环境/目标/批摘要，损坏内容不回显。目录声明可 null，旧资产无快照为空历史但不是未安装。吊销设备保留历史标记；记录是此前入库验证的快照，不是原批重新验签证明，runtime_status=unverified、effective_permissions=null。

新增 13 项测试：同时间戳三页稳定遍历、最后页空结果、缺失目录声明、最新属性改变后旧历史保持、GET 前后快照字段及审计/outbox计数不变、跨租户/跨资产cursor/参数覆盖、非法边界、结构/任务损坏、设备移至外租户后不泄露、旧生产者无虚构历史。独立权限集合测试保留 admin 角色标签但分别移除 agent/env 权限，均 403；两权限齐全才 200，身份替身仅用于隔离测试并自动恢复。

实际验证：首轮历史/storage/migration **14 passed** 后发现一处测试行长，已修正。最终与来源对照、原生 ancestry、租户隔离组合 **43 passed、1 条既有 warning，13.23 秒**；Ruff/diff 检查通过。本批未重跑全量后端、未修改前端、未执行生产迁移。历史 UI、按旧快照对照技能及原批签名回放能力仍未完成。未提交、未部署、未修改 Kimi 文件。

## Batch145：已保存配置快照与最新技能观察对照

新增 enterprise-role-skill-snapshot-comparison/v1 合同及 GET `/api/v1/agents/{asset_id}/configuration-observations/{observation_id}/skill-installation-sources`。认证租户范围内定位资产和快照后检查 agent/env 双权限，使用该快照的设备和根声明；缺失、损坏或 unresolved 不回退到最新配置。复用最新技能观察的签名回执验证与有界分页，明确 comparison_basis 为 latest_skill_observations_against_saved_configuration，不声称时点回放或运行时生效。原最新来源 GET 保持接口不变。

新增 snapshot comparison 7 项测试，覆盖旧根不随最新属性变化、分页、吊销设备历史、只读计数/字段快照、配置/任务/技能签名摘要损坏、跨租户/跨资产/权限拒绝及参数边界。原生 ancestry 集成增加真实配置入库快照对照调用。与原来源及原生集成组合 **22 passed、1 条既有 warning，6.02 秒**；整理两处导入格式后 Ruff 通过。没有重跑全量后端，也没有生产迁移、提交或部署。配置历史前端仍待完成。

同轮收到 Claude 绑定 UI 完成通知，转入用户授权的验收修复；独立结果记录于 [绑定 UI 复核](enterprise-runtime-binding-ui-review.md)。不能将该前端子任务验收等同 ENT-018 或整个项目完成。

## Batch146：Kimi 框架树主开发者验收与修复

用户要求验收 Kimi 框架树，发现问题直接修复。独立负向测试复现实例键/设备键直接拼接碰撞（2 项）和将首角色证据当整实例证据（1 项），均先失败后修复。两级键改 JSON 数组编码；来源摘要、证据和观察时间改为逐角色展示，不推断共同配置时点。

修复详情返回丢失框架视图：保持既有 `/agents` 路由，使用 `view=framework` 及环境/设备白名单查询；刷新、返回、前进后退可恢复。新增 2 项查询白名单单测，未更改业务权限/后端或既有批量操作。专用样式保留原主题。浏览器补展开证据溢出及完整返回链检查，零业务写。

实际门禁：框架/API 聚焦 62 项通过后再加入导航测试；最终全量 **102 文件 / 846 项通过**，正式模式标准构建成功；最终隔离浏览器 **15/15**，无未捕获异常和越界请求；Ruff/diff 通过。桌面/375px 逐角色证据截图已实际查看。详见 [框架树复核](enterprise-framework-tree-ui-review.md)。未提交、未部署，不代表 ENT-018 或整体目标完成。

本轮在转入验收前新增主线配置历史客户端及面板草稿（`api/roleConfigurationHistory.ts`、`components/inventory/RoleConfigurationHistoryPanel.tsx`），尚未挂载、未补齐其单测/浏览器证据，不能算功能完成；后续从这两个文件继续历史 UI 与快照对照。

## Batch147：配置历史在途收集与收口评估（2026-09-26）

配置历史前端补齐精确字段/权限语义、微秒接收时间顺序、游标/重复记录及错误拒绝测试；使用原生详情、既有 card/btn/kv-list 和身份范围 key 接入资产详情。新增 API/组件 **38 项通过**；当前全量前端 **104 文件 / 884 项通过**；`tsc -b && vite build` 的模拟身份构建成功，目录 `/tmp/siq-config-history-mock-only-20260926`，不可发布。新增 `configuration-history-browser-smoke.py`，尚未执行浏览器和最终正式模式构建，不把该面板标为验收完成。

期间用户要求评估剩余任务、转向收口，已停止本轮功能扩展。重新阅读 ENT 全部验收要求、各批索引、关键合同和当前源码，形成 [CL-01–08 收口清单](enterprise-auto-onboarding-closeout-20260926.md)，逐项覆盖 ENT-001–022，明确功能缺口、原生证据、外部决策/授权、先后依赖和结束条件。任务书原状态表中 ENT-014–016/019/021 全部 todo 等过时概括已校正，导航指向新清单；保留旧证据和失败历史。

主要阻断闭环的是精确关系、设备/Skill/revision/共享运行影响、真实权限效果、完整审计及可信原生安装/恢复/正式交付，不是需要再重做导航或列表。当前没有重新探测生产环境、签发、提交或部署；目标不标完成/阻塞。下一步先 CL-01 收完在途浏览器与正式构建、固定集成基线，然后按收口包推进。

## Batch148：CL-01 配置历史展示验收与后端全量更新

上一轮为有效进展：收口清单已落盘并校正原任务状态。本轮不扩展功能，先收完 Batch147 配置历史面板门禁。

- `configuration-history-browser-smoke.py --web /tmp/siq-config-history-mock-only-20260926 --out /tmp/siq-config-history-evidence-20260926-r1`：**7/7** 检查通过；加载不伪零、迟到失败不覆盖新响应、键盘展开/焦点、XSS 纯文本、缺失根不回填、历史设备吊销、375/768/1280 内外无溢出、分页失败同游标重试/上一页、空态及权限不足零请求。所有 API 为 loopback 合成响应，未发业务写，无异常/越界请求。
- 已实际查看 `configuration-history-375.png`、`configuration-history-1280.png`，保持原 card/btn/kv-list 主题，长摘要正常换行。
- 标准 `npm run build -- --outDir /tmp/siq-config-history-production-20260926`：取消 VITE_APP/SIQ_AS_WEB_BASE，显式 VITE_DEV_MODE=false、VITE_DEMO_PLACEHOLDERS=false，tsc 与 Vite 成功。
- 再跑 `npm test`：**104 文件 / 884 项通过**。
- 后端 `uv run pytest -q` 全量 **exit 0、无失败**；当前配置双 quiet 未输出数量汇总，随后独立 collect-only 核对 **1770 项收集**；运行输出含 1 项既有 wire 样本缺失 skip 和 1 条既有 Starlette 弃用 warning。不称全量零跳过，也不将 collect-only 本身当执行证据。
- Ruff 发现浏览器脚本一行 121 字符，拆行后通过；`git diff --check` 通过。

配置历史**展示子项**源码与隔离交互验收通过；旧快照对照选择仍是 CL-03 的未完成项，不声称历史运行状态已还原。CL-01 整体仍未关闭：尚需重新生成跨语言样本、隔离 PostgreSQL 验证和其余仓库/模块当前候选门禁，不用旧 /tmp 样本补造本轮生产者证据。已定位现有 PostgreSQL 验证脚本 `scripts/enterprise-experience/deployment-postgres-check.py` 与 `scripts/personal-experience/control-api-postgres-oidc-smoke.py`，后续先核对脚本安全范围再运行；本轮未执行它们。未提交、未部署、未读取真实身份或密码。

## Batch149：CL-01 隔离 PostgreSQL 迁移与部署并发验收

本轮推进实际集成门禁，同时按用户要求分出 Qwen 的旧快照对照 UI 和 Kimi 的 Hermes 原生协议验收；本轮不修改这两条任务线的文件，不把提示词分配当成任务完成。

修复 `scripts/enterprise-experience/deployment-postgres-check.py` 的过时验收逻辑：

- r1/r2 初始迁移失败：原 `pg_isready` 默认 Unix socket 可在 PostgreSQL 镜像临时启动阶段提前成功。改为对 Alembic 实际使用的临时 loopback TCP 端点认证并执行 `SELECT 1`，有界等待；失败日志先脱敏保存再报错。
- r3 升级到 0027 成功，降级失败于 0020 的既有设备隔离保护。这是应保留的安全边界，未修改迁移。现在分别验证空库 0017→0016→head、head→0020→head，以及跨 0020 自动降级必须拒绝。
- 由于正常降级不能跨过 0020，在真实 PostgreSQL 上直接调用 0017 的原迁移 guard，验证非空部署预约拒绝删除且行数不变；这不是完整 Alembic 降级成功证明。另核对被拒的完整降级事务后版本仍为 0027、部署预约仍存在。
- 同步原部署测试新增的临时目标授权目录参数，不移除独立授权检查。没有修改产品路由、数据库迁移或防御规则。

实际执行（仓库根目录）：

```bash
apps/control-api/.venv/bin/python scripts/enterprise-experience/deployment-postgres-check.py /tmp/siq-cl01-postgres-20260926-r5
apps/control-api/.venv/bin/ruff check scripts/enterprise-experience/deployment-postgres-check.py
git diff --check
```

r4 **13 项通过**，修复最后一项 lint 后 r5 最终源码再次 **13 项通过 / exit 0**；Ruff 通过。最终证据为 `/tmp/siq-cl01-postgres-20260926-r5/result.json`、五份 migration 日志、`worker.log`、`refused-downgrade.log`。脚本 SHA-256：`256052ffd41b770ed9d183e19bd3b81fc33e0a7605ca4a4a54b0c60d68c349ad`，与结果记录一致。原失败目录 r1–r3 保留，不改写失败历史。

覆盖持久预约/重放、未知执行失败、审计失败、预约期间吊销、模拟 OpenShell 成功/适配器失败/写后审计失败，以及 `pg_stat_activity` 实测行锁争用下重复提交仅执行一次。数据库使用本机已有 PostgreSQL 17 镜像、随机 loopback 端口、tmpfs 和本轮合成身份；执行后自己的临时容器与数据库已清理，检查无该前缀残留。没有访问生产数据库或真实 OpenShell。

边界：这是**真实 PostgreSQL + 合成开发身份 + 模拟执行后端**，不是生产 IAM、真实 OpenShell 效果或全部迁移/租户隔离的最终验收。CL-01 仍需新的跨语言 wire 样本、其余模块门禁及固定候选证据；CL-02–08 原缺口不缩减。未提交、未部署、未签发。

## Batch150：CL-01 新生成 wire 样本与无跳过后端全量

从当前工作树构建本地 Go 二进制到 `/tmp/siq-cl01-batch-wire-rmypql/agentshield`，不覆盖仓库二进制或内嵌 UI。运行现有个人批量撤权浏览器验收生成真实计划/请求/结果，本轮仅增强该验收脚本的临时 HOME/XDG 隔离、浏览器只允许测试源且阻止 Service Worker、子进程退出超时兜底。未修改个人端或企业端产品代码。

实际命令及结果：

```bash
# apps/agentshield
go build -o /tmp/siq-cl01-batch-wire-rmypql/agentshield ./cmd/agentshield
# 仓库根目录
/home/maoyd/miniconda3/bin/python scripts/personal-experience/personal-console-smoke.py --binary /tmp/siq-cl01-batch-wire-rmypql/agentshield --out-dir /tmp/siq-cl01-batch-wire-rmypql/evidence
# apps/control-api
SIQ_BATCH_WIRE_SAMPLE=/tmp/siq-cl01-batch-wire-rmypql/evidence/batch-contract-output.json uv run pytest -o addopts='' -q app/tests/test_grant_batch_contract.py
SIQ_BATCH_WIRE_SAMPLE=/tmp/siq-cl01-batch-wire-rmypql/evidence/batch-contract-output.json uv run pytest -o addopts='' -q
# 仓库根目录
/home/maoyd/miniconda3/bin/python scripts/enterprise-experience/audit-query-wire-check.py --out-dir /tmp/siq-cl01-audit-wire-20260926-r1
# edge/agent
go vet ./... && go test -race -count=1 ./...
```

- 个人浏览器隔离流程 **6 项通过**；新样本契约 **6 passed**；带新样本的后端全量 **1770 passed，0 skipped，1 条既有 Starlette 弃用 warning，110.50 秒，exit 0**。此前缺样本的 skip 本轮实际执行，没有删除或绕过测试。
- 原生二进制 SHA-256：`e896f6f79f6934d697bb8a312e5db68b9e0b90754f38026514653b57f214de97`；新批量样本 SHA-256：`9a6126a8408ea67cb36501a08d2b56a1ef03c8d1044038736f86aafdd4a6dd75`。样本是临时合成待审批授权的撤除，不是生产权限操作。
- 已查看桌面预览及小屏截图。小屏截图保存的是横屏页面上部，未覆盖全部确认区，不能据此宣称完整移动交互视觉验收；本批以新 wire 生产/消费为目的，不修改 UI。二进制包含已有内嵌 UI，未重新构建个人前端，因此不当作最新个人前端源码验收。
- 审计 wire 新生成样本，后端 **2 passed**、真实前端 `getListPage/parseListMeta` 消费者 **11 passed**；报告及双侧日志在 `/tmp/siq-cl01-audit-wire-20260926-r1/`。样本 SHA-256：`bef19d50ee3afe301521e2e0175593821a3a92313c9464135844684cf8bbc4e6`。这条链路是隔离 TestClient/SQLite 和 fetch 回放，不代表真实 IAM/Gateway/PostgreSQL。
- Edge `go vet` 及四包 `go test -race -count=1` 全部通过。修改的浏览器脚本 Ruff 通过，`git diff --check` 通过。

临时本地服务已由脚本退出并清理本次状态目录，保留非秘密的样本/截图和二进制证据。没有使用真实用户配置、设备、授权或密钥，没有部署、提交、签发。CL-01 的上述集成缺口推进，但尚缺其余模块/防御基线与最终源码身份冻结；各收口包未宣称完成。

## Batch151：CL-01/07 安全核心与采集器回归、持续盘点缺口核对

本轮只运行现有测试和交叉编译、核对源代码，不修改产品或并行开发者文件。

- `apps/agentshield`：`go vet ./... && go test ./...` exit 0，全模块通过；部分包命中 Go 缓存，如实保留，不称全部重新执行。
- 另执行 `go test -race -count=1 ./internal/rulepack ./internal/threat ./internal/admission ./internal/receipt ./internal/grant ./internal/provenance ./internal/skillcontext ./internal/runtimecheck`：**8 包全部通过，无缓存**。保留共享规则、防注入/准入、回执、授权、来源 Authority、技能执行上下文及运行时检查的既有测试，没有删除或弱化断言。
- `connectors/openclaw` 与 `connectors/directory` 各执行 `go vet ./... && go test -race -count=1 ./...`：均 exit 0。Hermes 原生协议任务已分给 Kimi，本轮不修改或重复宣称其交付。
- 当前安全二进制对 linux/amd64、linux/arm64、darwin/arm64、windows/amd64 的 `go build ./cmd/agentshield` 全部成功，输出各自位于 `/tmp/siq-cl01-cross-build-b9fFuM/agentshield-<os>-<arch>`，不覆盖仓库产物。交叉编译不代表目标 OS 原生验收或正式发行。

另核对 CL-02 持续盘点缺口：`edge/agent/initial_scan.go` 的 `requested` 在首次请求成功后保持 true，`serve.go` 仅循环心跳与任务领取；后端 `routers/initial_scan.py` 按 `EdgeInitialScan(edge.id)` 重放同一任务集合。因而当前自动首扫、首扫失败退避和后台领取已存在，但不能据此声称周期性重扫。不能简单去掉 `requested` 或更换 plan ID 绕过首扫幂等；后续需要明确范围确认与周期/预算的合同、持久调度去重和暂停/吊销边界，然后实现并测试。该缺口仍归 CL-02/ENT-007，不新增另一套安装器，也不在真实设备上默认开启周期扫描。

本轮未跑完整跨平台适配器原生攻击/恢复矩阵，也未固定最终源码身份；CL-01/07 未关闭。未提交、未部署、未签发。

## Batch152：CL-02 有界持续发现意图与时间槽基础

依据首扫源码缺口，先新增 `packages/contracts/enterprise-discovery-schedule.v1.md`，不修改旧安装计划/首扫合同。新增 `app/discovery_schedule.py` 与 `app/tests/test_discovery_schedule.py`：严格意图载荷绑定安装计划摘要和设备、显式时间窗口/间隔/预算；零隐式默认，拒绝额外字段和布尔/字符串数字。初版支持边界为间隔 900–86400 秒、窗口最多 30 天、最多 2880 轮，不为真实用户自动选择或启用这些值。

纯时间槽计算采用显式带时区时间和微秒边界，当前槽之外不补发积压，预算按已预约轮数而非经过槽数计；暂停/到期/耗尽不产生新槽，时钟回退或同槽不重复；矛盾计数与状态失败关闭。摘要绑定检查仅检查调用者已验证值的一致性，不冒充设备身份认证。

新增 **34 项测试通过**；与既有首扫、安装计划结构/签发测试合跑 **152 passed，1 条既有 Starlette warning，exit 0**；Ruff 与 diff 空白检查通过。首次合跑误用了不存在的 `test_install_plan.py`，exit 4、没有运行测试；用 rg 定位真实文件后按以下命令成功执行，不隐藏该命令错误：

```bash
# apps/control-api
uv run pytest -o addopts='' -q app/tests/test_discovery_schedule.py app/tests/test_initial_scan.py app/tests/test_enterprise_install_plan.py app/tests/test_install_plan_issuer.py
uv run ruff check app/discovery_schedule.py app/tests/test_discovery_schedule.py
```

本轮新增模块没有挂载接口、创建任务或改变旧用户行为。合同明确后续持久唯一预约/审计事务、设备确认来源核对、过期/暂停/吊销、未完成任务背压、Edge 范围复验和安装交互仍需实现；纯函数返回不是执行授权。完整持续扫描仍未交付，下一批继续数据库模型/迁移与事务测试，不以本基础关闭 CL-02/ENT-007。未提交、未部署、未扫描真实目录。

## Batch153：CL-02 周期计划与轮次持久结构、迁移保护

新增 `DiscoveryScheduleRecord`、`DiscoveryScheduleRun` 及迁移 `0028_discovery_schedule.py`。对已有环境/设备增加有界复合唯一键，为新计划租户→环境→设备链提供数据库外键；每轮 `(schedule_id, slot)` 主键与父计划租户复合外键防止重复槽/跨租户关联。默认 pending_confirmation，不回填、自动激活旧设备；计数/最后槽、状态、预算、正向窗口及 revision 有 CHECK。没有历史级联删除，非空计划或轮次阻止降级。

新增 `test_discovery_schedule_migration.py` 在临时 SQLite 中实际 upgrade/downgrade/reupgrade 并插入合成数据，验证上述拒绝、父记录删除拒绝和失败降级保留版本/行数。与 Batch152 合跑 **35 passed**；原首扫、租户隔离、配置历史迁移、凭据轮换迁移 **20 passed**，均 exit 0、仅既有 Starlette warning。Ruff 与 diff 检查通过。

同步 PostgreSQL 验收脚本：升级后记录实际 migration head，再比较拒绝降级后仍是同版本，不继续硬编码 0027。执行：

```bash
# 仓库根目录
apps/control-api/.venv/bin/python scripts/enterprise-experience/deployment-postgres-check.py /tmp/siq-cl01-postgres-0028-r1
# apps/control-api
uv run pytest -o addopts='' -q app/tests/test_discovery_schedule_migration.py app/tests/test_discovery_schedule.py
uv run pytest -o addopts='' -q app/tests/test_initial_scan.py app/tests/test_tenant_isolation.py app/tests/test_role_configuration_migration.py app/tests/test_credential_rotation_migration.py
```

临时 PostgreSQL **13 项通过**，head=0028，证据 `/tmp/siq-cl01-postgres-0028-r1/result.json` 及迁移/worker 日志；执行后测试容器已清理，无此前缀残留。这证明迁移可在 PostgreSQL 回放且原部署并发/审计链保持通过；新周期表的数据约束负例目前在 SQLite 执行，尚不称周期预约已通过 PostgreSQL 并发验证。

本轮未实现 HTTP/确认来源核对、任务创建与审计原子预约、暂停恢复或 Edge 安装接入；存储结构中的 active 字段不是授予激活权限。下一批继续事务执行器和负向测试，CL-02/ENT-007 仍未完成。未提交、未部署、未运行真实设备扫描。

## Batch154：CL-02 内部周期预约事务与失败回滚

新增 `app/discovery_scheduler.py`、`app/tests/test_discovery_scheduler.py`，合同补充内部预约边界。函数仅接受调用者已验证租户/设备，未挂载 HTTP 或后台：按租户→设备→计划行锁顺序复验租户 active、设备未吊销、计划/摘要/投影一致、原 install.plan.create 和本设备 scan.schedule.confirm 精确审计引用。没有确认来源事件即拒绝，不因数据库 status=active 就跳过确认。

当前槽新预约复验能力新鲜度/版本，严格沿用范围并区分 SKILL.md 与普通扫描；同设备非终态任务形成背压，预算到期/暂停不创建；签名任务、轮次、计数/revision、审计和 outbox 在 savepoint 中原子写入，最终 commit 由调用者控制。同槽返回原任务，缺失原任务拒绝而不新建替代。

首轮 4 失败/7 通过：既有开发身份夹具没有实际 Tenant 行，正确触发租户拒绝，导致正向和故障注入未到目标步骤。新增合成租户并让负向测试校验精确错误类别后通过，不放宽产品租户检查。另修复新增文件 lint。最终新增 **17 项**，与纯函数/原首扫合跑 **59 passed / 1 条既有 warning / exit 0**：包含同槽无新增写、下一槽背压、完成后新轮次、租户/设备/吊销/摘要/确认/过期能力/版本拒绝，签名/outbox/审计三个阶段故障完整回滚、暂停/期限/预算、原任务丢失不重放。

```bash
# apps/control-api
uv run pytest -o addopts='' -q app/tests/test_discovery_scheduler.py app/tests/test_discovery_schedule.py app/tests/test_initial_scan.py
uv run ruff check app/discovery_scheduler.py app/tests/test_discovery_scheduler.py
```

Ruff 与 diff 检查通过。现阶段是 SQLite 合成确认事件验证，真实确认入口、PostgreSQL 周期预约并发、暂停/恢复路由、Edge/安装确认尚未接通。租户锁只串行化本模块；旧手工任务入口未使用相同锁，不宣称全系统配额并发闭环。下一步优先补真实 PostgreSQL 并发及确认接入，不部署、不操作真实设备。CL-02/ENT-007 保持未完成。

## Batch155：CL-02 周期预约 PostgreSQL 实际竞争与保护验证

新增独立 `scripts/enterprise-experience/discovery-schedule-postgres-worker.py`，仅由已有临时 PostgreSQL 验收驱动设置专用标记后调用，校验 loopback PostgreSQL/开发模式。复用同一迁移数据库，创建独立合成租户、设备、计划和确认事件；没有 HTTP 登录、真实扫描或外部执行。驱动保存脱敏 worker 日志及源码摘要。

两个独立数据库会话同时预约同槽，第一事务在审计点停住；通过 `pg_stat_activity.wait_event_type='Lock'` 确认第二事务实际等待数据库锁，而非仅线程先后。释放后结果 ID 一致，数据库只有一轮、一组任务和一条预约审计，预算/revision 只增加一次。下一槽注入审计异常并由调用者捕获，任务/轮次/审计/outbox 行数及计数/槽/revision 全部保持不变。

另直接插入重复槽、跨租户轮次，核对 PostgreSQL 的准确主键/外键约束名，避免因其他错误误判负例通过；尝试有记录的 0028→0027 降级明确拒绝，版本与轮次仍保留。

首次 r1 **16 项通过**，新增直接约束和降级检查、修正两项 lint 后，最终执行：

```bash
apps/control-api/.venv/bin/python scripts/enterprise-experience/deployment-postgres-check.py /tmp/siq-cl02-scheduler-postgres-r2
apps/control-api/.venv/bin/ruff check scripts/enterprise-experience/discovery-schedule-postgres-worker.py scripts/enterprise-experience/deployment-postgres-check.py
git diff --check
```

最终 **18 项通过 / exit 0**（原部署检查 13 + 新周期检查 5），Ruff/diff 通过。报告与迁移、预约、拒绝降级日志在 `/tmp/siq-cl02-scheduler-postgres-r2/`，head=0028；worker SHA-256 为 `ce5d608f0fd053d53ef5437e03f37f6656fc447ca7ef675ab7fc1e853fb23c40`。执行后自己的临时容器已清理并确认无此前缀残留。

这补齐周期事务的本轮 PostgreSQL 并发证据，不代表真实用户确认、Edge 调度、系统级配额竞争或安装闭环已完成。确认事件仍为合成夹具；下一步须完成受控确认/停用入口与本机明确确认，而不是默认将存量设备设为 active。未提交、未部署，CL-02/ENT-007 未关闭。

## Batch156：CL-02 待确认计划管理与撤销入口

新增 `routers/discovery_schedules.py`、对应管理测试并在 main 注册；合同先补组织管理行为。POST 环境下 discovery-schedules 只保存 pending_confirmation，要求 env:manage+edge:manage、认证租户内环境/设备、设备未吊销、原计划精确签发审计和绑定摘要；请求无状态/权限覆盖字段。相同意图 ID/摘要幂等返回，不同内容拒绝，没有创建扫描任务或设备确认事件。

POST 单计划 revoke 先对象定位再权限核对，按租户→设备→计划锁序和 expected_revision 做 CAS；已撤销重试不再写审计。只阻止未来轮次，不删除历史或伪称取消已执行采集；没有管理端直接激活或恢复权限。创建/撤销审计失败时数据库回滚，响应为 no-store 的最小状态/摘要投影，不返回设备秘密或原路径。

新测试 **9 项**；与内部调度、旧首扫和安装计划签发合跑 **54 passed / 1 条既有 warning / exit 0**，Ruff/diff 通过。包括仅待确认且无任务、幂等/冲突、跨租户/缺权限、禁止 status 覆盖、伪造计划（即使摘要自洽）、错误摘要、吊销/缺失设备、版本 CAS/布尔拒绝、两种审计失败回滚。

```bash
# apps/control-api
uv run pytest -o addopts='' -q app/tests/test_discovery_schedule_management.py app/tests/test_discovery_scheduler.py app/tests/test_initial_scan.py app/tests/test_install_plan_issuer.py
uv run ruff check app/routers/discovery_schedules.py app/tests/test_discovery_schedule_management.py
```

当前没有 Edge 确认/周期轮询消费者、安装 UI 或激活入口；管理路由不调用任务预约。上述请求仅在隔离 TestClient/合成数据执行，没有向在线服务创建计划或撤销真实调度。下一步继续签名设备确认与本机明确确认、Edge 持久状态与服务接入；CL-02/ENT-007 未完成，未提交/部署。

## Batch157：CL-02 设备签名确认入口

新增 `routers/discovery_schedule_confirmation.py`、测试并在 main 注册；合同补精确签名字节、时间窗口、幂等与声明边界。设备确认同时要求当前设备凭据与其 Ed25519 签名，绑定控制面 origin、环境、设备、计划 ID、意图/原安装计划摘要及 expected_revision；锁后复验凭据未轮换/吊销。首次确认只允许 pending_confirmation，5 分钟内非未来确认、未过期计划和组织创建/安装签发审计仍存在；复核 JSON 摘要与存储投影一致。

只在同一事务将状态置 active、revision+1 并追加绑定请求摘要的确认审计，不创建任务。完全相同签名请求重试不重复审计；不同请求、paused/revoked 或过期不能恢复。user_confirmed 只接受真实布尔 true，不接受 false/1/字符串；其含义是设备签名声明，不伪称服务端直接观测人类操作。配套本机 CLI 尚未实现，签名密钥不能交给模型/页面。

新增 **15 项测试**；与管理、预约、凭据轮换合跑 **59 passed / 1 条既有 Starlette warning / exit 0**，Ruff/diff 通过。覆盖真实合成 Ed25519 签名、错误签名/另设备密钥、origin/摘要/版本替换、过期/未来确认、布尔强制、管理身份不能代替设备凭据、审计失败回滚、存储投影/签发或创建来源异常拒绝、旧确认不恢复已撤销计划。

```bash
# apps/control-api
uv run pytest -o addopts='' -q app/tests/test_discovery_schedule_confirmation.py app/tests/test_discovery_schedule_management.py app/tests/test_discovery_scheduler.py app/tests/test_credential_rotation.py
uv run ruff check app/routers/discovery_schedule_confirmation.py app/tests/test_discovery_schedule_confirmation.py
```

全部为隔离 TestClient 与临时合成设备密钥，未使用真实凭据或在线接口。下一步仍需 Edge 精确载荷/签名消费者、本机明确确认与持久恢复，然后才接周期轮询和安装交互；不把服务端确认接口等同完整用户旅程。未提交/部署，CL-02/ENT-007 未完成。

## Batch158：CL-02 Edge 严格解析和确认签名字节对等

新增 `edge/agent/discovery_schedule.go`、Go 测试及 `app/tests/test_discovery_schedule_go_wire.py`。解析拒绝重复键、大小写别名、额外/缺失字段、null/布尔或字符串数字、超大载荷、越界周期和不合法日期；UTC 最多微秒且拒绝 Python 不支持的公元 0 年。准备确认需要显式 confirmed、未过期周期、当前安装计划 compact 完整性及 canonical 摘要、相同 origin/环境/设备、匹配的私钥/公钥；无隐式扩展范围，不写 State、不读真实文件、不联网。

签名字节复用 Edge canon，与服务端 ensure_ascii=True 一致，确认时间截断到微秒。3 个 Go 顶层测试含 11 个准备场景和多项严格解析负例；Go 导出函数只在测试变量明确提供新路径时排他写非秘密样本。Python 测试实际执行当前 Go 测试生产者，再用真实 ConfirmSchedule、DiscoverySchedule 核对摘要/签名字节和公钥验签，修改 origin 后验签拒绝，不使用手写响应代替生产者。

- Edge `go vet ./... && go test -race -count=1 ./...` 四包全部通过；补充公元 0 年负例后再次执行本任务聚焦 race 测试。
- Python `uv run pytest -o addopts='' -q app/tests/test_discovery_schedule_go_wire.py --basetemp /tmp/siq-schedule-confirm-wire-qPSjY7/pytest`：**1 passed**，Ruff 通过。样本 `/tmp/siq-schedule-confirm-wire-qPSjY7/pytest/test_go_confirmation_bytes_dig0/confirmation.json` 仅含合成意图、请求、公开验签材料，无私钥或凭据。
- gofmt 与 diff 检查通过。

本轮仅纯函数和跨语言证明，没有 CLI、确认日志/发送、自动轮询或本机真实确认；不能因准备函数接受 confirmed=true 就宣称用户已授权。下一步仍需私密待确认日志及用户明确交互，再接 HTTP 与服务恢复。未提交/部署，CL-02/ENT-007 未完成。

## Batch159：CL-02 Edge 确认单次传输与响应边界

新增 `edge/agent/discovery_schedule_transport.go` 与测试；合同补传输行为。方法验证请求形状、同设备、明确 confirmed、精确 origin 与 Client 匹配，单次 POST 传输，不跟随重定向、不自动重试、不改变本地身份/状态。响应有界 4096 字节，拒绝重复/大小写别名/null/额外或缺失字段/尾随对象，只接受原计划和摘要的 active 状态以及增加的 revision；固定脱敏错误，不回显上游正文。

2 个 Go 顶层测试覆盖 15 种响应场景以及跨 origin 零请求、重定向目标零请求、取消后不发送。`go vet ./... && go test -race -count=1 ./...` Edge 四包全部通过，gofmt/diff 检查通过。全部 HTTP 为 httptest loopback 模拟，未向真实后端发确认，不将此模拟传输当作完整 Go→API 原生旅程。

持久确认日志与本机明确交互尚未实现，该方法没有 CLI/serve 调用，不能跳过发送前日志步骤；下一步继续日志与恢复并接入明确命令，然后补真实隔离 Go→API 验收。未提交/部署，CL-02/ENT-007 未完成。

## Batch160：CL-02 Linux 私密待确认日志与原请求恢复

新增 `edge/agent/discovery_schedule_journal_linux.go` 与测试；合同补日志协议。状态目录内固定待确认文件经逐级无链接路径与所有者/私密权限校验后使用 pinned directory + openat O_EXCL 创建为 0600，文件与目录同步；已有文件/部分写入不覆盖或删除。只保存意图、非秘密状态摘要和精确签名请求，原 state.json 不修改，设备 secret/签名 seed 不写入日志。

读取复用安全状态文件检查，限制 16384 字节，拒绝符号/硬链接、权限不安全、重复或别名字段/null/异常结构；核对本地安装范围与状态基线，以原 confirmed_at 重建确定性签名，确保恢复不更换时间或请求。状态基线排除可轮换 secret，但仍绑定签名身份、设备、控制面和原计划。旧日志可读取用于恢复核对不等于重新授权或延长截止，服务端继续拒绝过期。

3 个 Go 顶层测试覆盖排他持久/权限/无秘密/原样恢复、4 种未确认或状态/范围不匹配零写，以及 10 种不安全文件/篡改拒绝；全部在本轮临时目录。`go vet ./... && go test -race -count=1 ./...` Edge 四包通过，gofmt/diff 通过。

这些仍是内部日志函数，要求调用者持有任务锁；尚无 CLI 或自动发送调用，也未存储确认成功回执。下一步继续明确交互命令、发送失败恢复和成功状态读回，再接周期服务。未读取真实设备身份、未确认真实计划、未提交/部署，CL-02/ENT-007 未完成。

## Batch161：CL-02 明确确认 CLI、原请求恢复及成功回执

新增 Linux `confirm-discovery-schedule` 命令、非 Linux 明确拒绝入口及 CLI 测试，并注册 main/help。默认 `--intent FILE` 只核对绑定并展示设备/租户/环境/origin、原安装范围、周期/预算/截止与摘要，不创建确认签名、日志或请求；为此将绑定检查与签名准备拆开。显式精确 `--confirm-intent-sha256` 才先持久日志再单次发送。`--resume` 不接受新文件，只有相同摘要才发原日志请求，不刷新签名时间；服务持任务锁时拒绝，不自动停止服务。

成功后以 pinned 目录、O_EXCL、0600 和同步追加确认回执，关联原请求摘要；同请求重试保留既有历史回执，部分或未知内容拒绝覆盖，待确认日志保留。回执只是一次 active 读回，不是扫描执行或持续保护证明。没有命令启动服务或改变业务权限。

2 个新增 Go 顶层测试覆盖默认预览、摘要/范围展示且无秘密、错摘要零请求、日志先于发送、网络失败留存、拒绝重新创建、同字节恢复、回执排他重试、服务锁、过期与未知回执保留。`go vet ./... && go test -race -count=1 ./...` Edge 四包通过；Go→Python wire 与服务端确认测试 **16 passed**。Linux arm64/amd64、Darwin arm64、Windows amd64 构建通过，独立产物 `/tmp/siq-edge-schedule-cli-build-XJuuyy/`，非 Linux 构建不代表支持该命令或原生通过。gofmt/diff 通过。

验证使用临时状态与注入模拟 transport；实际 Client 的 httptest 已在 Batch159 验证，仍需完整 CLI→真实隔离 API 原生验收。尚缺周期轮询、服务接入、安装 UI 自动衔接和新计划替换生命周期。首次请求未被服务端接收而超过确认时效时不能自动重新签名；当前应明确报错保留材料，后续新确认/安全换代流程仍需补齐，不以复用过期签名关闭恢复要求。未操作真实设备、未提交/部署，CL-02/ENT-007 未完成。

## Batch162：CL-02 已确认计划的设备轮询入口

在既有设备确认路由新增 POST `/edge/v1/discovery-schedules/tick`，合同先补精确三字段请求与结果结构。设备凭据定位租户/环境，采用租户→设备→计划锁序，锁后核对凭据未轮换、设备未吊销/迁移；范围不匹配 404，摘要或预约完整性失败返回固定 409。只用服务端时间调用既有预约事务，不接受客户端范围、时间或预算覆盖。没有改变心跳或 GET 领取接口的授权语义。

返回已预约任务 ID 或空列表，no-store；active 仅为计划状态，不代表本次派发或保护生效。未确认/暂停/撤销/过期计划不能因此激活。任务、轮次、计数、审计和 outbox 仍在同一事务；同槽幂等，原领取和签名验证流程不变。

新增 `app/tests/test_discovery_schedule_tick.py` 三个集中用例：实际隔离 HTTP 创建待确认计划→真实合成签名确认→轮询→重复→领取→撤销；管理身份/摘要/范围/参数覆盖拒绝；审计失败回滚任务/轮次/计数。与确认和预约回归合跑 **35 passed**；修正测试 fixture 获取写法后聚焦 **3 passed**；Ruff 通过。仅保留既有 Starlette 弃用 warning，没有运行无关全量测试。

命令（apps/control-api）：`uv run pytest -o addopts='' -q app/tests/test_discovery_schedule_tick.py app/tests/test_discovery_schedule_confirmation.py app/tests/test_discovery_scheduler.py --tb=short`。未调用真实设备接口，未提交/部署。Edge 后台轮询消费者、安装交互与原生服务旅程仍待接通，CL-02 未完成。

## Batch163：CL-02 Edge serve 消费已确认周期计划

新增 Linux 周期消费者和非 Linux 编译占位，在既有 serve 持锁流程接入：无周期日志保持原流程；有日志必须安全读取并核对本机原确认与成功回执，缺回执/身份变化拒绝启动。周期窗口内心跳成功后单次 POST tick，严格响应验证并拒绝重定向；请求只含版本、计划 ID 与意图摘要，不携客户端时间/范围。返回任务 ID 不执行，复用既有独立任务循环验签和回执。

失败 30 秒至 15 分钟独立退避，不降低健康心跳频率；非 active 状态停止本次生命周期轮询，到期不继续请求，不续签或扩预算。未确认材料不自动激活，不修改本地日志或真实设备状态。

新增三个集中 Go 测试覆盖私密回执前提/身份替换、窗口/退避/停止、模拟 HTTP 请求与响应拒绝场景。执行 `go test -race -count=1 -run 'TestSchedule|TestServe' .` 通过，`go vet ./...` 及 diff 检查通过。仅相关回归，不重跑整个项目全量。

仍需安装交互衔接、确认换代恢复和同一候选的真实原生服务/API 旅程。本轮只临时合成状态和 loopback httptest，未启用真实周期扫描，未提交/部署，CL-02 保持未完成。

## Batch164：CL-02 服务安装前复验周期确认材料

安装器此前可能先配置/启用服务，再由 serve 拒绝未完成周期确认。本轮将同一校验前移至持锁读取身份后、写 unit/调用 systemd 前；专用固定错误提示恢复原确认，不删除日志、不隐式确认。不带周期日志仍走原流程。完整回执只解除此项前置阻断，不绕过计划有效期或发行验签。

修改 `edge/agent/install_user_service_linux.go` 和既有测试，新增一个集中用例覆盖配置/启动两种路径均在待确认时拒绝且不写 unit、日志保持原字节、保存合成回执后仍拒绝缺失发行材料。执行 `go test -race -count=1 -run 'TestPendingSchedule|TestUser|TestUnconfirmed|TestCancelledUser|TestSchedulePoll' .`、`go vet ./...` 及 diff 检查通过。全部临时合成状态，没有实际 systemctl/网络/设备操作。

这只完成安装与后台确认校验衔接；新设备获取周期计划、简化交互、确认换代和原生安装闭环尚待完成。未提交、未部署，CL-02 未关闭。

## Batch165：CL-02 按计划 ID 获取并预览周期意图

控制面新增指定 ID 的设备只读 GET，按当前凭据定位租户/环境/设备并锁后复验，返回精确意图/摘要/状态/revision，不返回安装路径或凭据，不创建审计、确认或任务。摘要/投影异常 409，错范围 404。新增集中测试核对字段、原意图一致、零业务写入、管理身份拒绝、错租户及损坏记录；与确认回归 **19 passed**，Ruff 通过（上一轮文档交付期间已收回实际测试结果）。

Edge `confirm-discovery-schedule --schedule-id ID` 已接该 GET，与文件/恢复模式互斥。只读获取后仍检查本地安装绑定、窗口和规范化摘要，默认展示范围而不签名确认；明确摘要参数才复用原日志先行、发送和回执流程。客户端拒绝重定向、重复/额外字段、非法 ID、摘要/设备不符和非 revision=0 待确认状态；已确认请求须通过 --resume 恢复，不能重新获取后自动签发。

新增客户端集中模拟 HTTP 测试，`go test -race -count=1 -run 'TestSchedule|TestConfirmSchedule' .`、`go vet ./...` 与 diff 检查通过。没有运行无关全量，也没有实际设备请求。GET 默认预览的网络行为已写入帮助与合同，不能称其完全离线。

尚缺安装器从组织侧创建到设备确认的便捷衔接、确认换代和同制品原生旅程；不将 HTTP 模拟当成生产验收。未提交、未部署，CL-02 未完成。

## Batch166：既有设备安装编排接入周期确认

setup-enterprise 新增可选计划 ID/原请求恢复与独立周期摘要参数，复用已有 confirmSchedule，不创建第二套签名/恢复机制。在暂存与采集范围确认后、配置/启用服务前完成周期确认；失败或取消停止后续阶段，材料保留。没有周期参数时原行为不变，交互 yes 不自动转为周期同意。

因为组织周期计划绑定已存在的设备，周期参数只允许 registered 身份；新注册/待恢复注册不能携这些参数进入准备，避免半途注册后才发现 ID 不适用。新设备注册→组织创建周期计划→本机确认的一步体验仍未闭合，不能因编排已接就宣称自动安装全部完成。

恢复口径复核：安装合同要求 current installation window，不能用已注册身份自动延长安装资格。安装器现先核对结构/目标/本地摘要，再对过期或尚未生效计划返回专用 `user_service_install_plan_outside_window`，提示取得并明确确认新计划，保留身份与暂存材料；未绕过发行验签，也不自动替换周期日志。新增过期计划零 unit 写入且身份逐字节保留的回归。原 pending-schedule 测试使用历史安装计划，之前的通用失败并不能证明已走到发行校验；本次把断言和注释准确收紧到安装窗口拒绝。周期确认换代仍为未完成项。

新增两个集中测试（顺序/失败停止、参数与帮助），与既有安装和确认用例执行 `go test -race -count=1 -run 'TestEnterpriseSetup|TestSetup|TestConfirmSchedule' .` 通过，`go vet ./...` 通过。仅注入合成动作，无真实 systemctl/设备请求；合同说明混合人类可读确认与 JSON 阶段输出。未提交、未部署，CL-02 未关闭。

## Batch167：周期意图终端确认收口

完成此前在途的 `confirm-discovery-schedule --interactive`：省去用户复制摘要，先展示原范围/周期/预算/期限，再由终端精确 yes 确认；默认取消，不支持管道代答，不将范围确认等同于业务授权。等待后重取当前时间检查到期；继续复用持久日志和原请求恢复，不增加自动续签。无参数预览与原摘要方式保持不变。

新增三个集中测试，覆盖 yes/CRLF、空输入/EOF/大小写/空白/过长拒绝、输出失败、取消、非终端及冲突参数在状态写入和发送前拒绝。`go test -race -count=1 -run 'TestScheduleInteractive|TestConfirmSchedule' .` 与 `go vet ./...` 通过；仅合成输入/临时目录，未进行真实设备确认或原生终端安装验收。

该交互只用于独立周期确认 CLI，setup 的交互与周期参数仍互斥。新设备组织计划衔接、日志换代与同制品原生安装旅程未完成，CL-02 保持开放。发行工具辅助线已独立复核 17 项通过，记录见 `enterprise-release-tools-closeout-handoff.md` 第 9 节；不代表签发发布完成。未提交、未部署。

## Batch168：安装交互独立周期确认衔接与服务状态复核

既有设备 setup-enterprise 的 --interactive 现在可携 --schedule-id 或 --resume-schedule：首次安装范围确认不再要求用户复制周期摘要，而是在独立周期步骤再次显示意图并要求 yes。第二次取消或失败阻止服务安装；禁止交互模式同时传周期摘要，非交互仍要求精确摘要。仅既有 registered 设备适用，新设备不自动创建周期或业务授权。此增量取代 Batch167 的 setup 互斥限制。

修改 setup 实现及测试，新增集中参数映射与第二次确认取消阻止服务用例；复用既有确认 CLI。执行 `go test -race -count=1 -run 'TestEnterpriseSetup|TestSetup|TestScheduleInteractive|TestConfirmSchedule' .`（通过，1.235s）、`go vet ./...`（通过）。全部使用合成输入/动作，未验收真实终端、网络、发行安装或 systemctl。

GLM 服务状态交付已检查实现和全部七个相关测试，独立执行 `go test -race -count=1 -run '^TestUserServiceStatus' .` 通过。取消后拒绝、帮助零执行、输出失败传播成立；固定 unit、20 秒超时、4096 字节上限和三项 verified=false 保留。详见服务状态交接第 7 节。Qwen 新任务仅占用 discovery_scheduler.py 与其测试，主线未修改它们。

仍未完成：新设备组织计划衔接、确认日志换代及同制品原生安装闭环。未提交、未部署，不关闭 CL-02/07 或总目标。

## Batch169：终端确认持久化边界与合同现状整理

复用现有 Linux PTY 夹具，对 confirmSchedule 的完整终端路径做一个四场景集中回归：yes 在范围/摘要展示后确认，发送前原请求已持久化且随后保存回执；取消、提示输出失败、初读时有效但回答后已过期均无确认发送、无日志/回执。过期使用不同的初读时间与回答后真实时间，不等待时钟、不增加生产时钟开关。检查不回显合成凭据/种子。

`go test -race -count=1 -run '^TestConfirmScheduleTerminalConsentJournalBoundary$' .` 通过（1.148s），`go vet ./...` 通过。这是本机真实 PTY、合成状态、注入传输的验证，不是正式二进制/真实控制面/原生安装全链路。未跑无关全量。

将周期合同中过时的“尚无 CLI/HTTP/轮询”等历史状态更新为当前实际调用链，消除 setup 交互互斥描述冲突，不更改 wire 字段或授权语义。明确固定日志不能换代、首次确认从未送达且超过五分钟不能靠 resume 续期；已接收丢响应按原幂等规则恢复，不把保留文件当作所有故障均可恢复。

并行边界：Qwen 拥有预约重放实现及测试，GLM 拥有周期轮询取消实现及测试；本轮未修改两者。新设备组织计划衔接、日志换代与真实安装仍未关闭。未提交、未部署。

## Batch170：周期确认失败的恢复分支纠正

原 setup 将所有周期失败都提示恢复原请求，但取消/显示失败时可能尚无日志；确认发送失败与本地回执保存失败也不可区分。本轮拆为固定 `confirmation_result_unknown` 与 `confirmation_receipt_not_saved`，保留 discovery_schedule_unconfirmed 错误类别和原材料，不重发、不续签、不覆盖。setup 只透传这两个本地可信错误类别，其他失败用固定阶段提示，不泄漏上游正文。说明“本次未进入服务安装”，不声称既有服务已停止或远端一定未确认。

已有网络失败/原请求恢复及部分回执拒覆盖测试收紧为精确错误类别；新增一个集中用例验证 setup 白名单传递、未知错误脱敏及服务步骤零执行。定向 `go test -race -count=1 -run 'TestConfirmSchedule|TestSetupSchedule|TestSetupSecondConsent' .`、`go vet ./...` 通过。未触碰 Qwen/GLM 文件，未进行真实设备操作；固定日志换代和新设备组织计划衔接仍未解决。未提交、未部署。

## Batch171：两框架角色—技能缺口按代码定位

只读核对 Hermes/OpenClaw 候选生产者、来源/选择/目录验证器和来源对照合同，确认 Hermes 当前只上报 profile 和工具集，没有 framework_source/skill_selection/skill_source_roots；框架来源后端解析器只接受 OpenClaw。OpenClaw 已有声明选择与目录来源，但对照合同明确只证明历史来源关系，不证明精确角色安装或实际加载。

已将五层对照矩阵、代码位置和下一步顺序写入收口清单 CL-03：先解决采集/版本化来源验证，再关联安装观察，不按同名或工具集造节点。此次没有修改业务代码、没有运行测试、不新增通过数量；没有把测试文件存在当作测试已通过。Qwen/GLM 在途文件未动；CL-03/04 保持未关闭。

## Batch172：Hermes 配置来源生产与入库校验

新增 enterprise-framework-source/v2 合同，仅用于 Hermes 完整 config.yaml 观察；OpenClaw v1 保持原样。Hermes 使用既有 profile 目录哈希身份与本批配置证据摘要/引用上报，不读新目录，不将 toolsets 变为 Skill；被截断或未授权 config.yaml 时不产生来源。后端严格核对版本/框架配对、hermes 任务、profile 类型/定位/候选 ID/instance_key，以及本批 manifest 的 subject、配置定位和摘要。缺失来源的旧客户端继续兼容。

新增一个三场景 Go 测试（完整/截断/SOUL-only），复用原后端入库负向用例参数化覆盖两框架。相关 Go race/vet 通过；后端来源入库与旧投影回归 **36 passed**，Ruff 通过。中途整理长行时出现括号语法错误，已修复并重跑上述 36 项至通过，未放宽断言；保留既有 httpx 弃用警告。

此轮完成采集属性与签名批次入库校验；读取投影仍仅支持 OpenClaw，Hermes 来源仍显示 source_unavailable，已测试且合同明确。后续必须接通兼容读取与树消费者，不能称为完整来源链或技能关系完成。未运行真实采集/上传、全项目测试或部署，未修改并行 Qwen/GLM 文件。CL-03 保持开放。

## Batch173：Hermes 来源读取与既有树消费者衔接

后端来源投影现在可按租户/设备/环境、manifest 类型、候选 subject、完整配置摘要及 profile 配置定位复验 Hermes 证据；失败不投影。Hermes 使用 source-view/v2，OpenClaw 保持 v1；分页清单含 v2 来源时使用 inventory/v2，旧形态页面继续 v1。合同明确旧严格消费者可能拒绝新版本，发布须前后端配套，不把 Hermes 映射成 OpenClaw。

前端严格解析两个已知版本/框架配对，v1 清单拒绝嵌入 v2；既有详情只派生框架名称，树复用环境+设备+框架+实例键，不改 CSS、布局或请求流程。遵循 React 技能的派生值规则，未增加 effect/state 或逐角色请求。

验证：来源入库及原投影 36 项通过；新增 Hermes 读取/损坏定位/类型/实例/跨租户及清单一致性后，投影文件 18 项通过（这些是重叠执行，不相加为独立覆盖数量）。Ruff 通过。前端四个定向文件 78 项通过，随后新增同摘要跨框架不混并的分组回归，单独树测试 10 项通过。正式模式标准构建输出 `/tmp/siq-hermes-source-build-5g1YVG` 成功；未部署、未运行浏览器/真实设备验收，未跑全项目测试。新增最后一项为测试文件增量，生产构建对应此前已完成的业务代码。

读取源码衔接完成不等于跨语言原生采集到界面全旅程已验收；仍缺最终 wire/浏览器证据及精确角色—Skill 安装/加载关系。Qwen/GLM 在途文件未修改，CL-03 未关闭。

## Batch174：混合来源分页浏览器验收与 Hermes 树标题修复

复用现有 framework-tree-browser-smoke.py，增加首页 inventory/v1、次页混合来源 inventory/v2 的场景：相同环境/设备/instance_key 的 Hermes 与 OpenClaw 分组不能合并。首次执行实际暴露树标题写死 OpenClaw；修复为按 group.framework 派生 Hermes profile / OpenClaw 配置实例，不增加状态、effect、请求或 CSS，遵循 React 派生值规则。

框架树两个定向文件 29 项通过；正式模式标准构建成功，输出 `/tmp/siq-hermes-tree-production-rF6YL2`。隔离开发身份构建 `/tmp/siq-hermes-mock-only-xqEM9i` 仅用于模拟、不可发布。脚本重跑 16 项通过，零业务写请求、零未捕获异常；证据 `/tmp/siq-hermes-tree-fixed-20260926/report.json`。已实际查看该目录 Hermes 375/1280 截图：标题、历史/未知提示、换行正确，保留原有视觉风格。Ruff 与 git diff --check 通过。未运行全项目测试、未连接真实业务数据。

纠正 Batch173 单独树测试数量笔误：实际为 12 项而非 10 项；与本轮 29 项有重叠，不能相加。GLM 四份合同文档已复核，修正文档中实例键等于 locator 末段仅适用于 Hermes 的表达，补充其交接第 7 节。原生采集到控制面到界面的同制品全旅程及精确角色—Skill 关系仍未完成；不关闭 CL-03。未提交、未部署。

## Batch175：防止 Hermes 来源套用 OpenClaw 技能目录语义

继续 CL-03 来源关联核对时发现：role-skill-roots/v1 合同仅允许 OpenClaw + framework-source/v1，但入库函数此前只检查 framework_source 存在。Hermes v2 接通后，有效 Hermes 来源可夹带 OpenClaw workspace_skills/project_agent_skills 声明。新增真实签名合成批次负例，修复前实际返回 200 并入库，违反既有合同；现验证候选 framework/source_type 及来源版本/框架配对，固定 422 role_skill_roots_invalid，写入前拒绝。读取技能来源对照同步核对 OpenClaw 配对，历史异常组合返回 source_unavailable、declared_roots=null，不生成匹配。

复用既有两组测试，增加入库和历史投影两个参数化负例；`uv run --no-sync pytest -o addopts='' -q app/tests/test_role_skill_roots.py app/tests/test_role_skill_sources_view.py --tb=short` 最终 29 passed。中途历史夹具按复用 evidence_id 找错其他环境行导致一项失败，已加本夹具 environment_id 精确约束后重跑，不放宽历史来源必须有效的断言。修改文件 Ruff、git diff --check 通过。保留既有 Starlette/httpx 弃用警告，无新依赖。

只读核对兄弟 Hermes 源码发现 profile skills、external_dirs、受信任项目目录有独立加载规则，不能把 toolsets 当作技能选择或把 OpenClaw workspace 两根套用 Hermes。没有读取用户配置或执行 Hermes，也没有跨仓库修改。此次只修复既有合同边界，不声称 Hermes 技能安装/加载关系完成；下一步仍需独立版本化来源规则与精确安装观察衔接。GLM 周期计划管理、Qwen 调度重放文件未触碰。未提交、未部署，CL-03 保持开放。

## Batch176：Hermes profile 本地技能布局候选采集与入库

先新增 enterprise-role-skill-roots/v2 合同，定义 hermes_profile_layout / layout_candidate / profile_skills 单根，与 OpenClaw v1 的显式工作区两根分开。依据本机 Hermes 源码 get_skills_dir 返回 get_hermes_home()/skills，仅在授权完整 config.yaml 已有来源证据时，按 POSIX profile 绝对目录计算 skills 子路径摘要；不读取/创建技能目录、不跟随链接、不扩展扫描范围、不解析环境变量，未读取配置或截断不附加该属性。

后端严格接受两组已知配对（OpenClaw roots/v1 + source/v1；Hermes roots/v2 + source/v2），保留 Batch175 跨框架错配拒绝，旧生产者缺失继续兼容。属性和配置来源由原批次签名绑定，仍不是独立宿主证明。原来源对照 v1 不消费 Hermes layout_candidate，避免将布局候选误当配置声明或已安装技能。

复用三场景 Go 来源测试，增加标准库独立摘要计算与目录未创建检查；`go test -race -count=1 -run 'TestHermesSourceRequiresCompleteIncludedConfig' .`、`go vet ./...` 通过。后端原两文件追加 Hermes 合法布局、错 kind、OpenClaw 套 v2 场景后 32 passed；Ruff、gofmt、git diff --check 通过。未跑无关全量、浏览器或真实扫描。

这只是采集/入库的一段增量，下一步必须升级读取对照和既有消费者，接同设备签名安装位置证据。external_dirs、受信任项目目录、禁用/优先级和真实加载尚未由本合同覆盖，不将 profile 单根替代 CL-03 全部要求。未触 GLM/Qwen 文件、未提交、未部署，CL-03 未关闭。

## Batch177：Hermes 布局候选与签名安装观察对照接入既有 UI

新增 role-skill-sources-view/v2 合同；Hermes 同 URL 使用独立 v2 响应，强制来源 view/v2 与根 roots/v2/layout_candidate 配对。复用原分页、同设备租户范围、签名批次、任务范围与最新观察完整核验，不另建扫描或匹配管线。兼容字段 declared_roots/outside_declared_sources 在 v2 中明确仅为布局候选，不等同配置声明或拒绝权限；OpenClaw 原 v1 保留。

前端解析器只接受明确两版及配对；既有来源面板按版本派生文案，Hermes 显示单一本地布局候选和外部/项目/加载未覆盖边界，不增加状态/effect/请求流程或 CSS（React 技能派生值规则）。复用后端分页与跨租户/无权限/只读回归验证 Hermes，后端两文件 **33 passed**；前端解析器+面板 **27 passed**；标准正式模式构建 `/tmp/siq-hermes-roots-production-3qc0cp` 成功，未部署。

复用浏览器脚本新增 --framework hermes；开发身份隔离构建 `/tmp/siq-hermes-roots-mock-only-fAHgKT` 仅模拟不可发布。7 项浏览器检查通过，零业务写/外网请求和未捕获异常；最终证据 `/tmp/siq-hermes-roots-ui-final-20260926/report.json`。实际查看 375/1280 截图，保留原 card/字体/焦点，内容换行无横向溢出。首次截图发现空数组 mock 未设 Content-Type 导致无关证据面板显示失败，修复夹具显式 application/json 后重跑并检查最终截图；不算生产缺陷。Ruff/git diff --check 通过。

当前来源读取到界面已连接，但本轮浏览器仅合成响应，未证明原生采集→真实控制面→界面的同制品全链路。历史 Hermes 快照仍未升级，external_dirs/受信任项目根和运行时加载归属未完成；不把目录相交当作授权或角色实际使用。CL-03 保持开放，未提交、未发布、未部署；未修改 GLM 周期管理或 Qwen 调度文件。

## Batch178：Hermes 历史配置与选中快照对照 v2

先冻结 configuration-history/v2 与 snapshot-comparison/v2 配对合同，同 URL 按资产框架选择版本。投影校验保存来源框架与原任务 connector、所属资产框架、根版本、目标设备及批摘要；异常不展示原文或回退最新配置。Hermes layout_candidate 可与该快照设备最新签名安装观察对照，保留双方时间，不称作配置当时安装还原；OpenClaw 仍走 v1。

前端历史/快照解析同步两组严格配对，外层 v1 不容纳 Hermes 成功快照，v2 不容纳 OpenClaw 成功快照。原两面板仅派生框架名称、单根布局说明及范围外标签，不改 CSS、导航、请求或授权行为，继续遵循 React 派生值规则。历史快照仍只是已保存配置记录，不新增原始批次重新验签保证。

复用既有夹具参数化两框架：分页、旧快照不被最新属性替换、根缺失/损坏、批摘要/安装回执损坏、跨租户/资产与权限拒绝。相关三个后端文件 **31 passed**；三个前端文件 **74 passed**。正式模式标准构建 `/tmp/siq-hermes-history-production-1divfd` 成功。Ruff、git diff --check 通过，未跑无关全量。

已有快照冒烟脚本增加 --framework hermes，用隔离开发身份构建 `/tmp/siq-hermes-history-mock-only-uXGe1e`（仅模拟不可发布）；**14 项通过**，包含显式选择前零请求、A→B 迟到隔离、同游标重试、无回退、双权限拒绝、零写/外网/未捕获异常。结果 `/tmp/siq-hermes-history-ui-20260926/report.json`，375/1280 截图已实际查看，单列移动布局/摘要换行正确，风格不变。不是生产 IAM 或真实设备验收。

历史 Hermes 界面缺口本轮已推进，不代表 CL-03 整体完成：默认/外部/项目范围、技能选择与真实加载归属、同制品原生全旅程仍需收口。未触碰并行 GLM/Qwen 文件，未提交、未部署。

## Batch179：默认/命名/自定义 Hermes profile 原生范围核对

核对安装 catalog 与计划签发，确认范围来自部署方受控文件原样投影，不能由采集器或 API 默默补根。Hermes 已支持显式默认 profile 与绝对自定义根，本次不修改生产默认范围或读取实际 catalog。补充 profile 身份合同说明：profiles/* 不覆盖默认 profile；自定义 HERMES_HOME 须转成明确确认路径，不继承开发进程环境；新增根需新计划/确认，不能改变已确认周期范围。

新增一个集中原生协议测试 native_source_roots_test.go，复用已有真实构建/--serve NDJSON 夹具，使用隔离 HOME 的默认、命名和自定义三个目录。窄 profiles/* 只返回命名角色；显式三根返回独立身份，标准库独立计算核对配置完整摘要、证据 ID、source/v2 与 roots/v2 布局摘要；SOUL-only 确实返回候选但没有配置/根声明。不读真实 profile、不发送上传、不扫描技能。

初跑误将夹具已解包的 collect 结果再次当 RPC envelope 处理，测试失败；修正测试调用层级后 `GOPROXY=off go test -race -count=1 -run '^TestNativeProfileLayoutsAndSourceV2$' .` 通过（1.365s），go vet、gofmt、git diff --check 通过。Linux ARM64 当前未提交源码临时构建，不使用仓库既有二进制，原生子进程由夹具回收。没有跑无关全量。

这关闭三类明确根在当前原生 Connector 的本轮证据缺口，不代表部署方 catalog 已配置这些根，更不代表原生 Edge→控制面→UI 全旅程完成。外部/项目来源与实际加载仍待实现。未提交、未部署，未修改 GLM/Qwen 在途文件。

## Batch180：原生 Edge/Connector 经隔离 Gateway 的 Hermes 来源读回

复用 gateway-edge-smoke.py 的真实本机 HTTP/原生执行链，补来源、框架清单、配置历史和两种技能来源对照 GET 的读回断言；预期配置/目录摘要由临时合成输入独立计算，不从响应取预期。当前工作树离线构建 Edge 与 Hermes，隔离 HOME/状态/SQLite、合成身份及回环 Gateway/Control API 启动，未访问实际用户配置或生产服务。

运行 `python scripts/enterprise-experience/gateway-edge-smoke.py --gateway /home/maoyd/siq/siq-gateway --edge /tmp/siq-hermes-native-readback-VYyJH0/edge-agent --connector-dir /tmp/siq-hermes-native-readback-VYyJH0 --out /tmp/siq-hermes-native-readback-VYyJH0/report.json --consent --initial-scan`，**11 项通过**。覆盖原生注册/重复拒绝、明确计划确认、心跳、首扫重放、签名上传/回执、Hermes v2 来源与不可变快照/布局读回、其他租户404、已签名越范围任务拒绝且审计、模拟吊销后在线拒绝。技能未采集，来源对照为空但状态为 historical_comparison，不宣称发现真实安装匹配。

证据 report.json 包含 Edge/Connector/脚本/Gateway与API源文件摘要，passed=true、fixture_processes_stopped=true。Edge SHA256 4109bc8e6e2ae1ea7d7b113f10a41a273324f1eddd394b83e0c497192bc229fc，Hermes SHA256 86966c4aad3c2eb28d0d8bad9721cea588e112a315e85873fc7b3326dd2eabfe。临时服务和夹具均由脚本回收，二进制和脱敏报告保留于上述 /tmp 目录；未签发/发布。git diff --check 通过；脚本完整 Ruff 检查报告 9 处原有 E501 长行（不在本轮新增断言），未通过删除规则或格式化无关片段掩盖，不宣称 Ruff 全过。

该证据比 mock 多覆盖真实原生上传与控制面读回，但仍是开发身份、SQLite、fake enforcement、未签名源码构建；本轮不是生产 IAM/PostgreSQL、正式安装服务或浏览器消费同批数据验收。外部/项目技能来源、实际加载和原生技能匹配仍未完成。未提交、未部署，CL-03/07/08 不关闭，未改并行任务所有权文件。

## Batch181：未按可信发行布局安装的技能采集器拒绝证据

在既有隔离 Gateway→Control API→原生 Edge 夹具中加入 Directory 技能任务，最初尝试验证 Hermes profile 与安装技能的正向匹配，但实际被技能采集前置门禁拒绝：源码构建的平铺二进制目录不满足受验证安装布局。未修改信任根、伪造正式签名或绕过 measureServiceCapabilities。正向技能匹配仍待可信发行制品验收；不得用下面的负向结果替代它。

现有脚本新增显式 `--untrusted-skill-bundle` 场景，只在合成 HOME 内准备技能，核对公开错误 skill_execution_unconfirmed、原任务仍可领取、隔离控制面数据库内状态仍为 pending 且没有 SkillUploadReceipt；最新来源对照与选中快照对照仍为空。数据库检查由该服务自己的隔离夹具进程执行，不查询兄弟服务或真实数据库。该场景仅证明未安装布局被拒绝，不证明已经走到发行签名密码学校验，也不证明技能已安装/加载或生效。

此前三次失败报告保留在 `/tmp/siq-hermes-skill-chain-i4rxgj/`：report.json 为未达成的正向匹配预期；denial-report.json 错误期待被包装隐藏的内部错误码；denial-final-report.json 错误期待任务 wire 有 status 字段。改为核验公开错误及 owner fixture 的持久状态后，denial-verified-report.json 实际 12 项通过。未删除产品安全断言或放宽门禁。

本轮复核确认该进程已结束且报告与脚本摘要一致，再收口脚本 11 处长行及字符串连接括号（仅格式，断言与语义不变）。最终执行：

```bash
python scripts/enterprise-experience/gateway-edge-smoke.py --gateway /home/maoyd/siq/siq-gateway --edge /tmp/siq-hermes-skill-chain-i4rxgj/edge-agent --connector-dir /tmp/siq-hermes-skill-chain-i4rxgj --out /tmp/siq-hermes-skill-chain-i4rxgj/denial-closeout-report.json --consent --initial-scan --untrusted-skill-bundle
apps/control-api/.venv/bin/ruff check --config apps/control-api/pyproject.toml scripts/enterprise-experience/gateway-edge-smoke.py
git diff --check
```

最终原生隔离检查 **12 项通过、exit 0**，临时服务全部回收；指定 Control API 配置的 Ruff 与 diff 检查通过。没有跑无关全库测试。报告明确 publisher_release_verified=false，记录脚本、二进制和源文件摘要；此前与本次 12 项为重复验证，不累加。工作区默认 Ruff 配置不同，首次检查还提示该脚本非可执行文件带 shebang；本任务使用明确 `python` 命令运行，未将指定配置通过扩大为全部配置通过。

未提交、未部署、未签发，未修改 GLM 周期管理或 Qwen 调度重放文件。CL-03/07/08 仍开放：合法发行包的技能采集与角色来源匹配、真实身份/数据库/部署形状仍没有本轮完成证据。

## Batch182：Qwen 同槽重放交付复核与异常记录拒绝修复

确认 Qwen 的 enterprise-schedule-replay-closeout-handoff.md 已交付，复核其任务范围多重集合比较、directory 拆分复用、原顺序返回与事务边界。发现其 task_ids 类型检查在 set 去重之后；合成持久记录含数组或对象元素时，两个新负例均实际抛 TypeError，而非固定 discovery_schedule_replay_unavailable。该发现不证明外部身份能任意改数据库，属于异常历史记录的拒绝路径缺陷。

最小调整先校验字符串元素再去重，补预算/槽/revision、任务/轮次/审计/outbox 数量和原记录不变断言。`uv run --no-sync pytest -o addopts='' -q app/tests/test_discovery_scheduler.py app/tests/test_discovery_schedule_tick.py --tb=short` **31 passed**；相关两文件 Ruff 与 git diff --check 通过。没有跑无关全量或改权限/签名/接口，未触碰 GLM 在途管理面板。Qwen 交接记录追加主开发者复核第 8 节；此次修复针对已交付成果，不并行重写其原任务。

仅接受该范围完整性子项，不将其等同历史任务原始签发身份、真实设备周期运行或完整安装闭环；CL-02 仍缺新设备组织计划衔接、确认日志换代及原生安装验收。未提交、未部署。

## Batch183：周期确认材料单侧缺失时启动拒绝

继续检查 CL-02 恢复路径发现：scheduledHeartbeat 在 pending 日志不存在时直接返回普通心跳，未检查 confirmed 回执是否残留。合成私密状态中保留完整或残缺回执、将原日志移到测试备份后，两种场景均复现错误放行。该缺陷不证明能扩大采集范围，但会把未完成恢复误判为从未配置周期，违反不完整确认材料拒绝启动的约定。

最小修复：无 pending 时再用 Lstat 核对 confirmed，只有两者都不存在才保持旧无周期行为；回执存在或无法确认其不存在均固定拒绝，原材料不改写、不删除。serve 和 install-user-service 复用同一验证，未新增命令或自动续期。合同澄清两份材料的对称存在要求，尚未实现计划日志换代。

新增一个参数化 Go 测试（完整/残缺两子场景），修复前均失败，修复后核对固定错误、无可用轮询函数、无心跳调用、原回执字节保留及未重建日志。`go test -race -count=1 -run 'TestSchedule|TestInstallUserService' .`、`go vet ./...`、gofmt 与 git diff --check 均通过。只操作测试临时目录，未调用真实 systemctl、未启停服务或发送采集。未提交、未部署；不关闭 CL-02。

## Batch184：周期计划换代的在线撤销核验前置

针对固定确认文件阻止新计划确认的剩余缺口，先冻结 enterprise-discovery-schedule-retirement/v1：旧计划须经既有组织接口撤销、本地明确确认后才可归档；不按设备时钟自动清理、自动续签或直接撤销业务权限。归档原字节保留、未决持久事务、启动阻断及恢复要求已明确，但归档 CLI 与文件事务尚未实现，文档明确不可作为可用命令。

复用既有设备 GET 的严格解析，提取状态快照读取；原 fetchDiscoverySchedule 仍只接受 pending_confirmation/revision=0，未扩大首次确认资格。新增只读 verifyRevokedSchedule 前置核验：原私密日志与状态基线、origin/设备身份、返回意图全部字段/摘要、revoked 状态及递增 revision 必须一致；取消前后失败关闭，不重试、不写文件、不签名、不发 POST。此方法尚未挂接归档命令，不能称换代已可用。

原真实回环 GET 拒绝矩阵保留；新增集中单测涵盖 revoked 正例、active/pending/未知状态、零 revision、内容变化但重算摘要、错 origin 和预先取消，确认单次 GET 或零请求及原日志字节不变。新单测使用注入 HTTP transport，是合成证据，不证明真实设备撤销。`go test -race -count=1 -run 'TestScheduleFetch|TestScheduleRetirement|TestConfirmSchedule' .`、`go vet ./...`、gofmt 与 git diff --check 通过。

下一步必须实现保留历史的归档事务、崩溃恢复与明确确认 CLI，不能以本阶段只读前置替代恢复目标。未触 GLM 管理接口/UI，未访问真实控制面或用户状态，未提交、未部署。CL-02 仍开放。

## Batch185：周期换代的持久归档准备与未决阻断

新增 discovery_schedule_retirement_linux.go：在调用方持任务锁且明确旧意图摘要后，重新核对本地身份/凭据、原日志和可选回执，经既有 GET 验证撤销，独占保存原字节历史副本、同步且安全读回后发布私密未决标记。该阶段不移除原文件、不创建新周期、不执行远端写入；尚无生产 CLI 调用方。历史副本没有凭据/私钥正文，回执缺失可记录，但残缺回执不能伪装为缺失。

serve/安装前置与 confirm/prepare 确认路径均拒绝任意未决标记，即使原日志和回执随后缺失，也不能退回“无周期”路径。回执关联核验提取为共享小函数，保留现有严格字段/摘要/revision 语义，无接口扩展。

新增一组集中测试（已确认、无回执、仍 active、错误摘要、残缺回执、取消），核对拒绝无归档、单次 GET、原字节保留、未决时阻断启动与新确认；原材料迁移仅在测试临时目录模拟。`go test -race -count=1 -run 'TestSchedule|TestConfirmSchedule|TestInstallUserService' .`、`go vet ./...` 通过，gofmt 与 git diff --check 通过。没有访问真实控制面或 systemctl。

仍需完成：原件安全迁移、标记提交、在线复验后的中断恢复、CLI 明确确认。历史副本已写而标记未发布时的重复准备目前拒绝覆盖，已如实写入合同，下一阶段必须处理，不能称归档换代可用了。未提交、未部署，CL-02 未关闭；GLM 在途文件未动。

## Batch186：GLM 周期计划管理交付复核修复

验收 CL-02-SCHEDULE-MANAGEMENT，实际旧模拟构建复现首次撤销成功后 pending 未释放，第二条撤销无请求。修复成功刷新前和 finally 的标记释放，保留原 POST 载荷、鉴权及审计。分页/撤销失败清除旧可撤销提示，刷新关闭旧确认目标；撤销期间禁止分页刷新。客户端增加游标前进/尾项一致、撤销 revision 下界、日历日期和预约预算校验；身份隔离 key 改用 JSON 数组。

按 React 技能保持状态归约与事件处理边界，未添加轮询或业务能力。截图实查发现移动列布局仍沿用桌面标签 6em flex-basis，造成大量留白，仅专用 CSS 移动断点重置 auto；冒烟增加高度断言。截图方式改为视口，避免长元素超出滚动容器产生空白证据。

针对性前端修复前 6 failed / 31 passed，修复后 39 passed；后端管理/确认/tick 定向 41 passed；正式标准构建和独立模拟构建成功。隔离浏览器新增连续两次撤销、分页失败同游标重试，总计 15 项；最终证据 `/tmp/siq-dsm-review-final-compact-20260926/`。Ruff、git diff --check 与本次新文件空白检查通过。详见 enterprise-discovery-schedule-management-handoff.md 第 10 节，纠正原交付验证命令口径。

只验收管理子任务；模拟 API 不证明真实 IAM、设备停止采集或生产撤销。未提交、未部署、未读取真实秘密；CL-02 仍开放，主线归档换代与其他开发线成果保留。

## Batch187：DeepSeek 独立回执验证子任务复核修复

复核 deployment_verify 交付，新增负例实测 8 failed / 28 passed：显式异常回执 target 被忽略、空白/异常独立读回被误报为漂移、目标冲突 Finding 复制目标原文。最小修复分别为 no_receipt 且零后端构造、unreachable 且不制造 Finding、固定脱敏描述；缺省 target 的合法旧回执兼容。未增加状态/接口或行为验证承诺。

补 mismatch 审计失败下 Finding/AuditEvent/OutboxEvent 与验证列回滚，原 verifier 8 项不修改。三文件定向测试 53 passed（边界 37、原 verifier 8、消费者 8），Ruff、git diff --check 与新增文件空白检查通过。具体命令与结果见 enterprise-receipt-verifier-closeout-handoff.md 第 10 节。

纠正文档：正整数 revision 是 CLI 路径限制，不泛化为所有适配器，本验证器不新增非零约束。错误目标是模拟适配器的纵深防御证据，不是生产攻击复现或真实归属证明。本子任务验收通过，CL-05 仍开放。未触 Kimi 的 policies.py/绑定复验、前端、Edge 或共享安全实现；未提交、未部署。
