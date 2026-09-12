# ADR-019：个人客户端管理会话恢复与本机配对恢复

- 日期：2026-09-10。
- 状态：M1 实施采用；限现有 desktop-same-uid 模式。
- 任务：UX-002、UX-003、UX-004、UX-012。

## 问题

浏览器刷新丢失内存管理 token，配对码却已经消费，导致用户必须重启决策 daemon。重启保护服务不是管理会话恢复的必要条件。bootstrap 仅检查 TCP 连通也会将其他程序误认为服务健康。

## 决策

保留管理、决策、效果观察的分权，新增只用于本机配对恢复的第四种凭据。

### 浏览器会话

- `POST /v1/pair` 兼容 `{code}`；新 UI 发送 `{code, remember:true}` 和 `X-SIQ-Session: 1`。
- 响应保持 `session`、`expires_in`、`scope`，增加 `schema_version:local-admin-session/v1`。access token 只在页面模块内存。
- remember 模式设置独立随机恢复 token 的 Cookie，服务端只索引其 SHA-256。Cookie 为 HttpOnly、SameSite=Strict、Host-only、Path=/v1/session，名称含监听端口，最长 12 小时，不延长原会话绝对期限。
- 本服务是仅 loopback 的 HTTP，Cookie 在该模式不设 Secure；TLS 请求设置 Secure。不能据此将 HTTP Cookie 方案用于企业/远端入口。Cookie 不隔离同一主机的其他端口，同 UID 风险仍存在。
- `POST /v1/session/restore` 要求 `X-SIQ-Session:1`，保持全局 Host/Origin/Fetch Metadata 检查；没有 CORS 授权。成功返回原会话及剩余期限，不产生无限滑动续期。
- `POST /v1/session/logout` 需要有效 admin bearer，注销当前会话及所有对应恢复凭据并过期 Cookie；其他独立管理会话不自动注销。
- Cookie 不被其他管理端点或决策端点接受；错误显式 bearer 不能回退为 Cookie 认证。
- 恢复入口和所有会话响应 no-store；失效 Cookie 清除；刷新并发不消耗一次性配对码。
- daemon 重启清除内存会话，旧恢复 Cookie 不能恢复管理权限。

### 本机重新配对

- `<state>/admin-recovery.token` 为独立随机 256-bit 凭据，仅本机 CLI/未来启动器使用，私有文件（0600，Windows 依赖用户 ACL）；适配器永不接收。
- `POST /v1/session/pairing` 只接受该凭据与 `X-SIQ-Local-CLI:1`，拒绝携带 Origin/浏览器 Fetch Metadata 的请求。
- 该端点只重置单次、5 分钟配对码，不发通用管理 bearer、不签发 Grant、不执行动作、不吊销已有会话。
- `siq-agent-security pair [--port N]` 从选定状态目录读取该凭据，在验证目标服务协议后请求新码并向操作者显示；不重新启动 daemon，不输出持久凭据。
- 旧配对码立即失效；记录不含码/凭据的审计。新码不会出现在无认证端点。
- 这是本机拥有者恢复路径，不是防同 UID 自批的机制。攻击者已控制同用户环境时仍可能读取此凭据，风险与当前威胁模型一致并明确保留。

### 服务识别

- `GET /healthz` 返回 `local-service-health/v1`、固定产品名、版本、`local_mode:true`、`status:ready`；无凭据或状态路径。
- `siq-agent-security status [--port N]` 只读并校验该合同，错误服务、重定向、HTML 和无效响应不被视为 healthy。
- `/ui-config.json` 增加 `product`、`schema_version:local-ui-config/v1`、`session_recovery:true`、`pairing_available`。保留旧字段语义供旧 UI。
- 新 UI 首次加载先验证服务配置并尝试恢复会话；401 进入配对，连接/协议错误进入可重试状态。

### 开发期启动入口

- `scripts/personal-experience/start-local.py` 接收明确指定、由操作者信任的本地开发二进制、状态目录和端口；不下载、不安装、不修改平台配置。
- 先调用二进制 `status` 验证协议，再检查 loopback 端口。未知服务占用端口时直接报错；不会终止其他进程。
- 空闲端口启动独立后台进程，轮询实际健康状态；不以固定 sleep 后的 TCP 连通作为成功。重复启动复用健康服务，不删除写锁。
- 后台启动不保存一次性配对码日志；用户通过 `pair` 命令获取新码。可选 `--open` 打开同一 loopback 地址。
- 当前签名 Skill 的脚本内容参与 `content_hash`，不能编辑后继续冒用旧签名。启动入口先在开发工具目录交付，UX-014 生成新版本制品时再整合进安装器和新 Skill 包。此工具依赖 Python，不计作“无开发工具安装”验收，不替代系统登录启动/系统服务管理。

## 兼容与验证

2026-09-12 UX-003/004 增量：增加 `/healthz/instance` 独立合同，返回规范化状态目录的域隔离 SHA-256 摘要。`status` 和 `pair` 在本机只读计算同一摘要并核对；启动器只复用匹配实例。旧 `/healthz` 仍保持原合同，新 CLI 遇到旧 daemon 不降低检查要求。具体算法和接口见开发规格 §3.11。该摘要不含路径原文，但可被猜测路径重算，不是秘密或永久设备身份；目录迁移需要重新定位，不提供防恶意同 UID 伪装或检查与后续请求之间的原子保证。后续安装器的稳定设备 ID 单独实现。

现有 API 的 bearer 权限不放宽。旧版 UI/CLI 仍可单次配对；新 UI 识别旧 daemon 的能力缺失并提供升级或重新配对提示。新 Cookie 不保证跨 daemon 重启恢复。

验证覆盖合法恢复、刷新并发、绝对过期、注销与重放、错误/缺失请求头、跨站/错误 Origin、决策与恢复凭据不能管理、旧配对码失效、错误端口服务与重定向拒绝。对应合同在 `packages/contracts/local-client-session.v1.schema.json`。
