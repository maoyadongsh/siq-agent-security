# Linux

当前宿主范围为 OpenClaw、Hermes；WorkBuddy 不排期，CodeBuddy 不新增接入。amd64 与 arm64 单独记录。0.4.0 已从固定提交 `2cd6116` 签发并公开，Linux ARM64 完成最终包全新状态启动；Linux amd64 仍只有构建与签名 pin 证据，两个架构的系统服务、升级/回滚和完整宿主旅程继续分别验收。

- 安装：从 [0.4.0 Release](https://github.com/maoyadongsh/siq-agent-security/releases/tag/siq-agent-security-v0.4.0)选择完整包，按[统一安装指南](../../docs/signed-release-packaging.md)选择对应架构、验签并首次 `start`。arm64 的这条实际链路已验证，amd64 未做本版原生安装。
- 日常运行/生命周期：[个人手册](../../docs/personal-client-operation-guide-20260916.md)、[本机 CLI](../../AGENTSHIELD.md)。前台启动、systemd 注册、登录自启、升级/回滚分别确认；沿用原状态目录，未知进程不清理。
- 开发与验收：[LX00–LX10](../../docs/linux-dual-host-integration-development-taskbook-20260918-205119.md)、[进度](../../docs/linux-dual-host-progress-20260918.md)、[影响其他 OS 的交接](../../docs/linux-dual-host-platform-handoff-20260918.md)。第六代功能与第八代 UI 候选的证据不互相继承。
- 宿主版本：[OpenClaw 受控入口](../../docs/openclaw-controlled-start-linux-20260919.md)、[固定补丁](../../patches/openclaw/README.md)。原版与固定补丁副本分开，不能把阶段 22/22 解释为上游原版已具备最终检查点。
- DGX Spark：[部署入口](../../deploy/dgx-spark/README.md)。GPU/CPU、模型/fixture 与实际使用模式分别记录；CPU fixture 不能作 GPU 推理证据。
- OpenShell：[Go 接入](../../apps/agentshield/internal/openshell/)、[企业接入](../../apps/control-api/app/adapters/openshell/)、[同步器](../../apps/control-api/app/openshell_sync.py)。沿用各控制面的合同；不自动启动网关或修改其他产品。

实际原生桌面、远端单任务停止与性能缺口见原台账；[评测索引](../../evaluations/README.md)提供结果身份，平台页不复制逐步日志。


## 源码、基础检查与功能验收

[运行时模块](../../apps/agentshield/README.md)、[Web](../../apps/web/README.md)与[宿主适配器](../../adapters/runtime/README.md)分别维护共享核心、界面和协议边界。平台生命周期按本页手册执行，不复制另一套实现到 platforms 目录。

[四目标源码原生检查](../../docs/evidence/repository-reorganization-final-20260919/README.md)已有本平台历史自建程序的准入与基础启动/配对/控制台/停止记录。它与 0.4.0 正式包使用不同候选，不等于本版系统服务、升级回滚、通知或完整宿主验收；后续验收仍需固定 0.4.0 程序、UI、适配器、宿主版本和状态格式，再记录允许、拒绝、撤销与恢复的实际结果。
