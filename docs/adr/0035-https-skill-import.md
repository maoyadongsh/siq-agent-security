# ADR-035：受限 HTTPS Skill 归档导入

状态：已实现并完成本批受控验证；UX-009 的下载链接入口，继续复用 ADR-033/034 的固定副本、准入和审阅。Git 仓库解析、认证来源、权限批准与平台安装仍属于后续完整目标。

## 请求与版本

新增管理 POST `/v1/skill-imports/remote`，严格 `local-skill-import-remote-create/v1`：import_id、url、archive_path、expected_sha256、actor_id 全部显式提供；archive_path 和 expected_sha256 可为空。只接受公网 HTTPS/443 ZIP，archive_path 为归档中的相对 Skill 目录，空值表示根层；不猜测多个目录，不自动运行任何脚本。CLI 对应 `import-skill --url URL --archive-path PATH --sha256 HASH --actor ACTOR`；后两项可省略，--url 与 --path 互斥。

下载导入使用记录/结果 v2，source_kind=https_zip，remote 记录归档字节数、原始 SHA256、最终 URL 摘要、所选归档目录和可选预期 SHA256。原始 URL（包括查询参数）只用于内存下载，不进记录/日志/卡片；source_locator_digest 为规范化 URL、archive_path、expected_sha256 的规范化 JSON 摘要。原始归档下载后不持久保存；归档摘要是签名的下载时事实，详情当前重新核对的是选中载荷和分析。

v1 本地请求、记录签名和结果保持不变，新增 remote 字段仅在 v2 出现。列表含 v2 元数据时返回 list/v2；全部本地时保持 list/v1。新前端同时理解两版；旧前端拒绝不认识的 v2，不把下载候选错误当作本地安装。新创建、本地/远端同 ID 冲突、重试均复用同一写锁和最终签名记录。既有候选匹配原请求后只读回，不重新下载；不同链接、目录或预期摘要冲突。

## 下载边界

URL 最多 4096 字节，仅标准 HTTPS、默认或显式 443；拒绝 userinfo、片段、控制字符、反斜杠、非 ASCII 主机、单标签或非法 DNS 名称、IPv6 zone 与非公网 IP。查询参数可以存在，但跨主机重定向不发送 Referer、Authorization、Cookie 等头。请求只使用固定 User-Agent、ZIP Accept 与 identity 编码，无代理、Cookie jar、用户 Git 配置或客户端凭据。

每次新连接显式解析 DNS，最多 32 个结果；任何结果为特殊/私有地址即拒绝，全部检查后最多尝试 8 个已经验证的字面 IP，禁止连接时第二次域名解析。禁用连接复用和 HTTP/2，重定向最多三次，每跳重做 URL 与地址检查，保留证书链/主机名验证。TLS 至少 1.2，连接 3 秒、TLS 握手与响应头各 10 秒；完整下载预算 45 秒，仍受外层导入取消/60 秒期限约束。

地址策略是保守的产品限制：IPv4 排除私有、回环、链路本地、共享地址、文档/测试、组播、保留及 IANA 专用块；IPv6 仅接受 2000::/3 内普通全局单播并排除 IANA 专用块，映射 IPv4 先还原检查，不允许 NAT64/6to4/Teredo 绕行。注册表不是网络隔离证明；本实现不防御恶意同 UID 的路由/信任库修改。来源：2026-09-11 查阅 [IANA IPv4 特殊地址表](https://www.iana.org/assignments/iana-ipv4-special-registry)、[IANA IPv6 特殊地址表](https://www.iana.org/assignments/iana-ipv6-special-registry)，两表标注更新日 2025-10-09。新增地址分配需后续维护；内网来源应有独立受控设计，不默认放开。

仅接受 HTTP 200，无透明解压，不接受额外 Content-Encoding；声明与实际下载均限 32 MiB，读取至上限+1 后拒绝。可选预期 SHA256 在解包前核对；无预期摘要时先固定本次获取内容供人审阅，不声称已确认发布者身份。ZIP 使用既有目录预检、CRC、路径/文件/解包预算；指定子目录前仍检查整个归档，所选目录必须含 SKILL.md。非选中内容仅在本次私有暂存中存在，完成复制后删除。

失败、超限、取消和校验失败不发布候选；禁止包含 URL 或下载响应正文的错误穿越 API/CLI。新错误固定为 skill_import_url_blocked / skill_import_download_failed / skill_import_archive_mismatch，加上原有 invalid/limit/interrupted 等。HTTP 管理分权、单并发、缓存禁止和恢复规则沿用 ADR-033。

## 验证

使用独立 TLS 测试服务和仅测试可替换的 DNS/拨号器，验证每跳地址检查、域名至 IP 固定、代理/Referer/凭据禁发、证书错误、重定向循环、混合 DNS、特殊地址、分块超限、压缩响应、取消和摘要不匹配；测试钩子不作为配置/环境变量暴露。覆盖旧记录签名、远端重试不联网、子目录选择、失败清理与合同样例。UI/CLI 接通后分别验证；控制 TLS 环境不冒充公网端到端或原生平台安装。

## 本批结果与证据边界（M19）

下载器、固定副本、管理 API、CLI 和个人审阅页已接通。四项 v2/remote 合同及 Go 输出样例由 Python 校验；旧 v1 样例保持兼容。下载器的私有测试拨号器把已校验的公网字面 IP 路由到独立本机 TLS 服务，正常证书链与主机名校验仍启用；真实 TLS 下载到签名副本、选中目录与离线重试由 Go 集成测试覆盖。此方法没有修改生产 DNS/拨号策略，也不是公网来源实测。

浏览器负向使用真实隔离 daemon 拒绝回环 URL；成功展示和响应丢失后的原请求重试使用明确的 Go DTO 响应夹具，没有伪造真实下载记录验收。原目录/ZIP 浏览器与 CLI/HTTP 独立验签回归在同一个 M19 候选通过。证据和剩余限制见 [M19 验证清单](../evidence/personal-experience/skill-import-https-20260911/verification.json)。本批不构成 UX-009 整项完成，仓库解析、私有来源、批准与平台安装仍需继续实现。
