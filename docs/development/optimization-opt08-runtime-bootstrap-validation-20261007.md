# OPT-08 D3b：受保护的原生运行初始化

日期：2026-10-07。状态：组件与真实 OpenShell 联验通过；OPT-08 保持 implementing，主任务完成 9/16（56.25%）。

## 实现结果

覆盖包新增 `native_bootstrap.py`，提供 `ImageBootstrap`，使受保护业务启动代码能够复用固定初始化过程。原先验收脚本中手工拼装 Channel/Callbacks/Runtime 的代码改为调用该产品组件；新模块自身包含在镜像文件清单与宿主实际摘要核验中。

初始化只接受启动器固定的 Agent、session namespace 和通道目录，不读取环境变量来替换主体，不接收任意回调、URL、命令或秘密凭据。每个进程只允许一次尝试，失败不能换主体重试。当前仅适用于 Linux 非 root OpenShell 镜像 profile，普通插件与原只读 mount profile 保持原行为。

目录逐级 NOFOLLOW 打开，以目录描述符排他创建新的 0700 叶目录；已有目录、符号链接、其他用户可写祖先、非私有/非 socket 端点均拒绝。保留并反复验证对象身份，运行端响应始终要求真实 SCM_CREDENTIALS 的 `(0, 当前 UID, 当前 GID)`。目录和端点检查只协调启动，不能替代逐包宿主认证。

`ready()` 与 configure 完成均不授予权限：ready 状态固定为 `unverified`，初始化不创建假任务或默认会话。后续实际原生任务、来源读取和工具调用仍须通过现有 Go Authority。`close()` 使后续交换失败，仅释放本次描述符，保留目录和宿主端点；不会回滚已经开始的动作或重置已消耗的调用。

## 验证

| 检查层次 | 本批结果 |
| --- | --- |
| 启动正向 | 固定身份与 namespace 正确；环境中的其他身份不生效；新目录为 0700；配置后仍不声称已验证 |
| 一次性与有界等待 | 非法输入后不得重新初始化；两个并发初始化仅一个成功；重复 configure 使当前初始化失效；超时与 close 均有界结束 |
| 路径与端点负向 | 既有用户标记保留；符号链接/可写祖先拒绝；目录权限变化、替换、端点替换、普通文件/FIFO/错误权限 socket 拒绝，未知对象不删除 |
| 进程与通道负向 | 不支持的平台、有效/真实 UID/GID 不匹配拒绝；真实 fork 子进程在父线程持锁时立即拒绝，不等待继承锁；同 namespace 假宿主即使返回 accepted=true，也不能让任务进入执行体 |
| 实际 OpenShell | 使用新初始化器及其固定文件摘要，经 HTTP 身份签发/会话登记、实际内核通道和 Go Authority，18 项权限检查全部通过 |

新增启动测试 39 项；启动、原生分发、通道、在线映射和转发相关测试共 138 项通过。fork 持锁反例有一条 Python 多线程 fork 弃用警告，这是该反例主动构造的情况；子进程拒绝并正常退出，未发生死锁。Ruff 和 diff 检查通过。

真实 OpenShell 中有 23 次工具尝试，18 条签名回执（14 allow、4 deny），另 5 次为决策前拒绝。两个合成 Skill 的允许/拒绝、并发隔离、重放、任务结束、三种撤权和宿主独立文件检查均保持通过。Go 集成段用时 21.849 秒，原网关配置及 TLS 摘要保持不变，独有沙箱和网络清理成功。

```bash
var/mako117-20261006/worktree/apps/control-api/.venv/bin/python -m pytest \
  adapters/runtime/hermes-agentshield/tests/test_native_bootstrap.py \
  adapters/runtime/hermes-agentshield/tests/test_native_dispatch.py \
  adapters/runtime/hermes-agentshield/tests/test_native_channel.py \
  adapters/runtime/hermes-agentshield/tests/test_native_online.py \
  adapters/runtime/hermes-agentshield/tests/test_native_relay.py -q
python patches/hermes/run_openshell_runtime_probe.py --online \
  --output var/optimization-20261007/opt08-openshell-bootstrap-01
```

源码指纹、候选镜像、检查摘要及原始结果摘要见[结构化证据](evidence/optimization-20261007/native-runtime-bootstrap.json)。本批没有修改 Go 生产逻辑，不重复 Go/前端/控制面全量或四目标构建；实际联验中的 Go 测试服务仍真实运行。

## 接入用法与剩余边界

受保护入口在启动现有 Hermes 业务服务前执行：

```python
from siq_native_runtime.native_bootstrap import ImageBootstrap

bootstrap = ImageBootstrap(fixed_agent_id, fixed_namespace, new_private_channel_directory)
descriptor = bootstrap.ready()  # 供可信宿主定位，不能当成运行证明。
# 使用入口既有的受控启动通道发布 descriptor；宿主独立核验并创建端点。
bootstrap.configure(timeout=30)
# 随后进入原有 Hermes gateway/业务服务；任务与 Skill 由原生路径自动观察。
```

上例是调用顺序，不是可直接部署的网关启动命令。参数与代码必须进入可信启动参数/制品绑定；管理与运行凭据仅在宿主。初始化器不负责模型配置、provider、OpenShell 生命周期或业务鉴权，不接收任意待执行模块。

当前实际联验仍由专属脚本驱动真实工具，Skill 和批准操作员为合成材料，模型调用为零。尚须将组件接入业务仓库既有受保护启动器与宿主生命周期，完成智能分析助手日常入口、真实业务 Skill、业务撤权、网络效果、升级/漂移/过期和审批重试。业务仓库 API/pool/lifecycle 核心文件存在既有未提交修改，本批只读核对并保留；未用验收脚本替代业务入口，未更改 production_enabled 标记。
