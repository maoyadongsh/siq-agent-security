# OPT-08 D2j：真实运行中的并发隔离、撤权与任务结束

日期：2026-10-07。状态：本批 18 项检查通过；OPT-08 保持 implementing，完整任务完成数仍为 9/16（56.25%）。

## 结果与证据口径

在 D2i 的同次实际 OpenShell 沙箱、Hermes 原生工具、宿主内核核验、Go HTTP Authority 和签名安装基础上，增加两个并发任务、调用重放、任务结束，以及三层权限撤销。运行使用新的独有派生镜像、沙箱、网络和临时 Authority 状态；没有改动日常网关或原业务镜像。

共 23 次真实 `handle_function_call` 工具尝试，18 条回执通过签名链验证，其中 14 条 allow、4 条 deny。另 5 次在进入决策回执阶段前拒绝：重复调用 ID、已结束任务，以及 SEC、Skill Grant、Agent 基线三种撤权。**这 5 次不是签名 deny 回执，不能用 23 条回执或 9 条签名 deny 描述本次结果。** 工具门禁、宿主事件和真实存储撤销读回共同说明拒绝发生在哪个阶段。

| 场景 | 正向对照 | 负向与独立观察 |
| --- | --- | --- |
| 原有权限交集 | reader 读取、独立 writer 写入成功 | reader 写入、切换 writer 后写入、批准路径外写入拒绝；切换保留两层上下文 |
| 同进程并发 | 两个线程分别加载 reader/writer，经屏障确认任务同时存活；writer 写入成功 | reader 写入仍拒绝，没有借用并发 writer 的权限；两次裁决均携带自己的单层上下文 |
| 调用重放 | writer 原调用产生批准文件 | 同一 task 和 call ID 改用另一目标文件被本地门禁拒绝，没有第二次授权和新文件 |
| 任务结束 | writer 任务正常执行并结束 | 结束后的新调用在进入宿主前拒绝；宿主事件中无该调用，目标文件不存在 |
| SEC 撤销 | writer 已加载并完成一次合法写入 | 测试操作员通过真实 InvocationStore 发布签名撤销，下一次调用拒绝；未产生目标文件 |
| Skill Grant 撤销 | 新 writer 上下文仍可合法写入，证明前一个 SEC 撤销没有错误撤销整个 Skill | 真实 Grant 撤销以 CAS 和审计提交，验证签名读回；下一次写入拒绝，目标文件不存在 |
| Agent 基线撤销 | 独立 reader 在 writer Grant 撤销后仍能读取合成输入 | Agent 基线经真实 Store 撤销后，下次读取在 call_prepare 阶段拒绝，工具结果不含输入内容 |

宿主通过已固定的实际进程根目录，独立检查四个允许写入的文件内容/摘要，以及所有预期拒绝目标的缺席。对读取拒绝的观察是原生门禁失败与工具返回不含合成标记，不把文件缺席当作读取未发生的证据。

## 实施方式

- 并发使用同一 Hermes 进程、同一会话下的两个实际任务，线程屏障使两者都完成 Skill 加载后才开始写入；不是顺序执行两个探针。
- 真实签名权限操作放在显式 opt-in 的 Go `_test.go` 所拥有的临时状态中。宿主只在指定下一次调用之前触发既定撤销，并等待存储确认；请求仍通过未修改的生产 relay 和 Authority。
- 撤销控制文件和凭据不挂载到沙箱，不增加运行时、管理 HTTP 或模型可调用的测试权限端点。该操作员路径是验收夹具，不是日常业务撤权 UI。
- 所有 Skill 内容均为合成测试材料；导入、批准、安装、激活和上下文使用真实实现。模型调用为零，不把此结果标注成智能分析助手模型对话验收。
- 本批仅扩充验收脚本及 Go 测试夹具，没有改动生产权限判定、模型配置或平台策略。

## 执行与复现

```bash
python patches/hermes/run_openshell_runtime_probe.py --online \
  --output var/optimization-20261007/opt08-openshell-lifecycle-01
```

输出目录要求不存在；复现时选择新目录，保留既有证据。脚本需要本机固定 OpenShell 工具链、固定 Hermes 基础镜像、已有源文件提取和前序镜像基线，不是跨机器零配置安装器。

本次实际 Go 集成测试通过，用时 22.198 秒。相关 Python Ruff、Go server vet、`git diff --check` 通过。测试代码在真实 opt-in 运行中编译执行；未改动生产代码，因此没有重复未受影响的前端、控制面全量、Go 全量或四目标构建。原先 14 allow/4 deny 的签名链与本批源码摘要见[结构化证据](evidence/optimization-20261007/native-openshell-lifecycle.json)。

原始运行目录保留在本机 `var/optimization-20261007/opt08-openshell-lifecycle-01/`。本次独有沙箱删除成功，独有网络确认空后移除；原网关配置和 TLS 摘要保持不变。原始服务日志、私钥、运行凭据、完整临时状态不提交。

## 尚未完成的产品入口

对实际业务仓库的只读核对确认：智能分析助手经过 `apps/api/services/openshell_pool_adapter.py` 管理 pool/lease，再进入受保护 Hermes 运行入口；`scripts/openshell/run_hermes_gateway.sh` 通过清理后的环境启动 `siq_analysis_lifecycle.py`，候选镜像另有 `infra/openshell/sandbox/qwen38_candidate/request_bootstrap.py` 的请求启动与原有适配器身份安装。这些已有入口不能由本次测试 bootstrap 替代。

后续必须将受保护原生启动、身份登记、真实业务 Skill 安装与这些既有入口经版本化协议接通，再做日常业务验收。独立业务仓库现有修改应继续保留，不能复制其内部鉴权到 Security 仓库。

剩余还包括真实业务授权撤销、安装升级/内容漂移、租约过期、网络实际效果和审批重试。当前三种撤权来自受控本地权限状态，不代表业务数据库授权撤销已经连通。并发结论仅覆盖本次同进程双任务交错，不扩展为任意多进程或全部调度的保证。新身份 HTTP 创建仍关闭，本批不能作为 OPT-08 或整体开发已完成的证明。
