# F06/R07：同候选 Linux 完整用户旅程（2026-09-17）

固定候选 `0b16e5e0…6c8177`（linux/arm64，[候选身份与源绑定](candidate.json)）在本机真实 OpenClaw 宿主 **2026.5.12 (f066dd2)** 上运行 R07 完整用户旅程：真实 daemon（候选内嵌 UI，`//go:embed all:embedded`，非 Vite dev 页）× headless Chromium 145.0.7632.0（Playwright 1.58.0）× 真实 `openclaw agent --local` 宿主进程与文件工具 × 本地确定性 model fixture（无外部/付费模型）。

命令：`python3 scripts/personal-experience/r07-linux-user-journey-smoke.py --openclaw-root ~/.nvm/versions/node/v22.22.1/lib/node_modules/openclaw --node ~/.nvm/versions/node/v22.22.1/bin/node --binary <本目录>/journey-private/siq-v6-hermes-post-e11-agent --out <本目录>/r07-journey.json`（脚本对 `--binary` 只做 copy2+sha256 复算，不重新编译；端口全部 127.0.0.1 随机分配）。

## 结果

**通过（attempt2）**：退出码 0，`{"passed": true, "checks": 25}`；[机器可读结果](r07-journey.json) `passed=true`、25/25 检查全 pass、`binary_sha256` 与候选一致、嵌套 r04 L2 更新腿 30/30。脚本自带 limitations 原文见结果 JSON。

| 旅程步 | 检查 | 结果 |
| --- | --- | --- |
| 原文默认关闭（前置） | step10a 新 daemon 原文仓 disabled / default_capture=false / 激活记录 404 | pass |
| 1 安装/配对 | step1 daemon 健康、产品身份 ready、local_mode | pass |
| 2 发现宿主 | step2 错误配对码被拒后真码配对成功；/bindings 发现真实 OpenClaw（发现安装文件） | pass ×2 |
| 3 grant | step3 /grants 显示已部署 V1 grant | pass |
| 4 真实宿主允许动作 | step5 无 SEC 原生读取 fail-closed deny（skill_attribution_mismatch）；step4 签发 SEC、授权读取 allow、controlled_session 归属 verified、call binding 重算一致、决策关联 grant+安装内容摘要+SEC | pass ×5 |
| 5 越权与 UI 一致 | /receipts 渲染同一 deny 决策（拒绝 + 匹配 reason） | pass |
| 6 审批与重放 | 敏感调用 hold 进入 SIQ 确认收件箱、UI 批准落回执、API 重放 resolve 409 拒绝 | pass ×3 |
| 7 Skill V1→取消→V2 | 嵌套完整 L2 更新腿（同一 daemon/宿主/fixture）：V1→取消→确认 V2→重授权→安全移除，30/30 | pass |
| 8 中断恢复 | daemon 重启后旧浏览器会话 401 失效、回执/身份持久不变、错误码重试后纯键盘重新配对 | pass ×2 |
| 9 回执/活动页 | 恢复后 /receipts 与 /activities 渲染零脚本错误 | pass |
| 10 原文与导出 | 设置页如实显示 opt-in 状态（默认采集仍关、限额可见、顶栏按任务授权）；到期清理字节级保留未过期密文与回执；默认导出排除密文仓与凭据 | pass ×3 |
| 11 移动宽度与卸载 | 390×844 视口确认收件箱可用；console 驱动卸载移除适配器状态且宿主 openclaw.json 保留 | pass ×2 |
| 12 退出管理 | 退出管理返回配对页 | pass |

**attempt1（保留不粉饰）**：[r07-journey.attempt1.failure.json](r07-journey.attempt1.failure.json)：同一命令同一候选，step1–7 共 16 检查全 pass 后，phase-c（daemon 重启后的浏览器段）一处 locator 等待超时（TimeoutError）。attempt2 原样重跑全绿，判定为瞬时等待 flake；脚本设计不落 DOM/截图（防配对码/凭据泄露），无法进一步定位具体元素，如实记录两轮事实。

## 前置核对（实测）

- 宿主：OpenClaw 2026.5.12 (f066dd2)，安装根含 `openclaw.mjs`+`package.json`；Node v22.22.1（openclaw wrapper 实际 exec 的同一解释器）；本机 aarch64 与候选 ELF ARM aarch64 匹配，原生执行无 qemu。
- 浏览器：Playwright Python 1.58.0，headless Chromium 145.0.7632.0 实测启动成功。
- 被测二进制指定：managed Harness 覆写继承的「编译 HEAD」build，对 `--binary` copy2 + sha256 复算相等后才启动；旅程两次运行报告内 `binary_sha256` 均等于候选摘要。
- UI 来源：daemon 内嵌 FS（`apps/agentshield/internal/ui/ui.go` `//go:embed all:embedded`）；脚本只浏览 daemon endpoint，全链路无 Vite dev server。
- 模型：本地确定性 fixture（进程内 ThreadingHTTPServer），无外部/付费模型。

## 宿主配置与清理核对

- 旅程全程在隔离 HOME（`<temp>/home/.openclaw`）安装/卸载适配器：step11 实测适配器状态移除且 fixture 宿主 openclaw.json 保留。
- 真实宿主配置零漂移：`~/.openclaw/openclaw.json`、`~/.openclaw/agentshield.json`、`~/.openclaw/exec-approvals.json` 运行前后 sha256 逐一相等（详见 [resources.json](resources.json)）。
- 清理：脚本 stop()/browser.close()/TemporaryDirectory 自动收尾；实测无本批 daemon/node/chromium 进程残留、无 `siq-r07-user-journey-*` 临时目录残留；attempt1 诊断目录已删；其他批次的历史进程与目录未触碰。

## 限制（不关闭的格）

- headless 浏览器只证明传输/API/渲染 DOM 行为，**不关闭 GUI 视觉格**；桌面 OS 通知不在本腿。
- 自动化浏览器操作员不是人工验收；step1 是 fixture 复制二进制而非 R06 已装 systemd 服务；step6 是 HTTP 决策+浏览器批准，非原生宿主 hold 消费/exactly-once；step5 只覆盖缺 Authority（无 SEC）越权；归属为会话级（controlled_session）；step10 到期删除由组件时钟测试另覆盖。
- 其他 OS（Windows/macOS）与其他宿主仍按各自实机证据独立验收；本腿不转移。

## 文件

- `r07-journey.json` — 通过轮机器可读结果（含 25 检查与嵌套 r04 腿 30 检查明细、limitations 原文）
- `r07-journey.attempt1.failure.json` — 失败轮原样保留
- `candidate.json` — 候选身份与源绑定（931 文件聚合 `ba8d266e…`）
- `resources.json` — 进程/端口/临时目录/宿主配置前后摘要与清理核对
- `journey-private/`（0700，gitignore 命中）— 候选执行副本（0700）、前置核对与宿主配置快照（0600）
- `SHA256SUMS` — 公开文件摘要
