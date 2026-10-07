# OpenShell 行为探针

`behavior_probe.go` 是 [ADR-058](../../../docs/adr/0058-enterprise-openshell-behavior-verification.md) 的有界 Linux ELF 观测程序。仅使用 Go 标准库，按固定位置参数执行一次 IPv4 TCP 或显式 CONNECT 隧道回显。它不判断策略是否生效。

在仓库根目录构建（Go ≥ 1.22）：

```bash
mkdir -p var/behavior-probe
CGO_ENABLED=0 GOWORK=off GOPROXY=off GOOS=linux go build -trimpath -buildvcs=false \
  -o var/behavior-probe/probe scripts/enterprise-experience/probe/behavior_probe.go
```

部署时将同一 ELF 放入已批准镜像的两个受保护绝对路径；普通工作负载不能改写程序及其父目录。实际目标、镜像、文件摘要、用户身份和保护属性须独立核验，程序自报不是证明。禁止将探针或可信运行前提不满足的目标标记为行为已验证。

程序接口为 `probe VERIFICATION_ID NONCE IPV4 PORT TIMEOUT_MS`。地址与端口必须来自算子批准的受控回显接收端；ID／nonce 来自有效的持久领取。超时 100–10000 毫秒覆盖建连、发送与读取。只发送不含业务数据的 `SIQ-BEHAVIOR/1 <verification_id> <nonce>\n`，精确回显才记为 `connected`；输出受 [agent v1 合同](../../../packages/contracts/openshell-behavior-agent.v1.schema.json) 约束。执行前为全部 Go 线程设置 NoNewPrivs，核对内核 UID／GID一致、非 root、CapEff／CapPrm／CapAmb 均为零。

`enforcement_probe_agent.py` 属于旧 v1 历史探针通道，保留其原合同与证据语义。新生产接线使用 ELF 及新通道，不能用脚本路径代替实际 ELF 归因。

显式代理接口为 `probe VERIFICATION_ID NONCE IPV4 PORT TIMEOUT_MS http_connect PROXY_IPV4 PROXY_PORT`，输出遵循 [agent v2 合同](../../../packages/contracts/openshell-behavior-agent.v2.schema.json)。代理地址同样必须经算子批准，程序不读取 HTTP_PROXY；CONNECT 200 后仍必须收到回显。只有 403 与严格匹配目标的 policy_denied 正文记 proxy_denied，其他代理失败不作为策略拒绝依据。响应头和正文分别限制 4096 字节，沿用单次总超时。

真实 OpenShell 初次直连失败记录保留；显式代理已完成同一目标三轮允许／拒绝／前后对照，以及给原拒绝路径授权后连通的反转检查，见 [CONNECT 验证](../../../docs/development/optimization-opt09-connect-validation-20261008.md)。持久台账已兼容新协议，但真实测评尚未经过企业认证协调 API／前端，部署等级保持配置读回。

内部协调器已连接批准模板、持久领取、每臂复核和同事务完成授权；真实专用网关／隔离数据库同次验证见 [持久协调验收](../../../docs/development/optimization-opt09-coordinator-validation-20261008.md)。普通用户入口尚未启用，不将合成审批身份视为生产认证。
