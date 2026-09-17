# R06/R04/R07 独立复核、修复与复测

日期：2026-09-15。基线 `efad8407c84b7b8f626cb06421287e7632c83a46`，工作分支 `kimi/personal-v4-r01-20260914`。

本批修复已落盘，未提交、推送、合并或发布。**允许接受本报告列出的修复和具体检查，不允许据此关闭 R06/R07/N09 的整体目标。** GLM 原始四目录及其 SHA256SUMS 未改动，完整性复验见 `original-evidence-integrity.json`。

## 1. 产品修复

1. `GrantsPage`、`ReceiptsPage`、`FindingsPage`、`PermissionsPage` 的加载 effect 随 guard 身份变化重新加载。此前 `/v1/status` 在页面首次请求期间返回，旧 guard 失效但 effect 不再执行，页面一直“加载中”。授权详情同时取消旧请求并清除旧选择。
2. `AdapterChangeDialog` 的实例、操作、连接模式、原生开关相同值事件为 no-op，不再清空预览后永久等待一个不会发生的 effect。
3. 本地 embed 已重建，不再沿用旧候选“二进制不变”的限制。本次未修改后端权限/签名实现、宿主源码、生产配置或发布信任根。

候选 SHA256：`5361966882f7bbdcfe44dbd942bbef1876ae93e043c744ea76158c8bdc80d942`。
重建命令：`npm run build:local`（apps/web），`go build -o /tmp/siq-review-candidate ./cmd/agentshield`（apps/agentshield）。
`source-sha256.json` 固定产品源码、embed 和执行脚本摘要；四目标 CGO=0 构建见 `cross-builds.json`，它们是构建证据，不是同一实机二进制的运行验收。

## 2. 修正的验收误报

| 原问题 | 修复与新的断言 |
| --- | --- |
| 页面刷新最多六次，掩盖加载竞态 | 每次只导航一次。单独浏览器测试延迟真实 API 响应，使 status 在列表响应之前触发 guard 变化；旧候选失败，新候选四个页面通过 |
| `refuse()` 把所有 RuntimeError 当拒绝，包括 `expected 200, got 201` | 严格匹配预期状态（通常 409，patch-desired 状态机拒绝为 400）；201、401、404、500、超时不得冒充完整性拒绝。新增负向单测 |
| UP03 只篡改请求签名 | 保留签名篡改独立检查，新增真实隔离 update-stages/payload 内容篡改，携带原有效签名提交，要求 409 changed，原安装目标和两个 Grant 不变 |
| UP07 把外部源改变等同导入快照改变 | 错误 snapshot digest 明确 409。导入快照与原目录分离；UP10 外部源消失时比较仍为 200，内容差异、Grant 与已安装目标不变。UP07 状态兼容不由此关闭 |
| 重启后另开浏览器，不能证明旧会话失效 | 同一已登录文档保持不变；重启后旧 admin 返回 401，页面实际请求显示失效并重新配对；回执及 runtime identities 前后相等 |
| 原文仅检查“清理成功”文案，实际没有密文 | 真实 OpenClaw 任务：授权前 0 条，按任务授权后真实参数/输出 2 条；撤销后真实允许读取继续，但密文仍为 2 条；UI 清理前后真实未到期密文摘要和签名回执完全一致 |
| 未检查默认导出隔离 | 真实 `/v1/export` 无原文仓、ciphertext 或 bearer，原文密文与回执未改动。未保存含身份数据的导出原文 |
| LC09 清空状态后重装冒充保留状态重入 | systemd 测试在同一状态注销→重新注册→启动→teardown，保留身份、配置、服务源和密钥摘要；不是正式发布包安装验证 |
| 调试转储包含配对码且权限宽松 | 原有 25 个诊断/运行日志收紧权限。新诊断只记录异常类型、阶段和计数，目录 0700/文件 0600；不存页面、截图、响应体、daemon 原文；失败检查摘要独立落盘，旧报告路径禁止覆盖 |

## 3. 验证与复现

