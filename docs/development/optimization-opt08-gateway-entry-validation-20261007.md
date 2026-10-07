# OPT-08 D3d：受保护初始化进入真实 Hermes 网关

日期：2026-10-07。状态：固定入口实现及离线真实网关启动通过，业务链路尚未接入；OPT-08 保持 implementing，整体 9/16。

## 实现与接入理由

既有 ImageBootstrap 只初始化原生运行，不能把运行配置带到 exec 后的新解释器。因此本批提供 `native_gateway.py` 与固定 `hermes-gateway` 入口：先初始化并输出 unverified 描述，宿主配置通道后，在同一 PID 内调用固定镜像的已有 `gateway.run.main`。实际任务和 Skill 仍由原生路径观察，入口不人工创建任务、不选择 Skill、不产生允许裁决。

入口只接受 Agent、请求 namespace、私有通道目录三个非秘密参数，不提供任意命令或模块接口。任何旧 `SIQ_AGENT_SECURITY_*` 环境项均拒绝，防止把旧插件身份/沙箱凭据和新宿主通道混用。异常只输出固定类别，SystemExit 字符串不打印；正常返回和 Python 异常均关闭初始化，既有上游强制退出仍由 OS 与宿主进程核验处理。

核对固定镜像发现，普通 CLI 可能通过 setproctitle 改写内核 argv，不宜在严格固定启动摘要的原生运行中使用；专用 `gateway.run.main` 是上游已有入口，不执行该 CLI 美化操作。新文件名 `hermes-gateway` 也被上游既有生命周期识别器识别。覆盖包记录入口与新模块摘要，旧插件与源镜像保持不变。

## 验证结果

| 范围 | 结果 |
| --- | --- |
| 固定入口单元测试 | 15 项通过：初始化顺序、同 PID 调用、旧插件环境拒绝、缺失/额外参数拒绝、初始化失败不启动网关、异常/退出关闭及诊断脱敏 |
| 入口与真实初始化定向回归 | 62 项通过；真实 fork 负向保留一条预期弃用警告 |
| 固定镜像中的真实网关 | 8 项通过：ready 为 unverified；启动 PID 等于 HTTP 健康 PID；精确 argv 匹配且启动后不变；真实健康 200；错误 key 401；API key 不在 argv；本次进程已退出 |
| 固定镜像原生函数回归 | 21 项通过，使用已有合成 Authority 回调；与网关启动证据分列 |
| 静态检查 | Ruff、diff 检查通过；未改 Go/控制面/前端，不重复其全量测试 |

网关探针在 network=none、只读根文件系统、无 capabilities、no-new-privileges 的独有 Docker 容器中运行，只写本次 tmpfs。使用合成启动 socket 协调初始化，没有提交任务或调用模型；该 socket 本身不能满足实际跨 PID namespace 的宿主认证，不将启动检查冒充 Authority 验收。

```bash
python3 patches/hermes/build_native_overlay.py \
  --source var/optimization-20261007/opt08-native-source \
  --destination var/optimization-20261007/opt08-native-gateway-overlay-01
python3 patches/hermes/run_native_probe.py --gateway \
  --overlay var/optimization-20261007/opt08-native-gateway-overlay-01 \
  --output var/optimization-20261007/opt08-native-gateway-startup-01.json
python3 patches/hermes/run_native_probe.py \
  --overlay var/optimization-20261007/opt08-native-gateway-overlay-01 \
  --output var/optimization-20261007/opt08-native-gateway-functions-01.json
```

源码、候选清单及原始结果摘要见[结构化证据](evidence/optimization-20261007/native-gateway-entry.json)。复跑时使用新的输出目录，保留既有结果。

## 真实业务接线剩余工作

只读核对 `siq-research-engine` 当前 `qwen38_request_gateway`、`qwen38_request_supervision`、请求身份消费者、候选 supervisor 和固定镜像 entrypoint 后确认：这些路径仍依赖 v1 插件身份/HTTP relay，并将运行 token 上传到沙箱。原生模式需要独立显式配置，不能仅放宽响应版本或把新入口塞入旧凭据路径。

下一步须在业务仓库原有授权与执行租约链中，接入原生身份客户端、宿主验证/转发、同进程网关入口及撤权监管；保留原有合法 profile，候选 profile 不静默回退。业务仓库当前存在大量既有修改，本批只读保留，没有把其未提交工作纳入本仓库。真实模型、真实业务 Skill、网络效果与同候选四组对照仍未验收，manifest 生产启用标记不变。
