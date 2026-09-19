# 平台交付与验证

[Linux](linux/README.md) · [macOS](macos/README.md) · [Windows](windows/README.md) · [支持矩阵](support-matrix.md) · [当前开发](../docs/development/current.md)

本目录只组织操作系统、架构和宿主的入口，不复制运行时、适配器或权限实现。个人客户端的已签名安装与 main 源码构建分别进入[安装指南](../docs/signed-release-packaging.md)和[源码操作](../AGENTSHIELD.md)。企业多环境部署沿用 [Compose](../deploy/compose/)与[运维模板](../docs/enterprise-production-runbook-v1.md)。

0.3.1 是普通 Release；平台支持等级仍由实际证据限定。四目标已构建并验签，仅 Linux ARM64 完成本版实际安装链路；同版本的完整升级/回滚与所有宿主旅程尚未验收。已合入共享核心修改需要各平台按同一候选复测，不能继承其他 OS 的通过结果。

OS 负责路径、权限和生命周期，宿主负责配置、钩子和调用归属；Windows 原生与 WSL2 分列，DGX Spark 是 Linux 硬件环境，OpenShell 是执行后端。具体事实见[评测索引](../evaluations/README.md)、[平台范围决策](../docs/personal-platform-scope-decision-20260917.md)及源码/签名包实际能力声明。


开发者从[本地运行时](../apps/agentshield/README.md)与[适配器](../adapters/runtime/README.md)定位实现；[四目标源码检查](../docs/evidence/repository-reorganization-final-20260919/README.md)提供后续基础原生记录。比较平台时须同时固定 OS/架构、宿主版本、程序摘要、UI/适配器和状态格式；不能仅凭相同版本号或目录名合并结果。
