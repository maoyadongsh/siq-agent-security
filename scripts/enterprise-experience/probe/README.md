# OpenShell 行为探针

`behavior_probe.go` 是 [ADR-058](../../../docs/adr/0058-enterprise-openshell-behavior-verification.md) 的有界 Linux ELF 观测程序。仅使用 Go 标准库，按固定位置参数执行一次 IPv4 TCP 回显。它不判断策略是否生效。

在仓库根目录构建（Go ≥ 1.22）：

```bash
mkdir -p var/behavior-probe
CGO_ENABLED=0 GOWORK=off GOPROXY=off GOOS=linux go build -trimpath -buildvcs=false \
  -o var/behavior-probe/probe scripts/enterprise-experience/probe/behavior_probe.go
```

部署时将同一 ELF 放入已批准镜像的两个受保护绝对路径；普通工作负载不能改写程序及其父目录。实际目标、镜像、文件摘要、用户身份和保护属性须独立核验，程序自报不是证明。禁止将探针或可信运行前提不满足的目标标记为行为已验证。

程序接口为 `probe VERIFICATION_ID NONCE IPV4 PORT TIMEOUT_MS`。地址与端口必须来自算子批准的受控回显接收端；ID／nonce 来自有效的持久领取。超时 100–10000 毫秒覆盖建连、发送与读取。只发送不含业务数据的 `SIQ-BEHAVIOR/1 <verification_id> <nonce>\n`，精确回显才记为 `connected`；输出受 [agent v1 合同](../../../packages/contracts/openshell-behavior-agent.v1.schema.json) 约束。执行前为全部 Go 线程设置 NoNewPrivs，核对内核 UID／GID一致、非 root、CapEff／CapPrm／CapAmb 均为零。

`enforcement_probe_agent.py` 属于旧 v1 历史探针通道，保留其原合同与证据语义。新生产接线使用 ELF 及新通道，不能用脚本路径代替实际 ELF 归因。

当前已有静态 ELF／本机 TCP／通道与独立 Docker 文件保护检查。真实 OpenShell 首次直连三臂中，两条路径都被拒绝；实际出网代理通道与程序路径归因、企业 API 接线仍待完成，不因静态检查通过而提升部署等级。
