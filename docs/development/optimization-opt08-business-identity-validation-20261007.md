# OPT-08 D3e：业务原生身份客户端与真实 HTTP 联验

日期：2026-10-07。状态：客户端实现及协议联验完成，日常业务接线未完成；OPT-08 保持 implementing，整体 9/16。

## 两个仓库的变更

| 仓库 | 本批改动 |
| --- | --- |
| SIQ Agent Security | 新增原生业务身份消费者合同；专属 Go 测试服务输出私有跨仓库联验输入；OpenShell runner 显式选择业务客户端探针 |
| SIQ Research Engine | 新增标准库原生 HTTP 客户端、49 项定向测试、独有联验探针与接入记录；独立分支 `codex/native-skill-business-20261007` |

业务基线 `47c0eda39119662a8f230c7a3b3bea97216abab6`，本批提交 `a08142c8316e623618d100c1e3e42f4a9dd3c796`，仅含上述四个新增文件。原有大量未提交修改保留，没有将其一并提交。客户端仅经公开 HTTP 合同接入，不导入安全产品内部实现，不读取其数据库；运行凭据保留在宿主。

## 客户端安全语义

原生 profile 严格接受 self/v2、request-identity-issued/v2 和 session-enrolled/v3，校验必需制品策略、父子身份、Grant、request/execution/scope、到期时间和派生会话。旧插件客户端保持不变。子凭据路径只能为父凭据同目录的精确派生身份文件，先完成签发响应校验再读取，并以子凭据再次自查。

凭据每次核对规范路径、私有父目录、当前用户、0600、单链接、读取前后元数据与路径身份；响应回显 token 即拒绝。网络固定 loopback 端口，不读环境代理、不重定向或重试。所有异常只给固定类别。取消沿既有父请求取消端点，父权限失效后仍尝试精确清理，不依赖 active self 预检查；只有服务端确认才报告取消成功。

## 实际结果

- 业务客户端定向测试 **49 项通过**，覆盖正向、版本/主体/策略/请求范围/路径不符、异常凭据、HTTP/JSON 失败、错误登记、取消失败和 token 回显。测试使用真实 loopback HTTP 夹具，夹具不是实际 Authority。
- 与真实 Go Authority 联验：运行子身份的幂等签发、子凭据自查和会话登记通过；另一个先前未签发请求由业务客户端首次签发、首次登记、取消，并确认取消后自查被拒绝。
- 同次实际 OpenShell/Hermes 原生链路 **18 项检查通过**。23 次工具尝试形成 18 条已校验签名回执（14 allow、4 deny），另 5 次在决策前拒绝；宿主独立核对文件效果。
- 父 Agent 基线撤销后，由业务客户端精确取消运行子身份，确认成功。该次 Go 集成段 22.721 秒。
- Ruff、Go 请求身份定向回归、server vet、diff 检查通过；独有沙箱与网络清理成功，原网关配置/TLS 摘要不变。没有改 Go 生产逻辑，未重复前端/控制面/Go 无关全量。

首轮 `opt08-business-identity-client-01` 已通过幂等接入和取消；补入首次签发与首次登记场景后运行 `-02`。保留两批原始结果，最终候选摘要以 `-02` 为准。

```bash
SIQ_NATIVE_BUSINESS_CLIENT_PROBE=1 python3 patches/hermes/run_openshell_runtime_probe.py \
  --online --output var/optimization-20261007/opt08-business-identity-client-02
```

显式开关仅影响这个独有联验脚本，不作为产品模式开关。输入包含凭据路径而非 token，位于本批私有临时目录；输出仅检查布尔值和源码摘要。完整结果见[结构化证据](evidence/optimization-20261007/native-business-identity-client.json)。

## 尚未证明的部分

客户端尚未接入智能分析助手日常 request builder、Supervisor 和业务撤权入口。当前 request ID、execution digest、操作员及 Skill 内容为合成材料，模型调用为零。真实用户授权、业务范围与执行租约仍由业务原有模块负责；后续必须把原生宿主监管、固定网关入口、业务取消/失效和模型工具调用接入同一候选，再做实际文件/网络效果验收。此批不提升生产启用或 OPT-08 完成状态。
