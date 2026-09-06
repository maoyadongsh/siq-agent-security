# AgentShield 能力 profile 与强边界声明（DEV18-A）

- 日期：2026-09-06
- 计划：[DEV18](development-plan-20260906-022735.md#dev18)
- 配套：规格 [`agentshield-dev-spec-v1.md`](agentshield-dev-spec-v1.md) §1.2 / §3.8.1 / §6；矩阵 [`skillmanifest/matrix.go`](../apps/agentshield/internal/skillmanifest/matrix.go)；证据索引 [`agentshield-capability-matrix-v1.md`](agentshield-capability-matrix-v1.md)；生产 runbook 模板 [`enterprise-production-runbook-v1.md`](enterprise-production-runbook-v1.md)
- 本文件是 **声明 + 边界**；OS×平台证据细节以能力矩阵为准。不是生产验收或独立对抗复核。

## 1. 本地信任配置

| Profile | 状态 | 防御对象 | 明确不承诺 |
| --- | --- | --- | --- |
| `desktop-same-uid` | **当前默认**（`GET /ui-config.json` 的 `trust_profile`） | 不可信 Skill 内容、错误权限、跨身份误调用（在 loopback + 文件权限范围内） | 同一 OS 用户下的 Agent/进程自批、读状态目录、卸载适配器 |
| `managed-linux` | **未实现** | 管理身份与 Agent 执行身份经 OS 权限/隔离挂载分离 | 不得用 TTY、第二个同 UID token 或一次性码冒充本 profile |

CLI `grant approve --approve-as` 仍直接写本地 Store（DEV03-B 单写者之前）。配对码只初始化浏览器管理会话，不是人类证明。

## 2. 主体能力（当前实现，desktop-same-uid）

| 主体 | 能做什么 | 不能（或未验证）做什么 |
| --- | --- | --- |
| 远程网页 / 网络客户端 | 若浏览器允许访问 loopback：请求 `127.0.0.1` | 无认证 `GET /ui-config.json` **不再**返回管理凭据。`Host` 必须是 `127.0.0.1` / `localhost` / `::1` + 监听端口，否则 403。非法 Origin / `Sec-Fetch-Site: cross-site` 的写请求 403。**完整浏览器 DNS rebinding 链未做真机验证（S2b）。** |
| 同机其他 UID | 受状态目录 0700 与 token 0600 限制 | 未做跨用户 ACL 实测；不是 managed-linux |
| 同 UID Agent | 读 `<state>/token`、跑 CLI、若能看到 `serve` 终端则看到配对码 | 决策 token 调管理 HTTP → 403；这 **不能** 阻止 CLI 批准 |
| 恶意 Skill / 配置 | 作为不可信输入被静态扫描 | 不被执行、import、eval；扫描预算与特殊文件见 DEV05-A/B；打开契约见 ADR-013 / DEV05-C（非同 UID 零窗口） |
| 浏览器控制台用户 | 用一次性配对码换 12 小时管理会话（5 次尝试、单次消费） | 刷新后 JS 会话丢失；码已消费则须重启 `serve` |
| 适配器 | `POST /v1/decide`、`POST /v1/observe` + 决策 token | 批准 / 卸载 / 改模式 / 导出 |
| 企业低权限用户 / 控制面管理员 | 不适用本机 daemon | 见控制面威胁模型；OIDC/JWKS 生命周期是 DEV08，未在 I0 关闭 |

## 3. L0–L3 证明强度

编译成功只说明制品可构建。下面各列必须单独有证据才可对外承诺。

| 档位 | 含义 | 当前诚实状态 |
| --- | --- | --- |
| L0 | 盘点 / 审计 | Hermes/OpenClaw/CodeBuddy linux 有 2026-09-05 隔离或实机归档；矩阵行仍是 `experimental` / Trae `audit_only` |
| L1 | 安装门禁 | OpenClaw `policy-exec` 有归档；Hermes 包装安装脚本；WorkBuddy 无安装前拦截 |
| L2 | 运行时决策 / 回执 | 三平台 linux 钩子/插件有归档；grant 由人类 `--approve-as` 批准 |
| L3 | OpenShell 网络策略 | `verify` 最高 `readback_verified`。**配置读回 ≠ 网络强制。** DNS/IP/重定向/IPv6/失联/替代进程路径未作为 enforcement_verified |

`support_matrix` **零行 `supported`**。跳过测试不得计通过。

## 4. S2b 浏览器 DNS rebinding（I0 记录）

| 项 | 记录 |
| --- | --- |
| 工程控制 | HTTP `Host` 允许列表 + 无 secret 的 ui-config + Origin / Fetch Metadata 辅助 |
| 真机浏览器版本 | **未记录** |
| 本地网络权限 / Private Network Access | **未记录** |
| 攻击者可控 DNS / TTL / 缓存条件 | **未记录** |
| 结论 | Host 修复是工程缺口闭合，**不是**完整攻击链复现或反证。不得用一个 httptest 冒充浏览器验证 |

## 5. 残余与后续

- DEV02 高影响批准挑战（digest/scope/revision/nonce/单次）：**A+B 聚焦验证通过**；受管 Linux 管理私钥隔离、S2b 真机：未做。
- DEV04 Python content_hash≡HashSkillDir + 私有 staging 再验（A+B+C+D 聚焦验证通过）；真实下载链、同 UID 防改写 OS 隔离：未做。
- DEV03 单写者 / CAS / hold / CommitGrant（A+B+C+D 聚焦验证通过）；崩溃级跨文件原子性：未宣称。
- DEV05 特殊文件/有界读/枚举预算 + ADR-013 打开契约（A+B+C 聚焦验证通过）；同 UID 零窗口、Windows 特殊文件矩阵、整任务验收：未宣称。
- 独立安全扫描、生产 PostgreSQL runbook、跨 OS 强隔离：未启动，缺口保留；见 [enterprise-production-runbook-v1.md](enterprise-production-runbook-v1.md)（均为 template/blocked，不得记通过）。
- OS×平台×档位证据索引：[agentshield-capability-matrix-v1.md](agentshield-capability-matrix-v1.md)（DEV18-C）；`L3_enforce` 全表 unverified。
