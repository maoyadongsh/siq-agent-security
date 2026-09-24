# 真实 OpenShell 上下文与部署预览验收（E149）

日期：2026-09-23。承接 E148；总目标 active，SEC-F 后续清单不插队。当前候选完成真实握手、策略读取和部署前检查，未执行运行时策略写入。

## 结论与用户影响

E148 的证书错误已查清：验收进程只传了 XDG_CONFIG_HOME，遗漏项目证书所在的 XDG_STATE_HOME。使用项目现有完整目录上下文后，HTTPS 网关握手恢复，未关闭 TLS、更换证书、重启服务或改写用户配置。后续接入时应继承同一项目的配置和状态目录，不能把“找到登记”当成“证书上下文完整”。

实际联调同时发现并修复三个产品问题：

1. Python/Go 显式连接的指纹未完整绑定配置及证书目录。现将传给 CLI 的 HOME、Windows 用户目录和 XDG 目录纳入摘要；切换项目上下文后旧缓存/计划/部署预览失效。只处理目录输入，不读取私钥；仍不能证明同一路径内容不会被并发替换。
2. 真实 v0.0.83 status 使用 `Version:`，旧解析器只认 `Gateway version:`，造成网关版本显示 unknown。两端保留旧格式，并对结构合法的 Server Status 接受 Version；重复/冲突版本保持 unknown，CLI 版本和 endpoint 不替代网关版本。共享 9 份向量确保对等，没有上调执行能力。
3. Python 策略读取只认 endpoint 的 host/port，遇到真实研究沙箱的 REST、方法/路径和 IP 限制即拒绝。现与已有 Go 读回语义对齐，保留 protocol/enforcement、每条 allow 的 method/path、CIDR 和布尔凭据改写标记；未知字段/模式、deny 规则或无效结构继续拒绝。扩展投影不能进入仅 L3/L4 的写入器，防止丢掉限制后扩大权限。原始完整策略仍作为 digest 与计划事实源。

## 真实链路证据

新增可复验脚本 `scripts/enterprise-experience/openshell-preview-live-check.py`，运行隔离开发控制面，通过真实 API 登记环境/绑定、提出策略及由另一身份审批，随后调用部署预览。CLI 使用原生 OpenShell 0.0.83，网关 HTTPS 127.0.0.1:17671；未禁用 TLS 验证。

真实目标为已有研究验收 canary，证据只存目标摘要。提案是隔离数据库里的网络限制提案，不曾下发。脚本的命令守卫只允许 gateway info、status、版本和明确目标的 policy get，所有响应来自真实 CLI；不使用成功响应桩。旧摘要在 XDG_CACHE_HOME 变化、同一真实网关仍可访问时被提交接口 409 拒绝。

8 项真实检查全部通过：TLS 握手、观察到版本、API 绑定/审批、预览不写状态与审计、上下文不变摘要稳定、目录变化拒绝旧预览、策略前后相同、所有 CLI 命令只读。前后 revision 均为 **2**，策略 SHA-256 均为 `900e77138f185f927a734f3a8520ca3f44ca2f87763bc614acc992bebd0ba3c1`，Deployment 和 EdgeTask 均为 0。此次证据只证明配置读取和部署前检查；不代表已执行部署、Hermes 工具被拦截或业务结果已完成。

## 回归结果

| 验证 | 结果与范围 |
| --- | --- |
| API | 全量 **1050 passed**；较 E148 新增 24 项，覆盖目录上下文、失效缓存/预览、秘密不转发、共享版本语料、限制字段保真及拒绝降格写入 |
| 真实网关页面 | **19 项**：PATH 发现、多个真实登记、目标与策略选择、切换/刷新/失联恢复、登记漂移拒绝、手机操作；网关登记/默认选择/目标清单未变且无新增授权 |
| 企业部署页面 | E148 核心流程 **16 项**回归通过，实际 API、独立读回、旧预览拒绝及响应丢失核对 |
| 个人结果页面 | 最终候选 **32 项**通过 |
| Go | **44 个测试包**、vet、产品包 gofmt 及 OpenShell 聚焦 race 通过；四目标 Linux amd64/arm64、macOS arm64、Windows amd64 构建通过 |
| 静态检查 | API 与新增脚本 Ruff、git diff --check 通过 |

本批未改前端源代码、合同或数据库结构。企业页面复用已验收 E148 构建，本地候选重新编译并引用原嵌入 UI；不重复将 E148 的 Web 测试数标为本批新增验证。已查看真实网关手机截图。已有 Starlette/httpx 弃用提示保留。

初轮只读脚本把不存在但非必需的数据目录当作必需，已改为校验真实 config/state；第一次真实策略读取因限制字段不支持失败，修复并加负向测试后完整重验。失败记录不计为通过。

**E148 记录勘误**：其末次诊断中的 TypeError 来自对 SandboxPage 结果调用 `len()`，不是 list_targets 缺少参数；该方法的 cursor 有默认值。E148 旧报告与哈希保留，当前解释以本条及真实 E149 证据为准。

## 复验、回滚与剩余任务

[E149 证据](../evidence/flagship-optimization-20260921/ux-openshell-live-preview-e149.json) 绑定源文件、日志、截图、真实结果和本地候选。现场复验需选定已存在的目标和新的输出目录：

```bash
apps/control-api/.venv/bin/python scripts/enterprise-experience/openshell-preview-live-check.py \
  --cli /home/maoyd/siq-research-engine/var/openshell/toolchains/v0.0.83/bin/openshell \
  --endpoint https://127.0.0.1:17671 \
  --xdg-root /home/maoyd/siq-research-engine/var/openshell/xdg \
  --target siq-analysis-canary-27d1289f98fa \
  --out-dir var/flagship/ux-e149/recheck-live
```

验收不留下用户网关或沙箱变更，临时控制面数据库及签名材料退出后清理。产品回滚仅限本批目录指纹、版本读取、Python 限制投影及对应测试，不恢复整个脏工作区、不重写历史证据。未提交、推送、发布或替换已安装应用；Hermes 0.21、OpenClaw 和模型配置保持原基线。

当前证书上下文问题已解除，不能再作为真实接入阻塞。后续仍需部署持久恢复、独立验收沙箱中的真实写入/生效及业务输出验证；生产身份、多客户端并发、用户安装体验和发行验收未完成。
