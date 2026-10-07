# OPT-09 显式 CONNECT 通道与真实 OpenShell 差分验证

日期：2026-10-08（Asia/Shanghai）。状态：本批通过，OPT-09 继续 implementing。

## 结论与覆盖范围

在 DGX Spark 本机的独立 OpenShell v0.0.83 网关／沙箱中，同一受保护 ELF 的两个路径经显式 HTTP CONNECT 代理访问同一受控回显接收端，完成三轮真实差分：允许路径三次连通，未授权路径三次收到明确策略拒绝，六次主机前后对照均成功。随后只修改网络策略，为原拒绝路径增加授权，该路径收到回显；旧观测随策略 revision／digest 变化失效。

这是实际 OpenShell 网络策略的程序路径管控证据，解决了此前原始 TCP 两臂均拒绝、无法归因的问题。它不替代 SIQ 原生 Agent／Skill 权限验收，也不表示企业生产 API 已完成行为验证接线。真实沙箱测试使用合成 tenant／deployment／operation 绑定；持久台账另行以合成观测测试，二者不拼接为生产端到端验收。

公开原始观测、制品身份、独立程序保护事实、接收端标识与清理结果见 [机器证据](evidence/optimization-20261007/enterprise-behavior-connect.json)。前次直连失败见 [保护检查与原始 TCP 记录](optimization-opt09-protection-validation-20261008.md)，原记录不修改。

## 合同与实现

新增 challenge/v2、result/v3、agent/v2，保留旧 challenge/v1、result/v2、agent/v1 语义。挑战及前后／当前可信读回绑定显式代理 IPv4／端口。固定 ELF 只执行一次 CONNECT，不读取代理环境、不解析 DNS、不跟随重定向、不携带凭据。主机对照直接访问同一接收端。

CONNECT 200 后仍须逐字匹配含挑战 ID／nonce 的回显。只有 403、严格 JSON 的 `policy_denied` 错误和与目标端点完全一致的 detail，才能记为 `proxy_denied`。其他 403、502／503、错误目标、重复 JSON 键、异常正文、EOF、错误回显、超时等均不能证明策略拒绝；头与正文分别不超过 4096 字节，建连／CONNECT／回显共用原超时。

通道核对报告的制品摘要、实际路径、UID、目标、代理、挑战和期限。新校验器要求拒绝臂为明确 `proxy_denied`，不再将代理链路中的普通 timeout／connection_refused 当作策略有效依据。台账兼容新合同，持久领取、一次消费和事务审计保持。

本次专用网关使用明确批准的 `10.200.0.1:3128` 代理模板，而非采信工作负载 HTTP_PROXY。生产通用入口仍须实现可信代理配置归属核验；该本机固定模板不能泛化到任意远端代理。

## 真实运行身份与结果

| 项目 | 实际记录 |
| --- | --- |
| ELF SHA-256 | `0d8c89512c9f373725abf44595801fc2c16b3dd1f7a86f88e66ab50fdf49f7df` |
| 镜像 | `sha256:ea5c48273e4c11b782e788a734a32e3b8043f2d22e1c341e0f297482aae9eefc` |
| 网关 SHA-256 | `d3546877b42699fd93133698316262f8d03ed2683f53bdce8c1987db43210317` |
| 运行身份 | 从镜像独立解析 UID 998；探针核对非 root、NoNewPrivs 和零有效／允许／ambient capability |
| 文件保护 | 独立 Docker daemon 读取镜像／容器归属、root 所有路径和实际 ELF 字节，不以程序自报代替 |
| 允许路径 | `/opt/siq-behavior/allow`：3/3 CONNECT 200 且精确回显 |
| 拒绝路径 | `/opt/siq-behavior/deny`：3/3 CONNECT 403 且明确 policy_denied |
| 主机可达性 | 每轮前后各一次，6/6 回显成功 |
| 接收端效果 | 原挑战只收到 9 条标识，即六次对照加三次允许；授权反转的新挑战再收到 1 条 |
| 授权反转 | 同一原拒绝 ELF 路径、新 nonce、新策略 revision／digest：CONNECT 200 且回显 |
| 策略漂移 | 新策略下旧挑战／观测不再通过校验 |
| 清理 | 接收线程停止、沙箱删除、独立网关终止、空网络删除；原网关配置、TLS、CLI 注册元数据保持 |

这是一台机器、一个专用沙箱内的三轮差分和一次授权反转，不是大量独立样本、跨平台统计或延迟 SLA。真实测评未调用模型，未修改业务库，也未提升产品部署等级。

## 验证记录

- Python 相关集合共 172 个不同用例：新 CONNECT 43、旧 ELF 通道 39、协议 58、台账 32。首轮 163 项中 162 通过、1 项 schema 外部引用解析失败；将新结果 schema 的 binding 定义内置后，CONNECT 34 项通过，再新增版本混用、错误代理输入及台账漂移拒绝 9 项通过。分批存在重叠，不累加为更多样本。
- 43 项新用例包含真实 Linux ELF 对受控本机代理的网络访问及异常响应分类；该代理是测试夹具，不冒称 OpenShell。
- 新 ELF 与测试生成字节摘要一致；真实 Docker 文件保护 12 项通过，相关容器均清理。
- 真实 OpenShell 脚本 9 项检查通过，含三轮差分、接收端数量、策略变化、授权反转及清理。
- 公开材料离线复核：新 schema 校验、历史有效时间窗口内的协议校验、保护摘要绑定、9＋1 接收标识、新策略／新 nonce／相同制品核对均通过。历史窗口校验不表示证据在当前时刻仍可用于部署提升。
- Ruff、Go vet、gofmt 与 diff 检查通过。真实脚本执行后只调整 import 空行和长行换行，公开证据同时保留执行时与最终源码摘要。

定向测试入口（在 `apps/control-api`）：

```bash
uv run --frozen pytest -q app/tests/test_openshell_behavior_connect.py \
  app/tests/test_openshell_behavior_channel.py app/tests/test_openshell_behavior_protocol.py \
  app/tests/test_openshell_behavior_journal.py
```

真实复现工具为 `scripts/enterprise-experience/behavior-protection-docker-check.py` 和 `scripts/enterprise-experience/owned-openshell-recovery-check.py --behavior-image … --probe-sha256 …`。后者必须提供明确批准的专用网关配置／二进制，本批私有输出分别在 `var/optimization-20261007/opt09-connect-protection-001/` 与 `opt09-owned-connect-001/`。不向仓库提交运行目录或 TLS 材料。

## 后续工作

企业认证／授权协调、目标互斥、通用可信代理模板核验、真实收集器与持久台账的同次接线、前端及部署证据过期／漂移展示尚未完成。生产验证等级继续保持配置读回；OPT-09 不标 done，总体仍为 9/16。其他优化任务的剩余范围不因本批通过缩减。未推送远端、未运行远端 CI、未合并 main。
