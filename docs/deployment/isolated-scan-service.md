# Linux 容器的隔离静态扫描部署

适用于 OPT-14 / [ADR-060](../adr/0060-host-isolated-scan-service.md)。
控制面镜像默认仍为非 root 用户 10001；宿主运行独立非 root 扫描服务。
每个样本启动新的 bubblewrap namespace，保持 256 MiB / CPU 3 秒 / 墙钟 5 秒预算。
这不是执行不可信程序的动态沙箱，也不是独立第三方认证。

## 部署前提

1. Linux 宿主已安装 bubblewrap，扫描服务用户实际能够使用非特权 user namespace。
   控制面容器保留默认 seccomp/AppArmor；不授予 privileged、宿主 PID 或 Docker socket。
2. 使用不同的非 root UID：例如扫描服务 1000、容器控制面 10001。生产建议专用服务账户；
   示例数字必须替换为部署实际身份。若 Docker 启用 userns-remap/rootless，先核实双方
   SO_PEERCRED 的真实 UID 映射，不能照抄容器内显示的 UID。
3. 服务目录只让所有者写：0710；socket 0660。目录组供控制面附加组访问，组成员无法
   替换目录内文件，服务仍核对准确 UID。只读挂载目录，不直接挂载 socket inode，便于重启。
4. 服务程序、解释器与依赖由部署管理员保护；不得让容器用户修改它们。服务环境不注入
   数据库、OIDC、签名种子或模型密钥。只部署同一候选的代码及 uv.lock 锁定依赖。

## 启动专用服务

由管理员预先创建并赋予扫描服务用户/共享组正确归属的目录，例如 `/run/siq-scan`，模式
0710。目录内不得已有 socket；服务拒绝覆盖旧路径。意外停机留下的 socket 需确认原进程
已退出，再由该部署的维护者清理；不提供按名字批量杀进程或强制覆盖命令。

以扫描服务用户运行（将路径替换为管理员安装的候选目录）：

```sh
cd /opt/siq-control-api
env -i PATH=/usr/bin:/bin LANG=C.UTF-8 \
  /opt/siq-control-api/.venv/bin/python -B -m app.scan_service \
  --socket /run/siq-scan/scan.sock --client-uid 10001 --concurrency 2
```

服务不接受任意命令参数或网络地址。关闭使用该服务自身的 SIGTERM/SIGINT；等待已有任务
在总期限内退出后，仅移除自己创建的 socket。不要将服务管理器的停止超时设为小于 10 秒。
部署服务管理器时应限制 cgroup 内存、进程数并禁用 core dump，且实测其 namespace 限制
不阻止 bubblewrap；本示例不宣称未验证的 systemd 模板已经可用。

## 容器配置

控制面三个配置：

| 环境变量 | 示例 |
| --- | --- |
| `SIQ_AS_THREAT_SCAN_ISOLATION` | `bwrap-service` |
| `SIQ_AS_THREAT_SCAN_SOCKET` | `/run/siq-scan/scan.sock` |
| `SIQ_AS_THREAT_SCAN_SERVICE_UID` | `1000`（宿主实际服务 UID） |

向控制面添加 socket 目录组（例如 `--group-add 1000`），只读挂载该目录到
`/run/siq-scan`。任何不匹配、缺失、权限异常、失联或过期响应均失败关闭。

仓库提供可选 Compose override：

```sh
export SIQ_SCAN_SERVICE_UID=1000
export SIQ_SCAN_SOCKET_GID=1000
export SIQ_SCAN_SOCKET_DIR=/run/siq-scan
docker compose -f deploy/compose/compose.yaml \
  -f deploy/compose/scan-service.override.yaml config
docker compose -f deploy/compose/compose.yaml \
  -f deploy/compose/scan-service.override.yaml up -d --build
```

基础 Compose 仍是显式开发身份/PostgreSQL 环境；生产须另满足原有 OIDC、PostgreSQL、
签名材料与受保护程序部署要求。此 override 不修改认证、审批、租户隔离或对外端口。

## 验收与运行观察

- 实际正常扫描返回绑定结果；恶意固定样本产生既有规则命中；这两个结果与原分析器对等。
- 超过 CPU/内存预算应分析失败，Finding/成功审计/Outbox 不应增加，资产不得半提交。
  下一正常请求能恢复；扫描繁忙/失联不影响治理健康接口。
- 错误客户端 UID 无法触发 worker，错误服务 UID 无样本发送，目录/端点替换拒绝。
- 用原生隔离探针确认宿主合成私有文件不可见、程序挂载不可写、宿主网络不可达。
- 按该候选记录 Docker inspect 中默认安全配置、服务/客户端 UID、镜像摘要和日志摘要。
  不把 Compose 配置渲染成功当作真实部署验收。

服务默认总并发为 2，控制面原进程配额继续生效；连接满时立即拒绝而不排队，故障不自动重试。
非法报文连接可直接断开/重置，错误文本不包含样本或自由异常。
历史 Finding 不回写；需要回退时停用该服务配置，仅在已验证的原生环境启用 `bwrap`。
生产不能回退到 `process`。

## 可复现实测入口

在已具备上述 Linux/Docker/bubblewrap 前提的开发验收机器上，以非 root 用户执行：

```sh
docker build -t siq-scan-candidate -f apps/control-api/Dockerfile apps/control-api
apps/control-api/.venv/bin/python scripts/scan_service/validate.py \
  --image siq-scan-candidate --output var/scan-acceptance/run-001.json
```

工具仅创建随机命名的自有容器、临时目录和扫描服务，使用开发身份/独立 SQLite 与合成样本，
无模型调用；退出清理自有资源，镜像保留。输出路径必须尚不存在，失败记录不得覆盖。
验收脚本会断开/重启它自己的扫描服务，不连接已安装的日常服务。
本机结果与前两次容器启动失败的说明见[验收记录](../development/optimization-opt14-host-service-validation-20261008.md)。
