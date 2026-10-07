# OPT-13：交付入口安全响应头验收

日期：2026-10-07。结论：本仓库范围内的本地 Go 入口、企业 Nginx 及受控反向代理链已完成本批验证，OPT-13 记为 done。客户生产网关、真实 IAM 联验和完整 DNS rebinding 攻击链不在本批实证范围内。

## 修复的问题与最终行为

原 Go 入口没有统一设置 CSP、frame、MIME 等浏览器防护头；部分错误响应和真实静态文件也没有统一缓存约束。现在主服务在 loopback、Host 和 Origin 检查前设置统一头，拒绝响应也有保护；独立 UI handler 使用同一实现。CSP 与企业入口原有策略一致，保留现有内联样式能力，未增加 HTML meta CSP，未放宽 CORS、Host 或 Origin 检查。HTTP 入口不设置 HSTS。

本地 API、HTML、配置和错误默认 `Cache-Control: no-store`。存在的 Vite assets 可使用一年 immutable 缓存；不存在的 assets，包括无扩展名的路径，返回 404，不能误走 SPA 回退。资产目录不展示目录内容。HEAD 与范围读取保持正常。

原企业 Nginx 在 `/assets/` location 中使用带 `always` 的长期缓存头，导致 404 也可缓存一年。本批按响应状态区分：仅 200/206/304 采用长期缓存，其余 no-store；HTML 仍 no-cache。健康端点设置单一 text/plain MIME 及 no-store，避免用附加 Content-Type 造成重复响应头。

## 实际验证

可复跑入口：[delivery-headers-browser-smoke.py](../../scripts/personal-experience/delivery-headers-browser-smoke.py)。完整脱敏记录：[delivery-headers.json](evidence/optimization-20261007/delivery-headers.json)。

| 验证层 | 结果 | 范围 |
| --- | --- | --- |
| 本地原生二进制 HTTP | 14 个用例通过 | HTML、SPA、JS、CSS、字体、HEAD、206、缺失资产、方法错误、配置、未授权、错误 Host、错误 Origin |
| 实际企业 Nginx | 12 个用例通过 | HTML、SPA、静态资源、404/405、健康 MIME、HEAD/206/304 及缓存 |
| 实际 Nginx 代理链 | 12 个用例通过 | `/agent-security/` 路径转发后的同一响应矩阵，安全头和缓存没有丢失 |
| 浏览器正常操作 | 通过 | 本地手动配对、刷新恢复、设置页导航、样式加载和退出；企业生产构建登录页及样式正常展示 |
| 浏览器负向 | 通过 | 本地与企业页面的内联脚本注入拒绝、跨源连接拒绝、CSS 冒充 JS 被 MIME 校验拒绝、iframe 嵌套拒绝；被阻断的连接在独立接收器没有收到请求 |
| Go | 45 个测试包通过、10 包无测试 | 全量 `go test ./...`、`go vet ./...`；server/ui/httpsecurity 三包 race 通过 |
| 构建 | 四目标通过 | linux/arm64、linux/amd64、darwin/arm64、windows/amd64；本机仅 Linux 原生执行 |
| 企业 Web | 生产构建通过 | `VITE_DEV_MODE=false`，base `/agent-security/`，本批没有修改 React 源码或重建既有本地嵌入资产 |
| 格式及已有检查 | 通过 | 受跟踪 Go 源码和本批新 Go 文件格式、新脚本 Ruff、已有 Nginx 静态头检查、diff 检查 |

每个 HTTP 用例核验 CSP、frame 限制、nosniff、Referrer、Permissions、缓存、MIME（适用时）以及未新增 ACAO/HSTS。38 是响应测试数，不是独立攻击样本数量。浏览器负向在真实文档响应的策略下插入合成测试元素，没有修改产品页面或伪造 CSP 结果。

固定镜像来自 Dockerfile 的 Nginx 1.29.7 引用，完整 digest 与实际平台镜像 ID 写入证据；没有使用浮动 latest 冒充固定候选。两个测试 Nginx 使用只读根、只读静态资源/配置、非 root UID、移除 capabilities、no-new-privileges，端口只发布到 127.0.0.1。使用本次专属 bridge，代理上游仅为本次静态容器；没有挂载凭据或访问真实业务服务。实际二进制使用私有临时 HOME/状态，配对信息只在内存处理，完成后停止本次 daemon 并清除本次容器和网络。

## 验收过程中的修正

首次格式命令发现原有忽略目录 `.tmp/fx01/refcalc.go` 未格式化；该文件不属于 Go 包或交付候选，未修改。受跟踪源码与本批新增 Go 文件格式检查通过，不能把原始 `gofmt -l .` 描述成完全无输出。

首轮静态 UI 单测的 CSS 文件名匹配仍假设 `index.local-*`，已按实际构建的 `index-*` 修正，随后全量 Go 与构建通过。首次浏览器环境使用 Docker internal 网络，本机 Docker 不向该网络发布端口，改为本次专属 bridge 和显式 loopback 端口；随后旧浏览器操作未展开新版“手动配对”区域，已修正。最终浏览器和 HTTP 验收完整通过；这些早期失败不计为通过。脚本异常输出已限定为固定类别，避免浏览器错误堆栈包含输入值。

## 复跑与边界

```bash
# 先构建企业 UI（使用既有依赖安装）
cd apps/web
VITE_DEV_MODE=false SIQ_AS_WEB_BASE=/agent-security/ \
  VITE_API_BASE=/api/agent-security/v1 VITE_IAM_URL=/api/iam npm run build

# 在仓库根，传入当前候选二进制与一个尚不存在的输出目录
python3 scripts/personal-experience/delivery-headers-browser-smoke.py \
  --binary /absolute/path/to/candidate \
  --web-dir apps/web/dist \
  --out-dir output/playwright/opt13-delivery-new-run
```

代理是隔离的真实 Nginx 进程和真实网络转发，但配置属于受控验收夹具，不能替代外部客户 Gateway/TLS 配置的读回。企业测试验证未登录入口，没有伪造真实 IAM 登录成功；正常管理会话正向来自本地真实 daemon。未测试完整 DNS rebinding，不把 Host 单点拒绝包装成完整攻击链防御。CSP 保留 unsafe-inline 样式，不承诺所有注入风险消失。零模型调用，零生产数据修改。

按用户要求，本批定向调试后仅执行一次相关 Go 全量/race/四目标构建；之后浏览器夹具的修正只复跑浏览器验收，没有再次重跑无关模块或全套前端单测。