| 检查 | 结果 | 证据 |
| --- | --- | --- |
| 旧候选加载竞态负例 | 预期失败：列表持续加载 | guard-old-candidate-failure.log |
| 新候选四页面浏览器竞态 | 4/4 | guard-new-candidate.json |
| 真实 OpenClaw 更新链 | 30/30，exit 0 | r04.json |
| 真实浏览器 + daemon + OpenClaw | 25/25 + 嵌套 R04 30/30，exit 0 | r07.json |
| systemd 用户服务保留状态重入/清理 | 1 passed，exit 0 | systemd-retained-reentry.log |
| 验收误报与诊断泄漏回归 | 7 passed，exit 0 | harness-tests.log |
| Go vet / 全量测试 | exit 0 / exit 0 | go-vet.log / go-tests.log |
| Web 测试 / 企业构建 / 本地构建 | 95/95 / exit 0 / exit 0 | web-tests.log、web-build.log、web-build-local.log |
| 改动 Python 脚本 Ruff | 通过 | ruff.log |
| Linux amd64/arm64、macOS arm64、Windows amd64 交叉构建 | 4/4 | cross-builds.json |
| N09 同候选逐项矩阵 | 完整性及 coverage 校验通过，零 complete_acceptance | n09/ |

原有 Go 全量测试包含原文过期删除、导出隔离、旧/未来状态写入拒绝的组件负例。本轮没有把组件时钟注入当实机经过一小时，也没有声称重跑 Python 业务 API 全量套件或新的 race 门禁。

从仓库根执行；本机 `python3` 已装 Playwright（control-api venv 未装，不改变其依赖）：

```bash
python3 scripts/personal-experience/r07-linux-user-journey-smoke.py --guard-only --openclaw-root <真实安装根> --node <node路径> --binary <本次候选> --out <全新结果路径>
python3 scripts/personal-experience/r04-openclaw-native-update-smoke.py --openclaw-root <真实安装根> --node <node路径> --binary <本次候选> --out <全新结果路径>
python3 scripts/personal-experience/r07-linux-user-journey-smoke.py --openclaw-root <真实安装根> --node <node路径> --binary <本次候选> --out <全新结果路径>
SIQ_TEST_SYSTEMD=1 SIQ_TEST_BINARY=<本次候选> apps/control-api/.venv/bin/python -m pytest -q scripts/personal-experience/test_systemd_user_service.py
apps/control-api/.venv/bin/python -m pytest -q scripts/personal-experience/test_review_journey_harness.py
python3 scripts/personal-experience/n09-baseline-check.py --matrix docs/evidence/personal-experience/r06-r04-r07-review-20260915-223037/n09/matrix.json
```

运行脚本使用隔离 HOME、真实 OpenClaw 2026.5.12 / Node 22.22.1、真实 Chromium 和本地确定性模型 fixture，不调用付费模型或外部业务服务。浏览器操作是自动化，不是人工视觉验收。验收开发过程发现的环境/选择器/会话错误见 `review-attempts.json`；失败不改写成通过，不覆盖 GLM 旧报告。

## 4. 剩余任务与执行次序

1. **R06 发行生命周期证据补齐**：用独立可追溯构建记录、对应源码 revision、发行清单和二进制摘要复现正式 v1→v2/中断/回滚；归档每个 LC 的原始退出码和安全日志，补撤权跨重启。不能补造此前丢失的日志，也不以不同版本标签替代版本兼容验证。
2. **R06→R07 串联**：让正式安装实例的 systemd 服务直接承载浏览器/宿主旅程；当前 R07 是复制候选后直接 serve。保留现有单独 systemd 回归；不得因它通过而关闭安装串联。
3. **R04 UP05/UP07/UP10**：补真实并发操作员的确定性交错、已部署旧/未来/损坏签名状态对全部相关写入口的验证；真网断连需合法可达生产来源，不能绕过 198.18/15 与 SSRF 防护。
4. **R07/N09**：真实到期密文删除、任务级导出生命周期、同候选 J8 原生必要调用故障、通知实际可见性。审批 HTTP/UI 腿不能冒充宿主 hold 消费；OpenClaw 仅 controlled_session，不声称 controlled_task。
5. **外部协作**：sunbo 的 Windows、Luke 的 macOS 原任务不变；WorkBuddy 和真实 OpenShell 网关缺口保留。N09 仍 partial，T01–T06 继续遵守原前置门槛。

## 5. 收尾与恢复

两个 GLM 遗留测试用户单位先核实 UID、MainPID、可执行文件、状态目录和 FragmentPath，再通过各自产品 `teardown --confirm-teardown` 停止并注销；状态保留，25173/25177 已无监听。新建测试服务自动清理，当前无本批 fixture 进程残留。见 `previous-test-service-cleanup.json` 和 `final-cleanup.json`。未操作日常配置、其他用户单位、兄弟仓库或远端。

需要回退产品修复时，以基线为依据单独审阅恢复五个 Web 文件与相应 embed；保留本批和原 GLM 证据。不要 reset/clean 工作树，它还包含尚未提交的 GLM 成果。当前修改尚未形成提交，不提供误导性的 revert 指令。
