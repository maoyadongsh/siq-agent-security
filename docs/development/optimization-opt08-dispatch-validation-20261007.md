# OPT-08 D2c2：原生 Hermes 读取与最终分发接线

日期：2026-10-07。结论：固定业务镜像中的原生函数已经接入强制门禁，组件验证通过；完整 SIQ Authority 桥接与日常业务验收仍未完成。OPT-08 保持 implementing。

## 实现与实际覆盖

合同：[native-hermes-dispatch/v1](../../packages/contracts/native-hermes-dispatch.v1.md)。实现：[native_dispatch.py](../../adapters/runtime/hermes-agentshield/native_dispatch.py)。原生补丁生成器与许可：[patches/hermes](../../patches/hermes/README.md)。

生成器核验固定镜像内六个源文件的摘要，逐处校验替换次数并编译生成内容；不改动业务仓库或正在运行的服务，不覆盖已有输出。源摘要、最终覆盖文件摘要及探针结果保存在[结构化证据](evidence/optimization-20261007/native-hermes-dispatch.json)。候选代码在离线临时容器中以只读方式覆盖原生路径。

| 原生位置 | 接线行为 | 本批证据 |
| --- | --- | --- |
| `run_conversation` | 实际任务/session 进入作用域，正常与异常均关闭；拒绝未知父任务 | 实际公开入口调用，内部会话循环用离线夹具替换 |
| 普通及插件 Skill 读取 | 主文件、支持文件均消费文件快照组件返回的同一份文本 | 实际函数读取临时 Skill 文件 |
| Skill 缓存 | 命中前重读并通知来源；同大小、同 mtime 的字节修改仍拒绝 | 实际缓存路径与后续拒绝检查 |
| Skill 预处理 | 此 profile 禁止内联 shell/模板执行，保留普通文本 | 带预处理文本的 Skill 未产生受控标记文件 |
| `registry.dispatch` | 在中间件之后，以最终私有参数快照和实际调用 ID 请求授权 | 实际 handler 正向写入、拒绝无写入、重复调用拒绝 |
| 执行中间件改参 | 改参后重新进入最终门禁，不能沿用早期参数授权 | 原生中间件改写允许路径为拒绝路径，无对应副作用 |
| 宿主直达路由 | 尚未接线的 todo/memory、上下文引擎等入口明确拒绝 | 实际 helper 和顺序/并发共用执行边界拒绝 |

接入模块不持有规则、管理凭据或签名私钥。来源、授权、结果回调必须由可信 bootstrap 一次配置；未配置时原生注册表也不能执行工具。返回的授权必须精确绑定最终请求，deny/hold 不执行；结果观察仅声明函数 returned/raised，不代替文件或网络效果核验。

同任务最终分发串行，不同任务独立；Skill 切换形成连续来源父链。任务结束先失效，排队时持续检查取消且最多等待五秒。已授权在途动作可能随后完成，仍观察其结果，不能声称取消已经撤回副作用。此模块不杀 Python 线程。

## 验证结果

- 全 Hermes 适配器首轮：252 通过、1 失败。失败揭示任务结束后，新调用仍可能等待在途 handler 的锁；已增加锁前存活检查和有界排队。
- 修复后受影响套件：24 项通过，覆盖精确参数、回调失败、重复调用、来源漂移、并发任务、fork、任务异常和在途任务结束。按本轮加速要求，不重复执行已通过的无关全量测试；不把首轮记录改写成最终全量通过。
- 固定镜像离线探针：21 项通过。运行真正的 Hermes 读取、缓存、分发、公开会话和执行器函数；会话内部循环与 Authority 回调是合成夹具。模型调用数为零。
- 构建器负向：源文件摘要变化时拒绝且不创建候选；已有目标拒绝且保留哨兵文件。两项通过。
- 新增 Python 文件 Ruff 通过。补丁在固定镜像 Python 3.11 中实际导入执行；本机定向套件使用 Python 3.13。

探针固定使用镜像 `sha256:fe5bdcebbc09b2099a3b387a675a4e8d879b8491bdc6246d93fbc8abb51e1f02`，禁网、只读根文件系统、丢弃 capabilities、非 root 用户，临时数据仅写 tmpfs。不挂载业务数据库、模型配置或真实凭据；容器退出自动移除，超时也按该次创建的精确容器 ID 清理。

复跑入口：

```bash
python -m pytest adapters/runtime/hermes-agentshield/tests/test_native_dispatch.py -q
python patches/hermes/build_native_overlay.py \
  --source /absolute/extracted-pinned-source \
  --destination /absolute/new-overlay
python patches/hermes/run_native_probe.py \
  --overlay /absolute/new-overlay \
  --output /absolute/native-probe.json
```

本次最终候选清单摘要为 `0b8d90c9d092fd1cfc8ab4fc3657b33ec0e1902cf19f8888f0b4277055580417`。摘要用于复核本批文件，不是独立签名或可信启动器验收。原始输出保留在本机 `var/optimization-20261007/opt08-dispatch-*`，不提交原始日志或上游完整源码。

## 后续接线与验收边界

真实 Go 上下文/调用存储、在线签名权限引擎、受保护启动器及宿主事实发布尚未连成产品路径；manifest 的 `production_enabled` 和 `authority_bridge_connected` 均为 false，新身份 HTTP 创建入口保持关闭。实际 OpenShell 挂载、智能分析助手业务 API、双 Skill 日常任务、四组对照及跨平台验收仍待完成。

本批不将合成 allow 回调作为真实 SIQ 权限决策，不把真实函数探针称为日常业务效果测试。缺少可信父任务的 subagent 与未接线宿主直达路由属于明确不支持范围。旧插件与冻结历史测评证据保持原样。
