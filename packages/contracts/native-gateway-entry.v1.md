# 原生 Hermes 网关入口 v1

本接口连接受保护 ImageBootstrap 与固定 Hermes 镜像中已有的 `gateway.run.main`。它不签发身份、不批准业务访问、不替代业务仓库的用户授权、租约、模型配置或 OpenShell 监管。

固定启动命令为 `/opt/siq/hermes/venv/bin/python -I -B /opt/hermes-agent/hermes-gateway <agent_id> <session_namespace> <channel_directory>`。仅接受三个非秘密参数，均由可信业务启动器固定；不接收任意模块、命令、配置路径或额外 CLI 参数。入口文件及 native_gateway 模块必须加入候选制品并由宿主核验。

启动顺序：

1. 拒绝任何 `SIQ_AGENT_SECURITY_*` 环境项，防止把旧插件凭据、代理或模式带入原生 profile。业务自身的 API key 和已有模型配置仍由业务入口管理，本模块不打印、持久化或转交这些值。
2. 创建 ImageBootstrap，输出一行 `SIQ_NATIVE_GATEWAY_READY=` 加严格 JSON ready 描述并 flush。描述仍为 `unverified`，只供可信宿主发现实际进程和通道；业务 HTTP ready 必须另外核验。
3. 等待最多 60 秒完成宿主通道配置，成功后才导入固定 `gateway.run.main` 并在同一 PID 内运行，不 fork/exec 第二个 Hermes 进程，不手工制造任务或指定 Skill。
4. Python 层 argv 固定为 `gateway/run.py`，不把原生参数交给网关解析器。内核 argv 保持实际启动命令，宿主可继续逐次核验；`hermes-gateway` 名称兼容上游已有的专用网关进程识别。
5. 入口失败只输出固定类别并返回非零；正常返回和 Python 异常均关闭本次初始化。上游网关的既有强制退出路径由 OS 关闭描述符、宿主 pidfd 观察退出，不把清理意图当作执行回滚。重启须由所属业务启动器创建新的运行实例。

普通插件安装和旧 profile 不自动切换。业务集成必须同时采用宿主保管的原生子凭据、实际进程验证器及生命周期撤权；不能仅把旧启动命令换成此命令即宣称日常业务验收完成。此入口通过不会改变 manifest 的生产启用状态。
