# Hermes 公共 CLI：受控原生入口尝试（未达到工具验收）

本轮仅执行一次 A 对照。已安装 Hermes 的公共 Python 模块入口启动后，在 90 秒期限内未访问合成模型端点、未执行目标文件写入；测试 guard 记录了 3 次 `subprocess.Popen` 和 1 次 `open` 拒绝。进程超时后由 harness 回收。A 为 **blocked**，B 为 **not_run**，不能把这些 guard 拒绝记为 SIQ 拒绝，也不能提升任何平台 matrix 项。

## 身份与结果

- checkout HEAD：`973541733ccdb25d4578e56033901e4829ff257c`；执行前后 tracked clean。
- 受测实现候选：`ebc472f2e46aa7de837afe9d6a0ed422eef51cd0`。运行前确认该候选到 HEAD 的 `apps/agentshield` 与 `adapters/runtime/hermes-agentshield` 无差异。
- 候选二进制 SHA256：`4bc3f5ae95fd00aab528363d5d91e64145e0fd75257904a9f898323de68b6f74`。本轮只核验其身份；A 不使用 SIQ，B 没有运行，因此没有新增该二进制的运行结果。
- 原创 harness：`evidence/hermes-public-cli-probe.py`（原字节审阅副本），SHA256 `ff1acd6063513bcaa5f4c8ddb61c738ee836ab5ebfc0323b46313703ed1c2924`。当前原始版本不再修改或重跑。
- Hermes 版本 `0.21.2` 来自此前安装源码盘点；本次没有成功运行版本命令，不把旧盘点当成新的运行输出。
- 使用安装目录内的 `venv/Scripts/python.exe -m hermes_cli.main chat`，不是自编 dispatcher，也没有修改或替换 Hermes dispatcher。该入口是安装源码支持的同一公共 CLI 模块入口；本轮没有调用外层 `hermes.exe`。
- A PID `35664`，期限触发 `timed_out=true`，kill 后退出码 `1`，`process_reaped=true`。另行 `Get-Process -Id 35664` 查询无结果。整个 harness 观测时间 `91.993` 秒（包含收尾）。
- 本地 provider 请求数 `0`；stdout、stderr 原始文件均为 0 字节；目标文件不存在；没有完整工具返回。
- B 没有创建 profile、安装插件或运行 CLI。不存在本轮 SIQ 插件加载、断服 block 或 dispatcher 消费 block 的新证据。

机器可读原始汇总为 [hermes-public-cli-observations.json](evidence/hermes-public-cli-observations.json)，保持原字节。其 `checks` 只包含实际执行的 A；[provenance](evidence/hermes-public-cli-provenance.json) 明确补充 B 的 `not_run`、4 条 guard 记录的 unknown 细分类、收尾状态及空 stdout/stderr 的长度与 SHA256。实际 profile、私有绝对路径、guard-loaded 标记和原始日志不在公开归档中。

本归档中的 harness 是原始代码审阅副本；它依赖原来的仓库相对位置与固定 checkout，不应从归档目录直接执行。完整复测需要审阅新的探针版本并另存新批次证据，本轮不重试。

## 已核实的受支持入口及配置依据

以下是安装源码的静态核查，不能当作本次运行已经应用了这些配置。

