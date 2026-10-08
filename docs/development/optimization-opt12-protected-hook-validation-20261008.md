# OPT-12：受保护钩子与实际执行拒绝联验

日期：2026-10-08。运行时代码与Go Authority使用本分支`20a55bf3`；新增测评脚本及实际镜像摘要见[结构化证据](evidence/optimization-20261007/protected-hook-execution.json)。OPT-12仍为implementing，总体10/16（62.5%）。

## 本次证明的能力

在DGX Spark／Linux的独立OpenShell沙箱中，当前Hermes原生工具、独立宿主校验器和真实Go权限服务共同工作：

| 阶段 | 实际结果 | 归因 |
| --- | --- | --- |
| 加载批准的writer Skill，写入允许目录 | 正常成功；宿主读取到准确文件内容 | SIQ实际签名安装／授权、原生上下文、HTTP裁决和Hermes write_file |
| 运行用户改写、删除、替换native_dispatch.py及镜像manifest.json | 两目标×三动作全部拒绝，字节未变 | 镜像文件与祖先为root所有，运行进程为非root且无附加能力；不是模型遵守提示 |
| 上述失败尝试后再次合法写入 | 正常成功 | 文件保护没有被解释为全面停机，允许路径仍可完成 |
| 宿主测试操作员仅在自有容器中修改已绑定钩子代码 | 下一次真实write_file失败，独立宿主确认目标文件不存在 | RuntimeGuard逐次复验实际代码及进程，失效后原生通道不能继续发布权限上下文 |
| 操作员恢复钩子原字节，再使用同一运行身份写入 | 仍失败、无文件副作用 | 旧guard永久失效，不能用恢复内容自动复活；合法新运行须重新建立完整身份 |

这是确定性原生工具联验，没有调用模型。两项Skill包内容与审批操作者是测试夹具；Go签名存储、管理／运行HTTP、真实内核进程与文件事实、OpenShell及Hermes工具执行均实际运行。本批不冒充智能分析助手的日常业务入口或正式发行包验收。

## 信任链与证据

固定基础镜像提供解释器与Hermes。构建器先核对六份固定上游源文件摘要，再生成当前原生覆盖层；新镜像内钩子及祖先由root拥有。独立宿主持有预期镜像、制品、代码清单、进程／启动参数和后端绑定，运行用户不能通过改写插件目录的manifest改变这些预期值。宿主RuntimeGuard和权限凭据没有进入沙箱。

本次镜像为`sha256:02d703298fe3f002d970466c15ef9a47fdcef8e37e4211be6ca77ace540a904a`。记录18项运行检查、6次真实文件修改尝试及3条成功回执；这些检查相互重叠，不能合计为独立样本量。三条回执精确对应skill_view和两次允许write_file，真实Go权限服务在退出前验证完整签名链。漂移拒绝发生在原生宿主通道，未产生新的Go裁决回执；不伪造deny记录。

公开证据提供回执元数据与摘要投影，不是带独立公钥的签名导出包，不用投影宣称第三方离线验签。外部文件观察由宿主在容器进程实际根目录读回，分别确认两个成功文件的内容及两个拒绝文件不存在。

## 验证与失败保留

- 真实联验最终批次：`var/optimization-20261007/opt12-protected-hook-002/`，完整成功。
- 首批001：所有已打印执行条件通过，但清理目录context退出时再次校验已失效guard而抛出异常，整批没有记成功。脚本按既有控制器的终态清理重试语义修正；未放宽RuntimeGuard，也未吞掉未知异常。001输出保留，自有沙箱／网络清理成功。
- RuntimeGuard／HostSession／HostControl相关50项回归通过；既有fork多线程警告保留，没有将其算失败。
- 新证据校验器9项通过，拒绝空／缺少／多余、truthy字符串、错误调用、错误工具、deny及旧版本回执。该严格校验在运行后加入，已对未改变的002原始回执执行；没有为纯结果校验重跑OpenShell。
- 新脚本按当前Ruff配置通过。对原有runner额外指定py313会提示既有tomllib导入排序，当前仓库配置检查通过；未为该提示改写无关导入。

复现命令（输出目录必须不存在）：

```bash
python3 patches/hermes/run_openshell_runtime_probe.py --integrity \
  --output var/optimization-20261007/NEW_PROTECTED_HOOK_RUN
apps/control-api/.venv/bin/python -m pytest -q \
  adapters/runtime/hermes-agentshield/tests/test_host_runtime_image.py \
  adapters/runtime/hermes-agentshield/tests/test_host_session.py \
  adapters/runtime/hermes-agentshield/tests/test_host_control.py \
  patches/hermes/test_integrity_probe.py
```

脚本复用已有固定镜像、源码快照及专用网关模板，需要本机Docker与既有OpenShell工具链；不是任意机器一条命令即可通过的发行验收工具。保留已有online/image-profile入口语义，新`--integrity`入口独立选择受控实验。

## 清理与边界

002自有网关进程、沙箱、网络、原生宿主线程、验证socket和临时Authority均已结束／清理。日常网关模板、CLI元数据及TLS摘要保持不变。新派生镜像和忽略目录证据保留用于复核，未标记为生产镜像，未修改current-image。原始凭据只在临时私密状态，未写入公开证据。

管理员故障注入验证的是变化后的检测和拒绝，不代表能抵御控制宿主、Docker或内核的恶意root。Windows/macOS桌面同UID可替换钩子的原有限制仍在；普通安装诊断与本次受保护部署属于不同信任条件。完整发行制品的安装／升级身份核对及最终业务候选、平台验收继续，不能因本批联验通过而提前关闭OPT-12或全项目。
