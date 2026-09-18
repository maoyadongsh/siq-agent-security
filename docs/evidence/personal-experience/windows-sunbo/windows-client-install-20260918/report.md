# Windows 已验证客户端安装入口

代码候选 `0c9a335bcfa06205801f9b15b596c8c185dd34c4`，基于 `0674509`；Windows amd64 制品 SHA-256 为 `52d8f3674d1f3141ee613fb28d4982743962c09ad7f26ec0ab889c13bd4eee3e`，实际构建信息与源码一致且 `vcs.modified=false`。

此前 `client-install` 在 Windows 总是因 Linux-only 平台检查拒绝，未进入发行验证；真实 CLI 复现见 `before.json`。本次接通当前用户 Task Scheduler 安装：继续使用内置发行根和状态兼容预检，暂存后再验签与校验摘要目录，Windows 目标为 `siq-agent-security.exe`，只从该稳定路径执行已有 setup。Windows 不支持的 runtime 选项在副作用前拒绝，子进程环境按 Windows 名称大小写语义移除冲突状态覆盖。

setup 后父进程按暂存程序路径、状态实例和当前用户 SID 构造预期任务；核验本地签名记录、实际系统定义及单个运行实例，再核对目录健康和发行版本。任务定义在运行态读取前后均复验；当前安装器路径或原下载路径不能替代暂存路径。错误保留现场，不自动覆盖任务或停服务。不新增升级/回退能力，不更换发行根，不新增跳过验签方式。

定向单测 7 个顶层、22 个子测试通过，未跳过。覆盖源/目标信任拒绝、版本/内容/位置漂移、Windows 环境变量大小写、未确认及不支持参数，以及任务 ready/queued/多实例、系统读取失败、前后归属漂移、错误程序和错误用户。任务读取使用明确注入的测试读取器，是组件证据，不能称为真实 Task Scheduler 安装。首轮九个任务夹具因名称过长超过产品现有 260 单位路径上限而失败；只缩短测试目录，未放宽产品限制，原始结果在私有工作记录保留。

干净源码四目标构建通过：Windows amd64、Linux amd64/arm64、Darwin arm64；逐个记录产物摘要和源码身份。CLI 包 go vet、改动文件 gofmt 通过。真实新 Windows CLI 对不受信任清单、未确认安装和不支持的 runtime 三种调用均退出 1，均未创建隔离状态目录。具体结果见 `build-and-native-refusals.json`。交叉构建不等于其他系统实测；本批未执行全量 Go 或最终集成回归。

复现单测：在 Windows 普通用户、可用的私有短临时目录运行 `go test -count=1 -run 'TestClientInstall|TestClientInstallation|TestInstallationEnvironment|TestWindowsClientInstall|TestWindowsInstallationEnvironment|TestWindowsOwnedTaskRuntime' ./cmd/agentshield`。原生拒绝探针使用独立不存在的 SIQ_AGENT_SECURITY_STATE_DIR，分别提供仓库测试清单、附加 `--runtime` 或缺少确认，核对退出码和状态目录缺席。

P05-19 尚不能登记通过：最终组合候选仍需真实受信任的新发行清单和对应制品，完成普通用户安装、系统任务读回、运行身份、重复安装及清理还原。测试签名或注入的组件读取器不能代替正式发行安装。旧冻结清单未修改，本批未发布制品。

本批未注册计划任务、启动服务、调用模型或修改日常配置。测试临时夹具由测试框架清理，原生负向仅保留空的自有测试父目录用于核查。私钥、token 和完整私有状态未入库。
