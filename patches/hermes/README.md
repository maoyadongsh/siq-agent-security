# Hermes 固定镜像原生接入候选

用于 OPT-08 的实际原生函数接线，合同见 [native-hermes-dispatch/v1](../../packages/contracts/native-hermes-dispatch.v1.md)。仅适用于镜像 `sha256:fe5bdcebbc09b2099a3b387a675a4e8d879b8491bdc6246d93fbc8abb51e1f02` 内 `/opt/hermes-agent` 的固定源码；不是任意 Hermes 版本补丁，也不改变旧插件安装行为。

`build_native_overlay.py` 先核验六个原文件摘要，输出新的目录和逐文件摘要清单，不修改源目录，不覆盖已有目标。输出必须覆盖到同一固定镜像的相同原生路径，并将 `siq_native_runtime` 包作为受保护只读代码加载。补丁覆盖实际任务作用域、普通/插件 Skill 主文件与支持文件、缓存命中核验、最终 registry handler 门禁与调用 ID 传递。内联 Skill 预处理在此 profile 中禁用，普通文本仍返回；Agent loop 的直接处理、上下文引擎和动态 memory provider 尚无最终接线，顺序/并发执行器及直接 helper 调用均明确拒绝这些路径，不绕过到普通授权。

```bash
python patches/hermes/build_native_overlay.py \
  --source /absolute/extracted-pinned-source \
  --destination /absolute/new-candidate-overlay
```

可信 bootstrap 须先一次性配置 `Runtime` 的来源、最终授权和结果回调。未配置或回调失效时禁止调用；模型不持有或选择这些回调。测试回调只用于独立临时运行，不得用固定 allow 回调部署业务。Go 在线 Authority 桥接已提供显式接线；可信 OpenShell 启动器和真实业务验收未完成前，manifest 保持 `production_enabled=false`、`authority_bridge_connected=false`。

同一任务的调用串行以固定来源链；不同任务可并发。缺少精确父任务的 subagent 入口暂时拒绝。桥接不重置失败任务、不重复运行已消耗调用，不把函数 returned 解释为效果核验成功。受保护加载、签名权限、独立副作用观察与三平台支持仍须分别验证。

上游代码遵循 [MIT License](LICENSE)；此目录的原生片段修改由 SIQ 标识并保留归属。完整容器及其依赖的再分发仍需独立许可证/SBOM 核对。

现有 Hermes 安装使用目标与私密事务归属文件的硬链接对。新 profile 的可信 bootstrap 只有在接入 [实际安装来源解析](../../packages/contracts/native-install-source.v1.md)及实际只读挂载验证后，才可显式传入 `managed_installations=True`；默认不开放此模式，三条及以上链接始终拒绝。

实际进程核验组件及离线探针见 [D2f 验证](../../docs/development/optimization-opt08-runtime-guard-validation-20261007.md)。`run_runtime_guard_probe.py --output /absolute/result.json` 使用固定镜像和本次私有容器核对进程、代码、真实只读挂载与凭据通道；不调用模型，也不代表 OpenShell 日常后端已经接入。

在线覆盖包包含 `native_channel.py` 和 `native_online.py`，供受保护 bootstrap 配置回调。`host_online.py` 与宿主凭据不进入覆盖包；Go 与 Python 的各自在线联验见 [D2g](../../docs/development/optimization-opt08-online-validation-20261007.md)。
