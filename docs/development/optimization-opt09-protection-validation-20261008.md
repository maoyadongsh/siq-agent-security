# OPT-09：独立程序保护与首次真实 OpenShell 探测

日期：2026-10-08。任务保持 `implementing`，总体完整验收仍为 9/16。

**独立程序保护检查已通过；真实 OpenShell 原始 TCP 三臂未通过。** 最后一次真实尝试中，三个允许臂和三个拒绝臂都返回 connection_refused，六个边界外对照均 connected。校验器返回 `behavior_control_or_allow_failed`，部署验证等级没有提升。

## 已实现的保护能力

新增 `behavior_protection.py` 和 [保护事实 v1 合同](../../packages/contracts/openshell-behavior-protection.v1.schema.json)。观察器使用固定 root 所有的 Docker CLI／Unix socket，并通过内核 SO_PEERCRED 核对 daemon 的 root 身份；对镜像、容器、OpenShell 标签、运行状态、网络命名空间、启动模板及覆盖挂载进行独立检查。

通过 daemon 的只读 tar 归档读取探针及逐级父目录：核验 root 所有、禁止组／其他用户改写、拒绝链接／特殊文件／危险 ACL／capability 扩展，逐字哈希两份 ELF。流有大小、时间边界，不提取文件到主机，不在容器中运行检查脚本。Docker 归档接口依据见 [官方 API](https://docs.docker.com/reference/api/engine/version/v1.40/#tag/Container/operation/ContainerArchive)；本机的链接与归属行为另有实际负向验证。

显式区分无额外 capability 的普通非 root 容器和 OpenShell root 启动模板。后者只接受恰好 SYS_ADMIN／NET_ADMIN／SYS_PTRACE／SYSLOG 四项启动权限，模板来自操作员批准的配置。探针通过全部 Go 线程的 NoNewPrivs 设置及内核 UID／GID、CapEff／CapPrm／CapAmb 检查拒绝高权限执行；容器启动权限不等于探针工作负载权限。

这仍以可信操作员、Docker daemon 和已批准镜像／制品为边界；不宣称防御 Docker 管理员或同 UID 的主机绕过。企业 API 的实时授权与完整生产接线尚未完成。

## 验证结果与实际分母

| 验证 | 结果 | 范围 |
| --- | --- | --- |
| 保护观察器与加强后的 ELF／通道回归 | 84 项通过 | 45 项保护测试＋39 项已有通道测试，无跳过 |
| 最终 Unix peer 检查后的保护回归 | 46 项通过 | 含真实非 root Unix 服务端拒绝；与上一行重叠 |
| 最终真实 Docker 验证 | 12 项通过 | 实际归档／权限／字节；链接、可写文件、可写父目录、错镜像／namespace／sandbox ID、相同字节的只读覆盖挂载均拒绝；恢复权限后重新核验 |
| 真实 OpenShell 尝试 003 | 未通过 | 实际目标保护检查通过，12 次网络观测完成，按程序路径的差分未成立 |
| 工具与源代码检查 | 通过 | Ruff、Go vet、gofmt、diff 空白检查 |

真实 Docker 验证使用合成 OpenShell 标签，不计作真实 OpenShell 运行。尝试 003 由独立验证网关实际创建沙箱并经 CLI 执行，所用 tenant／deployment／operation 仍为组件标识，没有伪造企业部署台账已验收。最终新增 Unix peer 检查在 Docker 验证中通过；003 的失败记录早于该增量，不冒充整套最终候选验收。

三次真实尝试均已终止并清理自有沙箱、网关和网络，原网关模板、TLS 文件和 CLI 元数据保持一致；没有模型调用或业务数据库写入。

## 真实尝试中发现的问题

1. **001：启动模板不匹配。** 初版要求无额外 capability，拒绝实际 OpenShell root 启动配置。已引入固定、显式批准的模板，并加强探针自身低权限检查。
2. **002：测试配置误用了 UID 1000。** 固定基础镜像中的 sandbox 用户实际为 998。已改为在同一批准镜像的隔离只读容器中独立解析账户 UID，禁止采用探针自报值作为预期。
3. **003：原始 TCP 的允许臂仍被拒绝。** 允许与拒绝各三次均 refused，接收端只收到六次主机对照。原始观测保留，不能解释为按 ELF 路径验证成功；其后的策略漂移／显式授权反转步骤因前置失败尚未执行。

本机 OpenShell 构建源码中，代理网络模式向工作负载注入代理地址，nft 规则只允许代理及本地通信；这与本次直连被拒的现象一致。上游的[网络规则说明](https://docs.nvidia.com/openshell/dev/how-it-works/policies/network-rules)也要求区分连接路径、程序规则与目的地址限制。上游当前文档不是本机旧版本的实测替代，下一批需要直接核对目标的代理配置并执行绑定该配置的代理三臂。

## 下一步与复核入口

下一版协议显式区分原始 TCP 与受管 HTTP CONNECT 通道，绑定代理地址、目标端点和真实响应状态。HTTP 拒绝不能伪装成 TCP connection_refused，错误回显／服务故障继续不能作为有效阻断。完成协议和探针适配后重做真实三臂、授权反转、策略漂移，再接入持久协调／企业 API／前端。

本批记录：[enterprise-behavior-protection.json](evidence/optimization-20261007/enterprise-behavior-protection.json)。真实失败原始观测的可分享副本：[enterprise-behavior-direct-attempt.json](evidence/optimization-20261007/enterprise-behavior-direct-attempt.json)。历史记录不覆盖、不计入通过分母。

本地私有原始材料在 `var/optimization-20261007/opt09-protection-*` 与 `opt09-owned-behavior-001/002/003/`。网关配置、TLS／JWT 文件、完整日志不提交。运行工具分别为 `behavior-protection-docker-check.py` 和 `owned-openshell-recovery-check.py --behavior-image … --probe-sha256 …`，均要求新输出目录。后者默认原恢复验收模式仍使用 `--web`，两种模式互斥。