- `hermes_cli/_parser.py` 的 `chat` 支持 `--provider custom --model ... --toolsets file --max-turns 3 --run-budget 40 --ignore-rules --quiet --oneshot -q ...`。`hermes_cli/main.py` 包含 Windows 桌面通过 `python -m hermes_cli.main` 调用的入口链。
- `hermes_cli/main.py` 在主体导入前处理 profile；`hermes_constants.py:get_default_hermes_root` 对位于原生 Hermes 根之外的自定义 `HERMES_HOME` 推导独立根。采用新的 `<private>/hermes/profiles/probe`，同时隔离 HOME、USERPROFILE、APPDATA、LOCALAPPDATA、cwd 和 TEMP/TMP，避免 profile 名解析与默认认证回退回到原目录。
- `hermes_cli/auth.py` 会有 profile 到默认根的认证回退；仅更改真实 Hermes 根内的 profile 不足以证明账号隔离。此次不读取任何既有认证文件。
- `hermes_cli/env_loader.py` 可能加载安装源码 `.env`，而且启动恢复逻辑可能使用 `.update-incomplete`、`.lazy-refresh-incomplete`。本轮只检查这三个路径是否存在，均为 false；若存在即停止，不读取内容、不通过测试标记绕过恢复。
- `hermes_cli/runtime_provider_backends.py` 的 custom provider 支持 `CUSTOM_BASE_URL` 与 `model.base_url`；安装文档 `website/docs/user-guide/local-models.md` 描述 OpenAI-compatible 自定义端点。配置同时固定二者为新建 loopback provider，`model.api_mode=chat_completions`。不依赖 `OPENAI_BASE_URL`，不提供任何真实 API 凭据。
- profile 配置关闭 `memory.memory_enabled`、`memory.user_profile_enabled`，将 `memory.provider` 设为空；关闭 `telemetry.shared_metrics.enabled/send`、`updates.check`、`local_runtime.enabled`、`compression.enabled`、`auxiliary.title_generation.enabled`、`auxiliary.background_review.enabled`；MCP 配置为空。`--ignore-rules` 避免读取工作区规则。`--safe-mode` 会停用插件，因此不能用来验证 SIQ hook。
- `agent/tool_executor.py` 的 `_pre_tool_block` 调用真实 `_dispatch_pre_tool_call_hooks`，随后才进入 `model_tools.handle_function_call`；`hermes_cli/plugins.py` 接受有效的 `action=block` 与非空 message 并形成工具结果。当前 SIQ 插件 `_pre_tool_call` 在决策服务不可达时返回 fail-closed block。只有真实 CLI 到达该链且实际工具副作用有前后对照时，才可形成原生验收证据。本轮没有到达这一证明条件。

报告保存了入口、profile/plugin/provider 相关六个宿主源码文件的运行前 SHA256，并确认运行后相同。这个检查不等同于对完整 Hermes 安装树作了不可变性证明。

## 两例最小方案与安全边界

A 使用公共 CLI、仅文件工具和新私有 profile，不安装 SIQ；loopback OpenAI-compatible server 只能返回一个写私有合成目标的工具调用及结束消息。成功条件必须包括真实工具结果、目标内容匹配、CLI 正常退出、没有 guard 拒绝。

B 只有在 A 成功后才运行：在另一个全新的私有 profile 复制仓库原始 `__init__.py` 与 `plugin.yaml` 并记录摘要，通过受支持的 enabled 配置启用。因为没有既有配置，所以备份不适用；这不覆盖已有宿主安装迁移。使用新建、无实际权限的合成 token，决策端口使用占有但不 listen 的 loopback socket；必须观察到实际插件 block 被宿主完整 dispatcher 消费，同时目标未写入，不能把 guard、缺 token、异常退出或模型未调用工具当作通过。本轮 B 未运行。

白名单子进程环境不继承提供商凭据、代理和既有账号路径。Python `sitecustomize` audit guard 只允许限定 loopback 端口，限制写入新私有根，拒绝子进程与注册表修改，并拒绝配置/用户目录的非授权读取。**它不是 OS 沙箱，不能证明所有原生扩展行为都被覆盖。** 模型 server 只控制合成模型输出，不改宿主工具 dispatcher；没有调用真实模型或付费服务。

当前失败只能定位到 audit event 种类。guard 没有记录被拒绝的路径、命令或调用栈，stdout/stderr 又为空，因此不能进一步断言三次子进程或一次 open 的具体来源，也不能断言 open 指向了账号文件。发生 guard 拒绝后，本轮不放宽限制重试。

超时收尾路径执行 child `kill` + `communicate`，关闭 loopback server、等待 server thread、关闭占位 socket。已确认直接子进程回收；guard 拒绝了观察到的子进程创建。本轮没有启动 GUI、登录、任务计划或后台真实宿主任务，没有修改宿主源码、用户配置、tracked 源码或扫描规则。

后续若要继续，需要先用另一个明确版本的审阅式探针定位启动阶段的必要读取/子进程合同，再判断能否在不访问真实账号、不允许外网、不放宽到任意子进程的条件下完成 A。后续复测仍遵循既有授权与隔离范围；当前对照阻塞不能转换为 SIQ 成功。
